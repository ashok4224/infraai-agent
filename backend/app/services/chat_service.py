"""Chat service — agentic conversation with confirm-before-execute diagnostics."""
import asyncio
import json
import logging
import time
import uuid as _uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession, ChatMessage
from app.models.alert import Alert
from app.models.ai_config import AIProviderConfig
from app.models.app_settings import AppSetting
from app.models.mcp_config import MCPServerConfig
from app.models.server_config import ServerConfig
from app.services.ai_service import analyze_with_ai, generate_raw_json
from app.services.pii_redactor import redact_text

logger = logging.getLogger(__name__)

_MAX_TOOL_CALLS = 6

_CHAT_SYSTEM_PROMPT = """\
You are InfraAI Assistant — an expert SRE / DBA conversational AI.

You help operators and engineers with:
- Understanding infrastructure alerts and their root causes
- Oracle Database administration (tablespaces, RAC, Data Guard, AWR, ORA- errors)
- PostgreSQL, MySQL, SQL Server troubleshooting
- Linux system administration (CPU, memory, disk, networking)
- Kubernetes operations (pods, deployments, services, networking)
- Writing and explaining SQL queries for diagnostics
- Interpreting monitoring metrics (Prometheus, Grafana)
- Incident response and remediation planning

Guidelines:
- Be concise but thorough. Use bullet points for clarity.
- When suggesting commands, specify the risk level.
- Format SQL and shell commands in code blocks with language tags.
- If you reference an alert, tie your answer to its specific details.
- If you don't have enough info, say so and ask clarifying questions.
- Never fabricate data — distinguish facts from educated guesses.

CRITICAL — LIVE DATA RULE:
When asked about live infrastructure state (how many clusters/instances/pods,
current counts, running resources, actual configuration, real-time status, what
is deployed, list of X in account Y), you MUST call the appropriate tool to get
real data. NEVER answer live-state questions from conversation history or
documents — those are stale runbooks/wikis and may be completely wrong.
Only use tools → synthesize from tool output.

Respond in plain text / markdown. Do NOT respond as JSON unless asked."""

_TOOL_PLAN_SYSTEM_PROMPT = """\
You are a diagnostic planning assistant. Given a user question and a list of \
available infrastructure tools, decide whether live diagnostics are needed.

Available tool types:
- Oracle databases   → type="sql",       include "query" (SELECT only)
- PostgreSQL         → type="postgres",   include "query" (SELECT only)
- MySQL              → type="mysql",      include "query" (SELECT only)
- Linux SSH servers  → type="ssh",        include "command" (safe read-only commands)
- AWS cloud          → type="aws",        include "service" (eks/ec2/rds/cloudwatch/s3/lambda), "operation", and "params" dict with ALL required fields for that operation (e.g. EKS list_nodegroups REQUIRES {{"clusterName":"<name>"}}, describe_cluster REQUIRES {{"name":"<name>"}}, describe_nodegroup REQUIRES {{"clusterName":"<name>","nodegroupName":"<ng>"}})
- Kubernetes         → type="kubernetes", include "verb" (get/describe/logs/top), "resource", optionally "namespace" and "extra_args"

RULES:
- Only plan READ-ONLY operations: SELECT queries, SHOW commands, safe OS \
  commands (df, free, top -bn1, uptime, ps, vmstat, iostat, etc.), or \
  AWS Describe/List/Get operations.
- NEVER plan DML (INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE), destructive shell commands, \
  or mutating AWS operations (create, delete, terminate, modify).
- Use the exact server_name from the available tools list.
- Maximum {max_tools} tool calls per plan.
- If the question is purely knowledge-based (concepts, best practices, how-to), \
  set needs_tools=false and provide a direct_answer.

Respond ONLY with valid JSON (no markdown fences):
{{
  "needs_tools": true/false,
  "explanation": "brief explanation of what you plan to check and why",
  "tool_calls": [
    {{
      "type": "sql",
      "server_name": "<exact server name>",
      "query": "<SELECT ...>",
      "description": "<what this checks>"
    }},
    {{
      "type": "postgres",
      "server_name": "<exact server name>",
      "query": "<SELECT ...>",
      "description": "<what this checks>"
    }},
    {{
      "type": "ssh",
      "server_name": "<exact SSH server name>",
      "command": "<safe command>",
      "description": "<what this checks>"
    }},
    {{
      "type": "aws",
      "server_name": "<exact AWS server name>",
      "service": "eks",
      "operation": "list_nodegroups",
      "params": {{"clusterName": "<cluster-name>"}},
      "description": "<what this checks>"
    }},
    {{
      "type": "kubernetes",
      "server_name": "<exact K8s server name>",
      "verb": "get",
      "resource": "nodes",
      "namespace": "",
      "description": "<what this checks>"
    }}
  ],
  "direct_answer": "<answer if needs_tools is false, else null>"
}}"""

_SYNTHESIS_SYSTEM_PROMPT = """\
You are InfraAI Assistant. The user asked a question and diagnostic data has been \
collected from live systems. Synthesize the results into a clear, actionable answer.

Guidelines:
- Reference the actual data collected — quote specific numbers, statuses, values.
- If any tool call failed, note the failure but still analyse whatever data is available.
- Use bullet points and markdown formatting for clarity.
- Provide recommendations if appropriate.
- Be concise but thorough.

After your main answer, suggest 3 short follow-up investigation questions in this exact format:
<suggestions>
[question 1]
[question 2]
[question 3]
</suggestions>"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def get_ai_mode(db: AsyncSession) -> str:
    """Read the current AI mode from app settings (defaults to azure_foundry)."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == "ai_mode"))
    setting = result.scalar_one_or_none()
    return (setting.value if setting else "azure_foundry").strip().lower()


async def process_chat(
    db: AsyncSession,
    session_id: UUID | None,
    message: str,
    user_id: UUID,
    user_email: str,
    context_alert_id: UUID | None = None,
    approve_tool_plan: bool = False,
    tool_plan_id: str | None = None,
    auto_investigate: bool = False,
) -> tuple[ChatSession, ChatMessage]:
    """Process a chat message and return the session + assistant response."""

    ai_mode = await get_ai_mode(db)

    # ── Get or create session ──
    session: ChatSession | None = None
    if session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        )
        session = result.scalar_one_or_none()

    # Always use azure_foundry — override any stale stored mode on existing sessions
    ai_mode = "azure_foundry"

    if not session:
        title = message[:80].strip() or "New Chat"
        session = ChatSession(user_id=user_id, title=title, ai_mode=ai_mode)
        db.add(session)
        await db.flush()
        await db.refresh(session)

    # ── Save user message ──
    user_msg = ChatMessage(session_id=session.id, role="user", content=message)
    db.add(user_msg)
    await db.flush()

    # ── Build conversation context ──
    context_parts = []

    # RAG Knowledge Base context (opt-in)
    try:
        from app.services.knowledge_retrieval_service import get_context_for_chat
        rag_context = await get_context_for_chat(message, db)
        if rag_context:
            context_parts.append(rag_context)
    except Exception as e:
        logger.debug("RAG knowledge search skipped for chat: %s", e)

    # Alert context if linked
    if context_alert_id:
        alert_result = await db.execute(select(Alert).where(Alert.id == context_alert_id))
        alert = alert_result.scalar_one_or_none()
        if alert:
            context_parts.append(
                f"[Context: The user is asking about alert '{alert.alertname}' "
                f"(severity={alert.severity}, status={alert.status}, "
                f"instance={alert.instance or 'N/A'}, category={alert.alert_category or 'general'}). "
                f"Summary: {alert.summary or 'N/A'}. Description: {alert.description or 'N/A'}]"
            )
            if alert.analysis:
                context_parts.append(
                    f"[AI Analysis available: root_cause='{alert.analysis.root_cause or 'N/A'}', "
                    f"risk_level='{alert.analysis.risk_level or 'N/A'}']"
                )

    # Load conversation history (last 20 messages to stay within token limits)
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id, ChatMessage.role != "system")
        .order_by(ChatMessage.created_at.desc())
        .limit(20)
    )
    history_msgs = list(reversed(history_result.scalars().all()))

    # ── Dispatch — always through Azure AI Foundry ──
    start_time = time.time()

    response_text, metadata = await _chat_with_foundry(
        db, history_msgs, context_parts,
        approve_tool_plan=approve_tool_plan,
        tool_plan_id=tool_plan_id,
        session_id=session.id,
        auto_investigate=auto_investigate,
    )

    metadata["latency_ms"] = int((time.time() - start_time) * 1000)
    metadata["ai_mode"] = ai_mode

    # ── Save assistant response ──
    assistant_msg = ChatMessage(
        session_id=session.id, role="assistant",
        content=response_text, metadata_json=metadata,
    )
    db.add(assistant_msg)

    # Update session title from first user message if still default
    if session.title == "New Chat" or session.title == message[:80].strip():
        session.title = message[:80].strip() or "Chat"

    await db.flush()
    await db.refresh(session)
    return session, assistant_msg


# ---------------------------------------------------------------------------
# Built-in AI — agentic two-step flow
# ---------------------------------------------------------------------------

async def _chat_with_builtin(
    db: AsyncSession,
    history: list[ChatMessage],
    context_parts: list[str],
    *,
    approve_tool_plan: bool = False,
    tool_plan_id: str | None = None,
    session_id: UUID | None = None,
) -> tuple[str, dict]:
    """Send chat through built-in AI provider with agentic tool planning."""
    from app.services.alert_analyzer import _get_ai_provider

    ai_config = await _get_ai_provider(db)
    if not ai_config:
        return "No AI provider is configured. Please set up an AI provider in System Configuration → AI Providers.", {}

    base_meta = {"provider": ai_config.provider, "model": ai_config.model_name}

    # ── Branch B: User approved a pending tool plan — execute it ──
    if approve_tool_plan and tool_plan_id and session_id:
        return await _execute_approved_plan(
            db, ai_config, history, context_parts, tool_plan_id, session_id, base_meta,
        )

    # ── Branch A: Normal message — plan tools if needed ──
    history_text = _build_history_text(history, context_parts)

    # Get the latest user message (last in history)
    user_question = ""
    for msg in reversed(history):
        if msg.role == "user":
            user_question = msg.content
            break

    try:
        tools_ctx = await _build_tools_context(db)
        if tools_ctx:
            plan = await _plan_tool_calls(ai_config, user_question, history_text, tools_ctx)
        else:
            plan = {"needs_tools": False, "direct_answer": None}

        if not plan.get("needs_tools"):
            # Knowledge-only question — answer directly
            direct = plan.get("direct_answer")
            if direct:
                return direct, base_meta
            # Fallback: normal chat call
            response_text = await _call_chat_ai(ai_config, history_text, _CHAT_SYSTEM_PROMPT)
            return response_text, base_meta

        # AI wants to run diagnostics — validate & build tool plan for user approval
        tool_calls = plan.get("tool_calls", [])[:_MAX_TOOL_CALLS]
        tool_calls = await _validate_tool_plan(db, tool_calls)
        if not tool_calls:
            # All planned calls were invalid — fall back to plain chat
            logger.info("All planned tool calls failed validation — falling back to chat")
            response_text = await _call_chat_ai(ai_config, history_text, _CHAT_SYSTEM_PROMPT)
            return response_text, base_meta
        explanation = plan.get("explanation", "I need to run some diagnostics to answer your question.")

        plan_id = str(_uuid.uuid4())
        tool_plan = {
            "id": plan_id,
            "explanation": explanation,
            "calls": tool_calls,
            "status": "pending",
        }

        meta = {**base_meta, "tool_plan": tool_plan}
        return explanation, meta

    except Exception as e:
        logger.exception("Chat tool planning failed: %s", e)
        # Fallback to plain chat
        try:
            response_text = await _call_chat_ai(ai_config, history_text, _CHAT_SYSTEM_PROMPT)
            return response_text, base_meta
        except Exception as e2:
            logger.exception("Fallback chat also failed: %s", e2)
            return f"Sorry, the AI service encountered an error: {e2}", {"error": str(e2)}


async def _execute_approved_plan(
    db: AsyncSession,
    ai_config,
    history: list[ChatMessage],
    context_parts: list[str],
    tool_plan_id: str,
    session_id: UUID,
    base_meta: dict,
) -> tuple[str, dict]:
    """Execute a user-approved tool plan and synthesize results."""
    # Find the assistant message that holds the plan
    plan_result = await db.execute(
        select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "assistant",
        ).order_by(ChatMessage.created_at.desc()).limit(10)
    )
    plan_msg: ChatMessage | None = None
    for msg in plan_result.scalars().all():
        meta = msg.metadata_json or {}
        tp = meta.get("tool_plan") or {}
        if tp.get("id") == tool_plan_id:
            plan_msg = msg
            break

    if not plan_msg:
        return "Could not find the tool plan to execute. Please try asking your question again.", base_meta

    tool_plan = plan_msg.metadata_json.get("tool_plan", {})
    tool_calls = tool_plan.get("calls", [])
    if not tool_calls:
        return "The tool plan has no diagnostics to run.", base_meta

    # Execute the approved tool calls
    results = await _execute_tool_calls(db, tool_calls)

    # Build synthesis prompt
    user_question = ""
    for msg in reversed(history):
        if msg.role == "user" and msg.content != "(approved tool execution)":
            user_question = msg.content
            break

    results_text = _format_tool_results(results)
    history_text = _build_history_text(history, context_parts)

    synthesis_prompt = (
        f"{history_text}\n\n"
        f"User's question: {user_question}\n\n"
        f"Live diagnostic results:\n{results_text}\n\n"
        f"Synthesize a clear answer using the diagnostic data above."
    )

    try:
        answer = await _call_chat_ai(ai_config, synthesis_prompt, _SYNTHESIS_SYSTEM_PROMPT)
    except Exception as e:
        logger.exception("Synthesis AI call failed: %s", e)
        answer = (
            f"I collected the diagnostic data but had trouble synthesizing it. "
            f"Here are the raw results:\n\n{results_text}"
        )

    answer, follow_ups = _extract_follow_ups(answer)
    tools_executed = []
    for r in results:
        tools_executed.append({
            "type": r["type"],
            "server_name": r["server_name"],
            "success": r["success"],
            "description": r.get("description", ""),
            "output": _normalize_tool_output(r.get("output")),
            "query": r.get("query"),
            "command": r.get("command"),
            "error": r.get("error"),
        })

    meta = {
        **base_meta,
        "tools_executed": tools_executed,
        "tool_plan_id": tool_plan_id,
        "suggested_follow_ups": follow_ups,
    }
    return answer, meta


# ---------------------------------------------------------------------------
# Helper: build text representations
# ---------------------------------------------------------------------------

def _build_history_text(history: list[ChatMessage], context_parts: list[str]) -> str:
    """Build a text prompt from context + conversation history."""
    parts = []
    if context_parts:
        parts.extend(context_parts)
        parts.append("")
    parts.append("Conversation history:")
    for msg in history:
        role_label = "User" if msg.role == "user" else "Assistant"
        parts.append(f"{role_label}: {redact_text(msg.content)}")
    return "\n".join(parts)


async def _build_tools_context(db: AsyncSession) -> str:
    """Query active MCP and SSH servers, return a text summary for the AI planner."""
    lines = []

    mcp_result = await db.execute(
        select(MCPServerConfig).where(MCPServerConfig.is_active == True)
    )
    mcp_servers = mcp_result.scalars().all()

    # Group MCP servers by type
    oracle_servers = [s for s in mcp_servers if (s.server_type or "").lower() in ("oracle", "oracle_db", "ora", "sqlcl", "")]
    pg_servers = [s for s in mcp_servers if (s.server_type or "").lower() in ("postgresql", "postgres", "pg")]
    mysql_servers = [s for s in mcp_servers if (s.server_type or "").lower() in ("mysql", "my")]
    aws_servers = [s for s in mcp_servers if (s.server_type or "").lower() == "aws"]
    k8s_servers = [s for s in mcp_servers if (s.server_type or "").lower() in ("kubernetes", "k8s")]

    if oracle_servers:
        lines.append("Available Oracle databases (use type='sql'):")
        for s in oracle_servers:
            desc = f" — {s.description}" if getattr(s, "description", None) else ""
            lines.append(f"  - server_name: \"{s.name}\"  ({s.oracle_host}:{s.oracle_port}/{s.oracle_service}){desc}")

    if pg_servers:
        lines.append("Available PostgreSQL databases (use type='postgres'):")
        for s in pg_servers:
            desc = f" — {s.description}" if getattr(s, "description", None) else ""
            lines.append(f"  - server_name: \"{s.name}\"  ({s.oracle_host}:{s.oracle_port or 5432}/{s.oracle_service}){desc}")

    if mysql_servers:
        lines.append("Available MySQL databases (use type='mysql'):")
        for s in mysql_servers:
            desc = f" — {s.description}" if getattr(s, "description", None) else ""
            lines.append(f"  - server_name: \"{s.name}\"  ({s.oracle_host}:{s.oracle_port or 3306}/{s.oracle_service}){desc}")

    if aws_servers:
        lines.append("Available AWS environments (use type='aws', services: eks/ec2/rds/cloudwatch/s3/lambda):")
        for s in aws_servers:
            desc = f" — {s.description}" if getattr(s, "description", None) else ""
            lines.append(f"  - server_name: \"{s.name}\"{desc}")

    if k8s_servers:
        lines.append("Available Kubernetes clusters (use type='kubernetes', verbs: get/describe/logs/top):")
        for s in k8s_servers:
            desc = f" — {s.description}" if getattr(s, "description", None) else ""
            lines.append(f"  - server_name: \"{s.name}\"{desc}")

    # SSH servers
    ssh_result = await db.execute(
        select(ServerConfig).where(ServerConfig.is_active == True)
    )
    ssh_servers = ssh_result.scalars().all()
    if ssh_servers:
        lines.append("Available SSH servers (use type='ssh'):")
        for s in ssh_servers:
            tags = f", tags={s.tags}" if getattr(s, "tags", None) else ""
            lines.append(f"  - server_name: \"{s.name}\"  ({s.host}, os={s.os_type}{tags})")

    return "\n".join(lines)


async def _plan_tool_calls(ai_config, user_question: str, history_text: str, tools_context: str) -> dict:
    """Ask AI to decide if diagnostics are needed and plan tool calls."""
    system_prompt = _TOOL_PLAN_SYSTEM_PROMPT.format(max_tools=_MAX_TOOL_CALLS)

    prompt = (
        f"Available tools:\n{tools_context}\n\n"
        f"Conversation so far:\n{history_text}\n\n"
        f"User's latest question: {user_question}"
    )

    result = await generate_raw_json(ai_config, prompt, system_prompt)
    if isinstance(result, dict):
        return result
    return {"needs_tools": False, "direct_answer": None}


async def _validate_tool_plan(db: AsyncSession, tool_calls: list[dict]) -> list[dict]:
    """Pre-validate AI-planned tool calls before presenting to the user.

    Guardrails applied:
      - Remove calls referencing non-existent server names.
      - Reject SQL with critical safety violations (DDL/DML).
      - Reject shell commands matching critical deny patterns.
      - Reject mutating AWS operations.
      - Enforce query/command length limits (8 KB max).
    Returns only valid calls; logs every rejection.
    """
    from app.services.safety import is_sql_safe, is_shell_command_safe

    _MAX_CMD_LEN = 8192

    mcp_result = await db.execute(
        select(MCPServerConfig).where(MCPServerConfig.is_active == True)
    )
    mcp_map = {s.name: s for s in mcp_result.scalars().all()}
    mcp_names = set(mcp_map.keys())

    ssh_result = await db.execute(
        select(ServerConfig).where(ServerConfig.is_active == True)
    )
    ssh_names = {s.name for s in ssh_result.scalars().all()}

    # AWS read-only operation prefixes
    _AWS_READONLY_PREFIXES = ("describe_", "list_", "get_", "batch_get", "query", "scan", "search")

    valid: list[dict] = []
    for call in tool_calls:
        call_type = call.get("type", "").lower()
        server_name = call.get("server_name", "")

        # Validate SQL-like types (oracle, postgres, mysql)
        if call_type in ("sql", "postgres", "mysql"):
            if server_name not in mcp_names:
                logger.warning("Plan validation: MCP server '%s' not found — removing %s call", server_name, call_type)
                continue
            query = call.get("query", "")
            if len(query) > _MAX_CMD_LEN:
                logger.warning("Plan validation: SQL query too long (%d chars) — removing", len(query))
                continue
            safety = is_sql_safe(query)
            if safety.get("risk") in ("High", "Critical") and not safety.get("allowed"):
                logger.warning("Plan validation: unsafe SQL rejected — %s", safety.get("reason"))
                continue

        elif call_type == "ssh":
            if server_name not in ssh_names:
                logger.warning("Plan validation: SSH server '%s' not found — removing SSH call", server_name)
                continue
            command = call.get("command", "")
            if len(command) > _MAX_CMD_LEN:
                logger.warning("Plan validation: command too long (%d chars) — removing", len(command))
                continue
            safety = is_shell_command_safe(command)
            if safety.get("risk") == "Critical":
                logger.warning("Plan validation: critical command rejected — %s", safety.get("reason"))
                continue

        elif call_type == "aws":
            if server_name not in mcp_names:
                logger.warning("Plan validation: AWS server '%s' not found — removing", server_name)
                continue
            operation = call.get("operation", "").lower()
            if not any(operation.startswith(p) for p in _AWS_READONLY_PREFIXES):
                logger.warning("Plan validation: non-read-only AWS operation '%s' rejected", operation)
                continue

        elif call_type == "kubernetes":
            if server_name not in mcp_names:
                logger.warning("Plan validation: K8s server '%s' not found — removing", server_name)
                continue
            verb = call.get("verb", "").lower()
            if verb not in ("get", "describe", "logs", "top"):
                logger.warning("Plan validation: non-read-only kubectl verb '%s' rejected", verb)
                continue

        else:
            logger.warning("Plan validation: unknown tool type '%s' — removing", call_type)
            continue

        valid.append(call)

    if len(valid) < len(tool_calls):
        logger.info(
            "Plan validation: kept %d of %d planned calls",
            len(valid), len(tool_calls),
        )

    return valid


async def _execute_tool_calls(db: AsyncSession, tool_calls: list[dict]) -> list[dict]:
    """Execute approved tool calls concurrently, with safety gates."""
    from app.services.safety import is_sql_safe, is_shell_command_safe
    from app.services.mcp_service import fetch_oracle_data
    from app.services.ssh_service import run_ssh_command
    from app.services.tool_registry import _postgres_query_tool, _aws_exec_tool, _k8s_exec_tool

    # Preload server configs
    mcp_result = await db.execute(
        select(MCPServerConfig).where(MCPServerConfig.is_active == True)
    )
    mcp_map = {s.name: s for s in mcp_result.scalars().all()}

    ssh_result = await db.execute(
        select(ServerConfig).where(ServerConfig.is_active == True)
    )
    ssh_map = {s.name: s for s in ssh_result.scalars().all()}

    async def _run_one(call: dict) -> dict:
        call_type = call.get("type", "").lower()
        server_name = call.get("server_name", "")
        description = call.get("description", "")
        base = {"type": call_type, "server_name": server_name, "description": description}

        try:
            if call_type == "sql":
                query = call.get("query", "")
                if not query:
                    return {**base, "success": False, "error": "No query provided", "query": query}

                safety = is_sql_safe(query)
                if not safety.get("allowed"):
                    return {**base, "success": False, "error": f"Blocked: {safety.get('reason', 'unsafe')}", "query": query}

                config = mcp_map.get(server_name)
                if not config:
                    return {**base, "success": False, "error": f"MCP server '{server_name}' not found", "query": query}

                data = await fetch_oracle_data(config, query)
                return {**base, "success": True, "output": data, "query": query}

            elif call_type == "postgres":
                query = call.get("query", "")
                if not query:
                    return {**base, "success": False, "error": "No query provided", "query": query}

                safety = is_sql_safe(query)
                if not safety.get("allowed"):
                    return {**base, "success": False, "error": f"Blocked: {safety.get('reason', 'unsafe')}", "query": query}

                config = mcp_map.get(server_name)
                if not config:
                    return {**base, "success": False, "error": f"PostgreSQL server '{server_name}' not found", "query": query}

                data = await _postgres_query_tool(str(config.id), query)
                return {**base, "success": data.get("success", False), "output": data.get("data"), "error": data.get("error"), "query": query}

            elif call_type == "mysql":
                from app.services.tool_registry import _mysql_query_tool
                query = call.get("query", "")
                if not query:
                    return {**base, "success": False, "error": "No query provided", "query": query}

                safety = is_sql_safe(query)
                if not safety.get("allowed"):
                    return {**base, "success": False, "error": f"Blocked: {safety.get('reason', 'unsafe')}", "query": query}

                config = mcp_map.get(server_name)
                if not config:
                    return {**base, "success": False, "error": f"MySQL server '{server_name}' not found", "query": query}

                data = await _mysql_query_tool(str(config.id), query)
                return {**base, "success": data.get("success", False), "output": data.get("data"), "error": data.get("error"), "query": query}

            elif call_type == "ssh":
                command = call.get("command", "")
                if not command:
                    return {**base, "success": False, "error": "No command provided", "command": command}

                safety = is_shell_command_safe(command)
                if not safety.get("allowed"):
                    return {**base, "success": False, "error": f"Blocked: {safety.get('reason', 'unsafe')}", "command": command}

                config = ssh_map.get(server_name)
                if not config:
                    return {**base, "success": False, "error": f"SSH server '{server_name}' not found", "command": command}

                data = await run_ssh_command(config, command, use_sudo=False, timeout=15)
                return {**base, "success": data.get("success", False), "output": data.get("output", ""), "error": data.get("error"), "command": command}

            elif call_type == "aws":
                config = mcp_map.get(server_name)
                if not config:
                    return {**base, "success": False, "error": f"AWS server '{server_name}' not found"}

                service = call.get("service", "")
                operation = call.get("operation", "")
                params = call.get("params") or {}
                if not service or not operation:
                    return {**base, "success": False, "error": "AWS call requires 'service' and 'operation'"}

                data = await _aws_exec_tool(str(config.id), service=service, operation=operation, params=params)
                return {**base, "success": data.get("success", False), "output": data.get("data"), "error": data.get("error")}

            elif call_type == "kubernetes":
                config = mcp_map.get(server_name)
                if not config:
                    return {**base, "success": False, "error": f"Kubernetes server '{server_name}' not found"}

                verb = call.get("verb", "get")
                resource = call.get("resource", "pods")
                namespace = call.get("namespace") or None
                extra_args = call.get("extra_args") or []

                data = await _k8s_exec_tool(str(config.id), verb=verb, resource=resource, namespace=namespace, extra_args=extra_args)
                return {**base, "success": data.get("success", False), "output": data.get("data"), "error": data.get("error")}

            else:
                return {**base, "success": False, "error": f"Unknown tool type: {call_type}"}
        except Exception as e:
            logger.exception("Tool call failed: %s on %s", call_type, server_name)
            return {**base, "success": False, "error": str(e)}

    results = await asyncio.gather(*[_run_one(c) for c in tool_calls[:_MAX_TOOL_CALLS]])
    return list(results)


def _format_tool_results(results: list[dict]) -> str:
    """Format tool execution results into a text block for AI synthesis."""
    parts = []
    for i, r in enumerate(results, 1):
        header = f"=== [{i}] {r['type'].upper()} on {r['server_name']} ==="
        parts.append(header)
        parts.append(f"Description: {r.get('description', 'N/A')}")
        if r["type"] == "sql":
            parts.append(f"Query: {r.get('query', 'N/A')}")
        elif r["type"] == "ssh":
            parts.append(f"Command: {r.get('command', 'N/A')}")

        if r.get("success"):
            output = r.get("output", "")
            if isinstance(output, dict):
                output = json.dumps(output, indent=2, default=str)
            parts.append(f"Result:\n{output}")
        else:
            parts.append(f"FAILED: {r.get('error', 'Unknown error')}")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# AI provider call (text response)
# ---------------------------------------------------------------------------

async def _call_chat_ai(config, prompt: str, system_prompt: str) -> str:
    """Call AI provider for a chat-style response (returns text, not JSON)."""
    provider = config.provider.lower()

    if provider == "openai":
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url or None)
        response = await client.chat.completions.create(
            model=config.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=config.max_tokens,
            temperature=0.4,
        )
        return response.choices[0].message.content

    elif provider == "anthropic":
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=config.api_key)
        response = await client.messages.create(
            model=config.model_name,
            max_tokens=config.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    elif provider == "google":
        import google.generativeai as genai
        genai.configure(api_key=config.api_key)
        model = genai.GenerativeModel(config.model_name)
        response = await model.generate_content_async(
            f"{system_prompt}\n\n{prompt}",
            generation_config=genai.GenerationConfig(
                max_output_tokens=config.max_tokens,
                temperature=0.4,
            ),
        )
        return response.text

    else:
        raise ValueError(f"Unsupported provider: {provider}")


async def _chat_with_foundry(
    db: AsyncSession,
    history: list[ChatMessage],
    context_parts: list[str],
    *,
    approve_tool_plan: bool = False,
    tool_plan_id: str | None = None,
    session_id=None,
    auto_investigate: bool = False,
) -> tuple[str, dict]:
    """Send chat through Azure AI Foundry agent with function calling support.

    Two-phase flow:
      1. User asks a question → Azure agent plans tool calls → show approval card
      2. User approves → execute tools → send results back → Azure synthesizes answer
    """
    try:
        from app.services.azure_foundry_service import run_agent
        from app.models.foundry_config import FoundryAgentConfig
        from app.services.chat_tool_registry import build_chat_tools, execute_chat_tool_call

        # Build messages first (needed for both named agent and direct completion paths)
        messages = [{"role": "system", "content": _CHAT_SYSTEM_PROMPT}]
        if context_parts:
            messages.append({"role": "user", "content": "\n".join(context_parts)})
        for msg in history:
            messages.append({"role": msg.role, "content": redact_text(msg.content)})

        # Build available tools
        tools = await build_chat_tools(db)

        # Planning messages — exclude RAG/knowledge-base context when live tools are
        # available. RAG docs (runbooks, wikis, audit logs) contain stale cluster/
        # resource names that cause the model to answer live questions from documents
        # instead of calling tools. Alert context (starts with "[Context:") is still
        # useful so we keep that part.
        if tools:
            alert_ctx = [c for c in context_parts if c.startswith("[Context:")]
            planning_messages = [{"role": "system", "content": _CHAT_SYSTEM_PROMPT}]
            if alert_ctx:
                planning_messages.append({"role": "user", "content": "\n".join(alert_ctx)})
            for msg in history:
                planning_messages.append({"role": msg.role, "content": redact_text(msg.content)})
        else:
            # No live tools — include full context (RAG answers knowledge questions)
            planning_messages = messages

        # Find the chat agent
        result = await db.execute(
            select(FoundryAgentConfig).where(
                FoundryAgentConfig.role == "chat",
                FoundryAgentConfig.is_active == True,
            )
        )
        chat_agent = result.scalar_one_or_none()

        # ── Branch B: User approved a pending tool plan ──
        if approve_tool_plan and tool_plan_id and session_id:
            if chat_agent and chat_agent.foundry_agent_name:
                return await _execute_approved_plan_foundry(
                    db, chat_agent, history, context_parts, tool_plan_id, session_id,
                )
            else:
                # Direct completion mode — execute tools then synthesize via Azure
                return await _execute_approved_plan_direct_foundry(
                    db, history, context_parts, tool_plan_id, session_id,
                )

        # If no chat agent configured, fall back to direct Azure AI Foundry chat completion
        # (still uses Azure Foundry endpoint, just without a named agent)
        if not chat_agent or not chat_agent.foundry_agent_name:
            logger.info("No chat agent found in foundry_agent_configs — using direct Azure AI Foundry completion")
            from app.services.azure_foundry_service import _run_chat_completion_with_tools

            response = await _run_chat_completion_with_tools(
                planning_messages,
                tools=tools if tools else None,
                timeout=120.0,
            )

            base_meta = {
                "provider": "azure_foundry",
                "agent": "direct",
                "agent_name": "direct-completion",
            }

            # Handle text response (no tools needed)
            if isinstance(response, str):
                return response, base_meta

            if isinstance(response, dict) and response.get("type") == "message":
                return response.get("content", ""), base_meta

            # Handle tool calls response
            if isinstance(response, dict) and response.get("type") == "tool_calls":
                tool_calls_raw = response.get("tool_calls", [])[:_MAX_TOOL_CALLS]

                # Validate tool calls
                validated = await _validate_foundry_tool_plan(db, tool_calls_raw)
                if not validated:
                    logger.info("All Foundry tool calls failed validation — falling back to chat")
                    response_text = await _run_chat_completion_with_tools(messages, tools=None, timeout=120.0)
                    if isinstance(response_text, dict):
                        response_text = response_text.get("content", str(response_text))
                    return response_text, base_meta

                explanation = (
                    "I need to run some diagnostics to answer your question. "
                    f"Planned {len(validated)} tool call(s)."
                )

                # Auto-investigate: execute immediately without user approval
                if auto_investigate:
                    return await _auto_execute_and_synthesize(db, validated, history, base_meta)

                plan_id = str(_uuid.uuid4())
                tool_plan = {
                    "id": plan_id,
                    "explanation": explanation,
                    "calls": validated,
                    "status": "pending",
                }

                meta = {**base_meta, "tool_plan": tool_plan}
                return explanation, meta

            # Unknown response type
            logger.warning("Unexpected Foundry response type: %s", type(response))
            return str(response), base_meta

        # ── Branch A: Normal message → plan tools if needed (chat_agent exists) ──
        # Call Azure with tools (use planning_messages to avoid stale RAG context)
        response = await run_agent(
            chat_agent.foundry_agent_name,
            planning_messages,
            tools=tools if tools else None,
        )

        base_meta = {
            "provider": "azure_foundry",
            "agent": chat_agent.agent_name,
            "agent_name": chat_agent.foundry_agent_name,
        }

        # Handle text response (no tools needed)
        if isinstance(response, str):
            return response, base_meta

        if isinstance(response, dict) and response.get("type") == "message":
            return response.get("content", ""), base_meta

        # Handle tool calls response
        if isinstance(response, dict) and response.get("type") == "tool_calls":
            tool_calls_raw = response.get("tool_calls", [])[:_MAX_TOOL_CALLS]

            # Validate tool calls
            validated = await _validate_foundry_tool_plan(db, tool_calls_raw)
            if not validated:
                # All calls invalid → fall back to plain chat
                logger.info("All Foundry tool calls failed validation — falling back to chat")
                response_text = await run_agent(
                    chat_agent.foundry_agent_name, messages, tools=None,
                )
                if isinstance(response_text, dict):
                    response_text = response_text.get("content", str(response_text))
                return response_text, base_meta

            explanation = (
                "I need to run some diagnostics to answer your question. "
                f"Planned {len(validated)} tool call(s)."
            )

            # Auto-investigate: execute immediately without user approval
            if auto_investigate:
                return await _auto_execute_and_synthesize(db, validated, history, base_meta)

            plan_id = str(_uuid.uuid4())
            tool_plan = {
                "id": plan_id,
                "explanation": explanation,
                "calls": validated,
                "status": "pending",
            }

            meta = {**base_meta, "tool_plan": tool_plan}
            return explanation, meta

        # Unknown response type
        logger.warning("Unexpected Foundry response type: %s", type(response))
        return str(response), base_meta

    except ImportError:
        return "Azure AI Foundry SDK is not installed. Install azure-ai-projects package.", {}
    except Exception as e:
        logger.exception("Foundry chat failed: %s", e)
        return f"Azure AI Foundry error: {str(e)}", {"error": str(e)}


async def _validate_foundry_tool_plan(db: AsyncSession, tool_calls: list[dict]) -> list[dict]:
    """Validate AI-planned tool calls before presenting to the user.

    Reuses the same safety checks as the builtin mode but adapted for
    Azure function calling format.
    """
    from app.services.safety import is_sql_safe, is_shell_command_safe

    _MAX_CMD_LEN = 8192

    # Preload server configs
    mcp_result = await db.execute(
        select(MCPServerConfig).where(MCPServerConfig.is_active == True)
    )
    mcp_names = {m.name for m in mcp_result.scalars().all()}

    ssh_result = await db.execute(
        select(ServerConfig).where(ServerConfig.is_active == True)
    )
    ssh_names = {s.name for s in ssh_result.scalars().all()}

    valid: list[dict] = []
    for call in tool_calls:
        name = call.get("name", "")
        args = call.get("arguments", {})

        # Map tool name back to server and validate
        server_found = False
        call_type = "unknown"
        command_or_query = ""

        if name.startswith("query_oracle_"):
            server_name = name[len("query_oracle_"):]
            server_found = server_name in mcp_names
            call_type = "sql"
            command_or_query = args.get("sql", "")
        elif name.startswith("query_postgres_"):
            server_name = name[len("query_postgres_"):]
            server_found = server_name in mcp_names
            call_type = "sql"
            command_or_query = args.get("sql", "")
        elif name.startswith("query_mysql_"):
            server_name = name[len("query_mysql_"):]
            server_found = server_name in mcp_names
            call_type = "sql"
            command_or_query = args.get("sql", "")
        elif name.startswith("call_aws_"):
            server_name = name[len("call_aws_"):]
            server_found = server_name in mcp_names
            call_type = "aws"
        elif name.startswith("call_azure_"):
            server_name = name[len("call_azure_"):]
            server_found = server_name in mcp_names
            call_type = "azure"
        elif name.startswith("call_k8s_"):
            server_name = name[len("call_k8s_"):]
            server_found = server_name in mcp_names
            call_type = "k8s"
        elif name.startswith("query_mongodb_"):
            server_name = name[len("query_mongodb_"):]
            server_found = server_name in mcp_names
            call_type = "mongodb"
        elif name.startswith("run_ssh_"):
            server_name = name[len("run_ssh_"):]
            server_found = server_name in ssh_names
            call_type = "ssh"
            command_or_query = args.get("command", "")
        else:
            logger.warning("Foundry plan validation: unknown tool '%s' — removing", name)
            continue

        if not server_found:
            logger.warning("Foundry plan validation: server '%s' not found — removing", server_name)
            continue

        # Safety checks
        if call_type == "sql":
            if len(command_or_query) > _MAX_CMD_LEN:
                logger.warning("Foundry plan validation: SQL too long (%d chars) — removing", len(command_or_query))
                continue
            safety = is_sql_safe(command_or_query)
            if safety.get("risk") in ("High", "Critical") and not safety.get("allowed"):
                logger.warning("Foundry plan validation: unsafe SQL rejected — %s", safety.get("reason"))
                continue
        elif call_type == "ssh":
            if len(command_or_query) > _MAX_CMD_LEN:
                logger.warning("Foundry plan validation: command too long (%d chars) — removing", len(command_or_query))
                continue
            safety = is_shell_command_safe(command_or_query)
            if safety.get("risk") == "Critical":
                logger.warning("Foundry plan validation: critical command rejected — %s", safety.get("reason"))
                continue

        # Build validated call in the format the frontend expects
        validated_call = {
            "type": call_type,
            "server_name": server_name,
            "description": f"{name}({', '.join(f'{k}={v}' for k, v in args.items())})"[:200],
        }

        if call_type == "sql":
            validated_call["query"] = command_or_query
        elif call_type == "ssh":
            validated_call["command"] = command_or_query
        elif call_type in ("aws", "azure"):
            validated_call["service"] = args.get("service", "")
            validated_call["operation"] = args.get("operation", "")
            validated_call["params"] = args.get("params", {})
        elif call_type == "k8s":
            validated_call["verb"] = args.get("verb", "")
            validated_call["resource"] = args.get("resource", "")
            validated_call["namespace"] = args.get("namespace", "")
            validated_call["extra_args"] = args.get("extra_args", [])
        elif call_type == "mongodb":
            validated_call["command"] = args.get("command", "")

        # Store original function call info for execution
        validated_call["_function_name"] = name
        validated_call["_arguments"] = args

        valid.append(validated_call)

    if len(valid) < len(tool_calls):
        logger.info("Foundry plan validation: kept %d of %d planned calls", len(valid), len(tool_calls))

    return valid


async def _execute_approved_plan_direct_foundry(
    db: AsyncSession,
    history: list[ChatMessage],
    context_parts: list[str],
    tool_plan_id: str,
    session_id,
) -> tuple[str, dict]:
    """Execute an approved tool plan in direct Azure completion mode (no named agent)."""
    from app.services.chat_tool_registry import execute_chat_tool_call
    from app.services.azure_foundry_service import _run_chat_completion_with_tools

    base_meta = {"provider": "azure_foundry", "agent": "direct", "agent_name": "direct-completion"}

    # Find the assistant message that holds the plan
    plan_result = await db.execute(
        select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "assistant",
        ).order_by(ChatMessage.created_at.desc()).limit(10)
    )
    plan_msg: ChatMessage | None = None
    for msg in plan_result.scalars().all():
        meta = msg.metadata_json or {}
        tp = meta.get("tool_plan") or {}
        if tp.get("id") == tool_plan_id:
            plan_msg = msg
            break

    if not plan_msg:
        return "Could not find the tool plan to execute. Please try asking your question again.", base_meta

    tool_plan = plan_msg.metadata_json.get("tool_plan", {})
    tool_calls = tool_plan.get("calls", [])
    if not tool_calls:
        return "The tool plan has no diagnostics to run.", base_meta

    # Execute all approved tool calls
    results = []
    for call in tool_calls:
        function_call = {
            "name": call.get("_function_name", ""),
            "arguments": call.get("_arguments", {}),
        }
        result = await execute_chat_tool_call(db, function_call)
        results.append({
            "type": call.get("type", "unknown"),
            "server_name": call.get("server_name", ""),
            "description": call.get("description", ""),
            "success": result.get("success", False),
            "output": result.get("output"),
            "error": result.get("error"),
        })

    # Get original user question
    user_question = ""
    for msg in reversed(history):
        if msg.role == "user" and msg.content != "(approved tool execution)":
            user_question = msg.content
            break

    results_text = _format_foundry_tool_results(results)
    synthesis_prompt = (
        f"The user asked: {user_question}\n\n"
        f"Live diagnostic results:\n{results_text}\n\n"
        f"Synthesize a clear, actionable answer based on the actual data above. "
        f"Quote specific numbers and values. If any tool failed, note it but analyze what is available."
    )

    messages = [
        {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
        {"role": "user", "content": synthesis_prompt},
    ]

    try:
        synthesis_response = await _run_chat_completion_with_tools(messages, tools=None, timeout=120.0)
        if isinstance(synthesis_response, dict):
            answer = synthesis_response.get("content") or synthesis_response.get("text") or str(synthesis_response)
        else:
            answer = str(synthesis_response) if synthesis_response else results_text
        if not answer or not answer.strip():
            answer = f"Here are the live diagnostic results:\n\n{results_text}"
    except Exception as e:
        logger.exception("Direct Foundry synthesis failed: %s", e)
        answer = f"I collected the diagnostic data but had trouble synthesizing it.\n\n{results_text}"

    answer, follow_ups = _extract_follow_ups(answer)
    tools_executed = [
        {
            "type": r["type"],
            "server_name": r["server_name"],
            "success": r["success"],
            "description": r.get("description", ""),
            "output": _normalize_tool_output(r.get("output")),
            "query": r.get("query"),
            "command": r.get("command"),
            "error": r.get("error"),
        }
        for r in results
    ]

    meta = {**base_meta, "tools_executed": tools_executed, "tool_plan_id": tool_plan_id, "suggested_follow_ups": follow_ups}
    return answer, meta


async def _execute_approved_plan_foundry(
    db: AsyncSession,
    chat_agent,
    history: list[ChatMessage],
    context_parts: list[str],
    tool_plan_id: str,
    session_id,
) -> tuple[str, dict]:
    """Execute a user-approved tool plan from Azure Foundry and synthesize results."""
    from app.services.chat_tool_registry import execute_chat_tool_call
    from app.services.azure_foundry_service import run_agent

    # Find the assistant message that holds the plan
    plan_result = await db.execute(
        select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "assistant",
        ).order_by(ChatMessage.created_at.desc()).limit(10)
    )
    plan_msg: ChatMessage | None = None
    for msg in plan_result.scalars().all():
        meta = msg.metadata_json or {}
        tp = meta.get("tool_plan") or {}
        if tp.get("id") == tool_plan_id:
            plan_msg = msg
            break

    if not plan_msg:
        return "Could not find the tool plan to execute. Please try asking your question again.", {}

    tool_plan = plan_msg.metadata_json.get("tool_plan", {})
    tool_calls = tool_plan.get("calls", [])
    if not tool_calls:
        return "The tool plan has no diagnostics to run.", {}

    # Execute the approved tool calls
    results = []
    for call in tool_calls:
        function_call = {
            "name": call.get("_function_name", ""),
            "arguments": call.get("_arguments", {}),
        }
        result = await execute_chat_tool_call(db, function_call)
        results.append({
            "type": call.get("type", "unknown"),
            "server_name": call.get("server_name", ""),
            "description": call.get("description", ""),
            "success": result.get("success", False),
            "output": result.get("output"),
            "error": result.get("error"),
        })

    # Build synthesis prompt with tool results
    user_question = ""
    for msg in reversed(history):
        if msg.role == "user" and msg.content != "(approved tool execution)":
            user_question = msg.content
            break

    # Build messages for synthesis
    messages = [{"role": "system", "content": _CHAT_SYSTEM_PROMPT}]
    if context_parts:
        messages.append({"role": "user", "content": "\n".join(context_parts)})

    # Add history
    for msg in history:
        messages.append({"role": msg.role, "content": redact_text(msg.content)})

    # Add tool results as a system message
    results_text = _format_foundry_tool_results(results)
    synthesis_prompt = (
        f"The user asked: {user_question}\n\n"
        f"I ran the following diagnostics and got these results:\n\n"
        f"{results_text}\n\n"
        f"Please synthesize a clear, actionable answer based on the actual data above. "
        f"Quote specific numbers and values. If any tool failed, note it but analyze what we have.\n\n"
        f"After your answer, add 3 short follow-up investigation questions in this format:\n"
        f"<suggestions>\n[question 1]\n[question 2]\n[question 3]\n</suggestions>"
    )
    messages.append({"role": "user", "content": synthesis_prompt})

    # Call Azure for synthesis
    synthesis_response = await run_agent(chat_agent.foundry_agent_name, messages, tools=None)
    if isinstance(synthesis_response, dict):
        answer = synthesis_response.get("content", str(synthesis_response))
    else:
        answer = synthesis_response

    answer, follow_ups = _extract_follow_ups(answer)
    tools_executed = []
    for r in results:
        tools_executed.append({
            "type": r["type"],
            "server_name": r["server_name"],
            "success": r["success"],
            "description": r.get("description", ""),
            "output": _normalize_tool_output(r.get("output")),
            "query": r.get("query"),
            "command": r.get("command"),
            "error": r.get("error"),
        })

    meta = {
        "provider": "azure_foundry",
        "agent": chat_agent.agent_name,
        "agent_name": chat_agent.foundry_agent_name,
        "tools_executed": tools_executed,
        "tool_plan_id": tool_plan_id,
        "suggested_follow_ups": follow_ups,
    }
    return answer, meta


def _format_foundry_tool_results(results: list[dict]) -> str:
    """Format tool execution results into a text block for AI synthesis."""
    import json
    parts = []
    for i, r in enumerate(results, 1):
        header = f"=== [{i}] {r['type'].upper()} on {r['server_name']} ==="
        parts.append(header)
        parts.append(f"Description: {r.get('description', 'N/A')}")

        if r.get("success"):
            output = r.get("output", "")
            # Handle boto3 response, DB result dicts, MCPToolCallResponse objects, etc.
            if hasattr(output, "__dict__"):
                output = vars(output)
            if isinstance(output, (dict, list)):
                try:
                    output = json.dumps(output, indent=2, default=str)
                except Exception:
                    output = str(output)
            elif output is None:
                output = "(no data returned)"
            parts.append(f"Result:\n{output}")
        else:
            parts.append(f"FAILED: {r.get('error', 'Unknown error')}")
        parts.append("")

    return "\n".join(parts)


def _normalize_tool_output(output) -> dict | None:
    """Normalize tool output for frontend display. Caps table rows to 50."""
    import json as _json
    if output is None:
        return None
    # Unwrap objects with __dict__
    if hasattr(output, "__dict__"):
        output = vars(output)
    # Dict with columns+rows → table
    if isinstance(output, dict) and "columns" in output and "rows" in output:
        rows = output.get("rows") or []
        total = len(rows)
        return {
            "type": "table",
            "columns": output["columns"],
            "rows": rows[:50],
            "row_count": total,
            "truncated": total > 50,
        }
    # Generic dict/list → json
    if isinstance(output, (dict, list)):
        try:
            _json.dumps(output, default=str)
            return {"type": "json", "data": output}
        except Exception:
            return {"type": "text", "content": str(output)[:5000]}
    # String → text
    if isinstance(output, str):
        return {"type": "text", "content": output[:5000], "truncated": len(output) > 5000}
    return {"type": "text", "content": str(output)[:5000]}


def _extract_follow_ups(answer: str) -> tuple[str, list[str]]:
    """Extract <suggestions>…</suggestions> block from AI answer."""
    import re
    match = re.search(r"<suggestions>(.*?)</suggestions>", answer, re.DOTALL)
    if not match:
        return answer, []
    raw = match.group(1).strip().split("\n")
    suggestions = [s.strip().lstrip("0123456789.-) ").strip() for s in raw if s.strip()][:3]
    return answer[: match.start()].rstrip(), suggestions


async def _auto_execute_and_synthesize(
    db: AsyncSession,
    validated: list[dict],
    history: list[ChatMessage],
    base_meta: dict,
) -> tuple[str, dict]:
    """Execute validated tool calls immediately (no user approval) and synthesize — auto-investigate."""
    from app.services.chat_tool_registry import execute_chat_tool_call
    from app.services.azure_foundry_service import _run_chat_completion_with_tools

    results = []
    for call in validated:
        function_call = {
            "name": call.get("_function_name", ""),
            "arguments": call.get("_arguments", {}),
        }
        result = await execute_chat_tool_call(db, function_call)
        results.append({
            "type": call.get("type", "unknown"),
            "server_name": call.get("server_name", ""),
            "description": call.get("description", ""),
            "success": result.get("success", False),
            "output": result.get("output"),
            "error": result.get("error"),
            "query": call.get("query"),
            "command": call.get("command"),
        })

    user_question = next(
        (msg.content for msg in reversed(history) if msg.role == "user"),
        "Investigate this alert",
    )
    results_text = _format_foundry_tool_results(results)
    synth_messages = [
        {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Question: {user_question}\n\nLive diagnostic results:\n{results_text}\n\n"
                "Synthesize a clear, actionable answer. Quote specific numbers and values."
            ),
        },
    ]
    try:
        synthesis_response = await _run_chat_completion_with_tools(synth_messages, tools=None, timeout=120.0)
        if isinstance(synthesis_response, dict):
            answer = synthesis_response.get("content") or str(synthesis_response)
        else:
            answer = str(synthesis_response) if synthesis_response else results_text
    except Exception as exc:
        logger.exception("Auto-investigate synthesis failed: %s", exc)
        answer = f"Diagnostic data collected:\n\n{results_text}"

    tools_executed = [
        {
            "type": r["type"],
            "server_name": r["server_name"],
            "success": r["success"],
            "description": r.get("description", ""),
            "output": _normalize_tool_output(r.get("output")),
            "query": r.get("query"),
            "command": r.get("command"),
            "error": r.get("error"),
        }
        for r in results
    ]
    answer, follow_ups = _extract_follow_ups(answer)
    return answer, {**base_meta, "tools_executed": tools_executed, "suggested_follow_ups": follow_ups}
