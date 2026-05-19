"""Alert analysis orchestrator — ties AI, MCP, and email together."""
import asyncio
import json
import logging
import re
from datetime import datetime, date, timezone
from sqlalchemy import select

from app.database import async_session
from app.models.alert import Alert, AlertAnalysis
from app.models.ai_config import AIProviderConfig
from app.models.app_settings import AppSetting
from app.models.mcp_config import MCPServerConfig
from app.models.server_config import ServerConfig
from app.models.agent_profile import AgentProfile
from app.services.ai_service import analyze_with_ai, generate_raw_json
from app.services.mcp_service import fetch_oracle_data
from app.services.ssh_service import run_ssh_command
from app.services.email_service import send_action_plan_email
from app.services.pii_redactor import redact_text, redact_dict
from app.services.master_agent import select_agent_profile
from app.services.jira_knowledge_agent import gather_jira_context
from app.config import settings

logger = logging.getLogger(__name__)


def _make_json_serializable(obj):
    """Recursively convert non-JSON-serializable types (datetime, date, bytes, etc.)
    to JSON-safe equivalents. Falls back to str() for unknown types.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(i) for i in obj]
    if isinstance(obj, dict):
        return {str(k): _make_json_serializable(v) for k, v in obj.items()}
    try:
        json.dumps(obj)  # already serializable
        return obj
    except Exception:
        return str(obj)


def _normalize_text_field(val) -> str | None:
    """Ensure a field that must be a plain string actually is one.

    The AI occasionally returns fields like ``prevention_steps`` or
    ``root_cause`` as a dict (e.g. ``{'steps': [...]}`` or
    ``{'text': '...'}``), or as a list of strings, causing
    asyncpg DataError when writing to a VARCHAR column.  This helper
    coerces any such value to a plain string so the INSERT always works.
    """
    if val is None:
        return None
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        # Common AI mis-shapes: {'steps': [...]} or {'text': '...'} or {'prevention': '...'}
        for key in ("text", "steps", "prevention", "prevention_steps", "content", "summary"):
            if key in val:
                inner = val[key]
                if isinstance(inner, list):
                    return "\n".join(str(item) for item in inner)
                return str(inner)
        # Fallback: dump the whole dict as readable text
        return json.dumps(val)
    if isinstance(val, list):
        return "\n".join(str(item) for item in val)
    return str(val)


# Max queries the AI is allowed to generate per alert
_MAX_GENERATED_QUERIES = 8


async def analyze_alert_background(alert_id: str, analyst_hint: str | None = None):
    """Background task: analyze an alert using Azure AI Foundry agents (always)."""
    # ── Always route through Azure AI Foundry multi-agent pipeline ──
    from app.services.foundry_analyzer import analyze_alert_with_foundry
    return await analyze_alert_with_foundry(alert_id, analyst_hint)

    async with async_session() as db:
        try:
            result = await db.execute(select(Alert).where(Alert.id == alert_id))
            alert = result.scalar_one_or_none()
            if not alert:
                logger.error("Alert %s not found for analysis", alert_id)
                return

            # If alert is already marked resolved/cleared, record a resolved analysis with evidence
            if (alert.status or "").lower() == "resolved":
                evidence = {
                    "annotations": alert.annotations or {},
                    "labels": alert.labels or {},
                    "raw_payload": alert.raw_payload or {},
                }
                # Upsert analysis record for resolved alert
                now = datetime.now(timezone.utc)
                existing = alert.analysis
                if existing:
                    existing.root_cause = "Alert marked as resolved/cleared"
                    existing.confidence_score = 1.0
                    existing.action_plan = []
                    existing.fix_commands = []
                    existing.prevention_steps = None
                    existing.risk_level = "info"
                    existing.ai_provider_used = None
                    existing.ai_model_used = None
                    existing.tools_called = []
                    existing.logs_collected = evidence
                    existing.full_ai_response = {"resolved": True, "evidence": evidence}
                    existing.analyzed_at = now
                else:
                    analysis = AlertAnalysis(
                        alert_id=alert.id,
                        root_cause="Alert marked as resolved/cleared",
                        confidence_score=1.0,
                        action_plan=[],
                        fix_commands=[],
                        prevention_steps=None,
                        risk_level="info",
                        ai_provider_used=None,
                        ai_model_used=None,
                        tools_called=[],
                        logs_collected=evidence,
                        full_ai_response={"resolved": True, "evidence": evidence},
                    )
                    db.add(analysis)
                # Update alert-level tracking
                alert.analysis_status = "analyzed"
                alert.analysis_count = (alert.analysis_count or 0) + 1
                alert.last_analyzed_at = now
                await db.commit()
                try:
                    await send_action_plan_email(
                        to_email=settings.ADMIN_EMAIL,
                        alert_name=alert.alertname,
                        alert_id=str(alert.id),
                        analysis={"resolved": True, "evidence": evidence},
                    )
                except Exception as e:
                    logger.warning("Email notification failed for resolved alert %s: %s", alert_id, e)
                return

            alert.analysis_status = "analyzing"
            await db.commit()

            # ── Resolve AI provider early (needed for both phases) ──
            ai_config = await _get_ai_provider(db)
            if not ai_config:
                logger.error("No active AI provider configured — cannot analyze alert %s", alert_id)
                alert.analysis_status = "failed"
                await db.commit()
                return

            # ── Select best-matching agent profile ──
            agent_profile = await select_agent_profile(db, alert)
            agent_system_prompt = agent_profile.system_prompt if agent_profile else None
            agent_name = agent_profile.display_name if agent_profile else "General (fallback)"
            logger.info("Alert %s matched agent: %s", alert_id, agent_name)

            # ── Phase 1: AI-generated diagnostic queries ──
            collected_logs = {}
            tools_called = []
            mcp_connected = False
            os_collected = False

            agent_type = (agent_profile.agent_type if agent_profile else "general") or "general"

            # Load both server types up-front for cross-domain capability
            srv_result = await db.execute(
                select(ServerConfig).where(ServerConfig.is_active == True)
            )
            all_servers = srv_result.scalars().all()

            mcp_result = await db.execute(
                select(MCPServerConfig).where(MCPServerConfig.is_active == True)
            )
            active_mcp_servers = mcp_result.scalars().all()

            # ── Primary pipeline based on agent_type ──
            matched_mcps: list[MCPServerConfig] = []
            matched_ssh_host: str | None = None   # track for cross-domain

            if agent_type == "os":
                # Primary: OS diagnostics via SSH
                matched_ssh, _ssh_reason = _match_ssh_server(all_servers, alert)
                if matched_ssh:
                    matched_ssh_host = matched_ssh.host
                ssh_data, ssh_tools = await _collect_os_diagnostics(all_servers, alert)
                collected_logs.update(ssh_data)
                tools_called.extend(ssh_tools)
                os_collected = bool(ssh_data)
            else:
                # Primary: Database diagnostics via MCP SQL
                matched_mcps = _match_mcp_servers(active_mcp_servers, alert, agent_profile)

                if matched_mcps:
                    try:
                        generated_queries = await _ai_generate_diagnostic_queries(
                            ai_config, alert, agent_system_prompt
                        )
                        logger.info(
                            "Alert %s — AI generated %d diagnostic queries",
                            alert_id, len(generated_queries),
                        )
                    except Exception as e:
                        logger.warning("AI query generation failed for %s: %s", alert_id, e)
                        generated_queries = {}

                    # Execute the AI-generated queries via MCP — run all in parallel
                    async def _run_mcp_query(mcp, query_name, sql):
                        try:
                            data = await fetch_oracle_data(mcp, sql)
                            return (f"{mcp.name}_{query_name}", data, {
                                "tool": "execute_sql",
                                "server": mcp.name,
                                "query": query_name,
                                "sql": sql,
                            })
                        except Exception as e:
                            logger.warning("MCP query %s failed on %s: %s", query_name, mcp.name, e)
                            return (f"{mcp.name}_{query_name}_error", str(e), None)

                    tasks = [
                        _run_mcp_query(mcp, qn, sql)
                        for mcp in matched_mcps
                        for qn, sql in generated_queries.items()
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=False)
                    for log_key, data, tool_entry in results:
                        collected_logs[log_key] = data
                        if tool_entry:
                            tools_called.append(tool_entry)
                        if isinstance(data, dict) and data.get("success"):
                            mcp_connected = True

            # ── Cross-domain: secondary diagnostics ──
            # DB/general agents → OS diagnostics on servers co-located with
            # matched MCP databases (host-affinity) or matching the alert instance.
            if agent_type in ("database", "general") and all_servers:
                related_hosts = [m.oracle_host for m in matched_mcps if m.oracle_host]
                ssh_data, ssh_tools = await _collect_os_diagnostics(
                    all_servers, alert, related_hosts=related_hosts,
                )
                if ssh_data:
                    logger.info("Alert %s — cross-domain OS diagnostics collected", alert_id)
                    collected_logs.update(ssh_data)
                    tools_called.extend(ssh_tools)
                    os_collected = True
                else:
                    logger.info(
                        "Alert %s — no matching SSH server for cross-domain OS (instance=%s, related=%s)",
                        alert_id, alert.instance, related_hosts,
                    )

            # OS agents → DB diagnostics on MCP servers co-located with the
            # matched SSH server (host-affinity).
            if agent_type == "os" and active_mcp_servers and matched_ssh_host:
                cross_mcps = _find_cross_domain_mcp_servers(active_mcp_servers, matched_ssh_host)
                if cross_mcps:
                    logger.info(
                        "Alert %s — cross-domain DB diagnostics on %s (via SSH host %s)",
                        alert_id, [m.name for m in cross_mcps], matched_ssh_host,
                    )
                    try:
                        generated_queries = await _ai_generate_diagnostic_queries(
                            ai_config, alert, agent_system_prompt
                        )
                    except Exception as e:
                        logger.warning("Cross-domain SQL generation failed for %s: %s", alert_id, e)
                        generated_queries = {}

                    async def _run_mcp_query_xd(mcp, query_name, sql):
                        try:
                            data = await fetch_oracle_data(mcp, sql)
                            return (f"{mcp.name}_{query_name}", data, {
                                "tool": "execute_sql",
                                "server": mcp.name,
                                "query": query_name,
                                "sql": sql,
                            })
                        except Exception as e:
                            logger.warning("Cross-domain MCP query %s failed on %s: %s", query_name, mcp.name, e)
                            return (f"{mcp.name}_{query_name}_error", str(e), None)

                    xd_tasks = [
                        _run_mcp_query_xd(mcp, qn, sql)
                        for mcp in cross_mcps
                        for qn, sql in generated_queries.items()
                    ]
                    xd_results = await asyncio.gather(*xd_tasks, return_exceptions=False)
                    for log_key, data, tool_entry in xd_results:
                        collected_logs[log_key] = data
                        if tool_entry:
                            tools_called.append(tool_entry)
                        if isinstance(data, dict) and data.get("success"):
                            mcp_connected = True
                else:
                    logger.info(
                        "Alert %s — no co-located MCP server for cross-domain DB (ssh_host=%s)",
                        alert_id, matched_ssh_host,
                    )

            # ── RAG Knowledge Base context (opt-in) ──
            rag_context = ""
            try:
                from app.services.knowledge_retrieval_service import get_context_for_alert
                rag_context = await get_context_for_alert(
                    alert.alertname or "",
                    alert.description or "",
                    db,
                    labels=alert.labels,
                )
                if rag_context:
                    tools_called.append({"tool": "rag_knowledge_search", "chunks_returned": rag_context.count("###")})
                    collected_logs["rag_knowledge_context"] = rag_context
            except Exception as e:
                logger.debug("RAG knowledge search skipped for alert %s: %s", alert_id, e)

            # ── Jira Knowledge Agent: fetch similar issues & KB articles ──
            jira_context = {}
            try:
                jira_context = await gather_jira_context(db, alert)
                if jira_context:
                    logger.info(
                        "Alert %s — Jira context: %d similar issues, %d KB articles",
                        alert_id,
                        len(jira_context.get("jira_similar_issues", [])),
                        len(jira_context.get("jira_kb_articles", [])),
                    )
                    tools_called.append({
                        "tool": "jira_knowledge_search",
                        "issues_found": len(jira_context.get("jira_similar_issues", [])),
                        "kb_articles_found": len(jira_context.get("jira_kb_articles", [])),
                    })
                    # Store raw Jira data in collected_logs for audit
                    collected_logs["jira_similar_issues"] = jira_context.get("jira_similar_issues", [])
                    collected_logs["jira_kb_articles"] = jira_context.get("jira_kb_articles", [])
            except Exception as e:
                logger.warning("Jira knowledge search failed for alert %s: %s", alert_id, e)

            # ── Phase 2: Full analysis with alert + live data ──
            prompt = _build_analysis_prompt(
                alert, collected_logs, mcp_connected,
                analyst_hint=analyst_hint, agent_type=agent_type,
                os_collected=os_collected,
                jira_context=jira_context,
                rag_context=rag_context,
            )

            try:
                ai_response = await analyze_with_ai(ai_config, prompt, system_prompt=agent_system_prompt)
            except Exception as e:
                logger.error("AI analysis failed for alert %s: %s", alert_id, e)
                alert.analysis_status = "failed"
                await db.commit()
                return

            # If the AI returned a structured error (e.g. truncated JSON),
            # retry once with a higher max_tokens allowance.
            if isinstance(ai_response, dict) and ai_response.get("error"):
                logger.warning(
                    "Alert %s — AI returned error (%s), retrying with higher token limit",
                    alert_id, ai_response["error"],
                )
                original_max = ai_config.max_tokens
                try:
                    ai_config.max_tokens = max(original_max or 4096, 16384)
                    ai_response = await analyze_with_ai(ai_config, prompt, system_prompt=agent_system_prompt)
                except Exception as retry_err:
                    logger.error("AI retry also failed for alert %s: %s", alert_id, retry_err)
                finally:
                    ai_config.max_tokens = original_max

                # If still an error after retry, mark failed and bail
                if isinstance(ai_response, dict) and ai_response.get("error"):
                    logger.error(
                        "Alert %s — AI analysis failed after retry: %s",
                        alert_id, ai_response.get("exception", ai_response["error"]),
                    )
                    alert.analysis_status = "failed"
                    await db.commit()
                    return

            # ── Extract fix_commands from AI response ──
            fix_commands = ai_response.get("fix_commands", [])
            # Validate fix_commands structure
            # For OS agents the implicit default type is "os"; for db/general agents "sql"
            default_cmd_type = "os" if agent_type == "os" else "sql"
            validated_fix_cmds = []
            for cmd in fix_commands:
                if isinstance(cmd, dict) and "command" in cmd:
                    validated_fix_cmds.append({
                        "type": cmd.get("type", default_cmd_type),
                        "description": cmd.get("description", ""),
                        "command": cmd["command"],
                        "risk_level": cmd.get("risk_level", "Medium"),
                        "requires_approval": cmd.get("requires_approval", True),
                    })

            # ── Save analysis — ensure JSON columns are fully serializable ──
            now = datetime.now(timezone.utc)
            # Upsert AlertAnalysis for this alert (avoid unique constraint errors)
            existing = alert.analysis
            if existing:
                existing.root_cause = _normalize_text_field(ai_response.get("root_cause"))
                existing.confidence_score = ai_response.get("confidence_score")
                existing.action_plan = _make_json_serializable(ai_response.get("action_plan", []))
                existing.fix_commands = _make_json_serializable(validated_fix_cmds)
                existing.prevention_steps = _normalize_text_field(ai_response.get("prevention_steps"))
                existing.risk_level = _normalize_text_field(ai_response.get("risk_level"))
                existing.ai_provider_used = ai_config.provider
                existing.ai_model_used = ai_config.model_name
                existing.tools_called = _make_json_serializable(tools_called)
                existing.logs_collected = _make_json_serializable(collected_logs)
                existing.full_ai_response = _make_json_serializable(ai_response)
                existing.analyzed_at = now
            else:
                analysis = AlertAnalysis(
                    alert_id=alert.id,
                    root_cause=_normalize_text_field(ai_response.get("root_cause")),
                    confidence_score=ai_response.get("confidence_score"),
                    action_plan=_make_json_serializable(ai_response.get("action_plan", [])),
                    fix_commands=_make_json_serializable(validated_fix_cmds),
                    prevention_steps=_normalize_text_field(ai_response.get("prevention_steps")),
                    risk_level=_normalize_text_field(ai_response.get("risk_level")),
                    ai_provider_used=ai_config.provider,
                    ai_model_used=ai_config.model_name,
                    tools_called=_make_json_serializable(tools_called),
                    logs_collected=_make_json_serializable(collected_logs),
                    full_ai_response=_make_json_serializable(ai_response),
                )
                db.add(analysis)

            alert.analysis_status = "analyzed"
            alert.analysis_count = (alert.analysis_count or 0) + 1
            alert.last_analyzed_at = now
            await db.commit()

            logger.info("Alert %s analyzed successfully (%s)", alert_id, ai_config.provider)

            # ── Email notification ──
            try:
                await send_action_plan_email(
                    to_email=settings.ADMIN_EMAIL,
                    alert_name=alert.alertname,
                    alert_id=str(alert.id),
                    analysis=ai_response,
                )
            except Exception as e:
                logger.warning("Email notification failed for alert %s: %s", alert_id, e)

        except asyncio.CancelledError:
            logger.info("Analysis cancelled for alert %s", alert_id)
            try:
                alert.analysis_status = "cancelled"
                await db.commit()
            except Exception:
                pass
            return
        except Exception as e:
            logger.exception("Unexpected error analyzing alert %s: %s", alert_id, e)
            try:
                alert.analysis_status = "failed"
                await db.commit()
            except Exception:
                pass


def _build_analysis_prompt(alert: Alert, logs: dict, mcp_connected: bool = False, analyst_hint: str | None = None, agent_type: str = "general", os_collected: bool = False, jira_context: dict | None = None, rag_context: str = "") -> str:
    """Build a detailed prompt for AI analysis.

    All user-sourced text (alert fields, labels, log data) is run through the
    PII redactor before being included in the prompt so that personally
    identifiable information and credentials are never sent to the AI model.
    """
    # Redact alert-level text
    safe_alertname   = redact_text(alert.alertname or "")
    safe_summary     = redact_text(alert.summary or "N/A")
    safe_description = redact_text(alert.description or "N/A")
    safe_instance    = redact_text(alert.instance or "N/A")
    safe_source      = redact_text(alert.source or "")
    safe_labels      = redact_dict(alert.labels or {})

    parts = [
        f"# Infrastructure Alert Analysis Request",
        f"",
    ]

    # Analyst hint is injected first so it overrides any AI assumptions
    if analyst_hint and analyst_hint.strip():
        safe_hint = redact_text(analyst_hint.strip())
        parts += [
            f"## ⚠️ Analyst Guidance (HIGHEST PRIORITY — follow this exactly)",
            f"{safe_hint}",
            f"",
            f"> This guidance was provided by a human analyst who has direct knowledge of this",
            f"> incident. It MUST override any assumptions you would otherwise make based solely",
            f"> on the alert name or general patterns. Focus your entire analysis on what is",
            f"> described above.",
            f"",
        ]

    parts += [
        f"## Alert Details",
        f"- **Name**: {safe_alertname}",
        f"- **Severity**: {alert.severity}",
        f"- **Status**: {alert.status}",
        f"- **Instance**: {safe_instance}",
        f"- **Summary**: {safe_summary}",
        f"- **Description**: {safe_description}",
        f"- **Source**: {safe_source}",
        f"",
        f"## Labels",
    ]
    for k, v in safe_labels.items():
        parts.append(f"- {k}: {v}")

    if mcp_connected and logs:
        # Split logs into DB and OS categories
        db_logs = {k: v for k, v in logs.items() if not k.startswith("ssh_")}
        os_logs = {k: v for k, v in logs.items() if k.startswith("ssh_")}

        if db_logs:
            parts.append("")
            parts.append("## Live Database Data (collected via MCP connection)")
            parts.append("The following data was queried in real-time from the database instance associated with this alert. Use it to refine your root cause analysis and action plan.")
            for source, data in db_logs.items():
                safe_data = redact_dict(data) if isinstance(data, dict) else redact_text(str(data))
                parts.append(f"### {source}")
                parts.append(f"```json\n{safe_data}\n```")

        if os_logs:
            parts.append("")
            parts.append("## Live OS Diagnostics (collected via SSH)")
            parts.append("The following data was collected in real-time from the server via SSH. Cross-reference with database data above to identify OS-level root causes.")
            for source, data in os_logs.items():
                safe_data = redact_dict(data) if isinstance(data, dict) else redact_text(str(data))
                parts.append(f"### {source}")
                parts.append(f"```json\n{safe_data}\n```")
    elif logs:
        parts.append("")
        # Split logs into DB and OS categories
        db_logs = {k: v for k, v in logs.items() if not k.startswith("ssh_")}
        os_logs = {k: v for k, v in logs.items() if k.startswith("ssh_")}

        if os_logs and db_logs:
            parts.append("## Collected Diagnostic Data (Database + OS)")
            parts.append("Both database queries and OS-level diagnostics were collected. Cross-reference to identify the root cause.")
        elif os_logs:
            parts.append("## Live OS Diagnostics (collected via SSH)")
            parts.append("The following data was collected in real-time from the server via SSH. Use it to refine your root cause analysis.")
        else:
            parts.append("## Collected System Data")
            parts.append("Note: Some MCP queries may have failed — check each entry for success/error status.")

        for source, data in logs.items():
            safe_data = redact_dict(data) if isinstance(data, dict) else redact_text(str(data))
            parts.append(f"### {source}")
            parts.append(f"```json\n{safe_data}\n```")
    else:
        parts.append("")
        if agent_type == "os":
            parts.append("## OS Diagnostics")
            parts.append("No matching SSH server configuration was found for this alert instance. Analysis is based solely on alert metadata.")
        else:
            parts.append("## Database Connectivity")
            parts.append("No MCP server connection was available for this alert instance. Analysis is based solely on alert metadata.")

    # ── Jira historical context ──
    if jira_context and jira_context.get("jira_summary"):
        parts.append("")
        parts.append(jira_context["jira_summary"])

    # ── RAG Knowledge Base context ──
    if rag_context:
        parts.append("")
        parts.append(rag_context)
        parts.append("")
        parts.append("Use the knowledge base context above to inform your analysis. Cite the source when referencing KB content.")

    parts.append("")
    parts.append("Analyze this alert and provide your diagnosis with actionable remediation steps.")
    parts.append("")
    parts.append("REQUIRED: Your JSON response MUST include a `problem_statement` field — 2-3 plain-English sentences describing WHAT is happening right now, as if briefing a non-technical manager. Extract and reference specific metric values (percentages, sizes, counts, thresholds, error codes) directly from the alert description and live data. Clearly state the business impact (e.g. queries will fail, application downtime, data loss risk). Do NOT be vague — mention actual numbers.")
    parts.append("")
    parts.append("IMPORTANT: Include a `fix_commands` array in your JSON response with specific remediation commands. Each fix command must have:")
    parts.append('- `type`: "sql", "os", or "config"')
    parts.append('- `description`: what the command does')
    parts.append('- `command`: the exact command to run')
    parts.append('- `risk_level`: "Low", "Medium", "High", or "Critical"')
    parts.append('- `requires_approval`: true for risky operations, false for safe diagnostics')

    if agent_type == "os":
        if mcp_connected:
            parts.append("")
            parts.append("CROSS-DOMAIN ANALYSIS — OS AGENT WITH DATABASE DATA: This alert was primarily classified as OS/infrastructure, ")
            parts.append("but database diagnostic data was also collected. Analyze BOTH. ")
            parts.append("Use type=\"os\" for shell commands and type=\"sql\" for database remediation as appropriate. ")
            parts.append("Correlate OS and database findings — e.g., disk full on /u01 may relate to tablespace growth.")
        else:
            parts.append("")
            parts.append("CRITICAL CONSTRAINT — OS AGENT: This is a pure OS/infrastructure alert. ")
            parts.append("You MUST only provide fix_commands with type=\"os\". ")
            parts.append("Do NOT suggest any SQL queries, database connections, or type=\"sql\" commands. ")
            parts.append("All commands must be standard Linux/Unix shell commands (df, du, find, rm, systemctl, etc.).")
    elif agent_type == "database":
        if os_collected:
            parts.append("")
            parts.append("CROSS-DOMAIN ANALYSIS — DATABASE AGENT WITH OS DATA: This is a database alert, ")
            parts.append("and OS-level diagnostics were also collected. Analyze BOTH layers. ")
            parts.append("Use type=\"sql\" for database commands and type=\"os\" for OS-level remediation as needed. ")
            parts.append("Correlate database and OS findings — e.g., tablespace full may need OS file cleanup, ")
            parts.append("sessions blocked may indicate CPU/memory pressure from the OS side.")
        else:
            parts.append("")
            parts.append("CONSTRAINT — DATABASE AGENT: Focus fix_commands on database-level remediation. ")
            parts.append("Use type=\"sql\" for Oracle/DB commands and type=\"os\" only for OS-level storage operations directly related to the database.")

    if mcp_connected:
        parts.append("")
        parts.append("Use ACTUAL values from the live data above (tablespace names, session IDs, SQL IDs, etc.) in your fix commands — do NOT use placeholders.")
    return "\n".join(parts)


def _match_ssh_server(
    servers: list[ServerConfig],
    alert: Alert,
    *,
    related_hosts: list[str] | None = None,
) -> tuple[ServerConfig | None, str]:
    """Find the best-matching SSH ServerConfig for an alert.

    Multi-pass matching:
      1. Exact host match against alert instance
      2. Partial match (instance substring in host/name/tags)
      3. Fallback to related hosts (cross-domain host-affinity)

    Returns ``(matched_server, match_reason)`` or ``(None, "")``.
    Requires at least 3 characters in the match token to prevent
    spurious substring hits (e.g. "db" matching "prod-db-server").
    """
    _MIN_MATCH_LEN = 3

    instance = (alert.instance or "").lower().strip()
    instance_host = instance.split(":")[0] if ":" in instance else instance

    # Pass 1 — exact host
    if instance_host and len(instance_host) >= _MIN_MATCH_LEN:
        for s in servers:
            if instance_host == (s.host or "").lower():
                return s, f"exact host (instance='{instance_host}' == host='{s.host}')"

    # Pass 2 — partial (instance substring in host/name/tags)
    if instance_host and len(instance_host) >= _MIN_MATCH_LEN:
        for s in servers:
            h = (s.host or "").lower()
            n = (s.name or "").lower()
            t = (s.tags or "").lower()
            if instance_host in h or instance_host in n or instance_host in t:
                return s, f"partial (instance='{instance_host}' in server '{s.name}')"

    # Pass 3 — related hosts (cross-domain affinity from MCP oracle_host)
    if related_hosts:
        for rh in related_hosts:
            rh_lower = rh.lower().strip()
            if len(rh_lower) < _MIN_MATCH_LEN:
                continue
            for s in servers:
                if rh_lower == (s.host or "").lower():
                    return s, f"cross-domain affinity (mcp_host='{rh}' == ssh_host='{s.host}')"

    return None, ""


async def _collect_os_diagnostics(
    servers: list[ServerConfig],
    alert: Alert,
    *,
    related_hosts: list[str] | None = None,
) -> tuple[dict, list]:
    """Run a standard set of OS diagnostic commands over SSH for infrastructure alerts.

    Uses ``_match_ssh_server`` to find the best server, with optional
    ``related_hosts`` for cross-domain affinity (e.g. MCP oracle_host values).
    """
    collected: dict = {}
    tools: list = []

    if not servers:
        return collected, tools

    matched_server, match_reason = _match_ssh_server(
        servers, alert, related_hosts=related_hosts,
    )

    if not matched_server:
        logger.info(
            "OS diagnostics: no ServerConfig matched instance '%s' (related_hosts=%s) — skipping",
            alert.instance or "", related_hosts or [],
        )
        return collected, tools

    logger.info(
        "OS diagnostics: matched server '%s' (%s) — %s",
        matched_server.name, matched_server.host, match_reason,
    )

    # Standard OS diagnostic commands — all read-only / safe
    diagnostic_commands = [
        ("disk_usage_human",      "df -h"),
        ("disk_usage_inodes",     "df -i"),
        ("top_disk_consumers",    "du -sh /* 2>/dev/null | sort -rh | head -20"),
        ("u01_top_consumers",     "du -sh /u01/* 2>/dev/null | sort -rh | head -20"),
        ("large_files_u01",       "find /u01 -xdev -type f -size +500M 2>/dev/null | head -20"),
        ("memory_usage",          "free -h"),
        ("cpu_load",              "uptime"),
        ("top_processes",         "ps aux --sort=-%mem | head -20"),
        ("os_release",            "cat /etc/os-release 2>/dev/null || uname -a"),
    ]

    for cmd_name, command in diagnostic_commands:
        try:
            result = await run_ssh_command(matched_server, command, use_sudo=False, timeout=15)
            collected[f"ssh_{cmd_name}"] = result
            tools.append({
                "tool": "ssh_command",
                "server": matched_server.name,
                "command_name": cmd_name,
                "command": command,
            })
        except Exception as e:
            logger.warning("OS diagnostic command '%s' failed on %s: %s", cmd_name, matched_server.name, e)
            collected[f"ssh_{cmd_name}_error"] = str(e)

    return collected, tools


def _match_mcp_servers(
    servers: list[MCPServerConfig],
    alert: Alert,
    agent_profile: AgentProfile | None = None,
) -> list[MCPServerConfig]:
    """Match MCP servers to the alert by instance, service, or DB label hints.

    Guardrails:
      - Returns ``[]`` for OS/infrastructure agents (MCP is never appropriate).
      - Requires at least 3-character tokens to prevent spurious substring hits.
      - Gathers DB hints from multiple alert labels (db, db_instance, database,
        oracle_sid, service_name, oracle_service, datname, sid).
      - Logs every match decision for audit.
    """
    if not servers:
        return []

    # OS / infrastructure agents must never use MCP/SQL
    if agent_profile:
        at = getattr(agent_profile, "agent_type", "general") or "general"
        if at in ("os", "infrastructure"):
            logger.info("MCP match: blocked for agent_type='%s'", at)
            return []

    _MIN_MATCH_LEN = 3

    instance = (alert.instance or "").lower().strip()
    instance_host = instance.split(":")[0] if ":" in instance else instance

    alert_labels = {k.lower(): str(v).lower() for k, v in (alert.labels or {}).items()}

    # Gather all DB-related hints from labels
    db_hints: set[str] = set()
    for label_key in (
        "db", "db_instance", "database", "dbname",
        "oracle_sid", "service_name", "oracle_service", "datname", "sid",
    ):
        val = alert_labels.get(label_key, "").strip()
        if val and len(val) >= _MIN_MATCH_LEN:
            db_hints.add(val)

    matched: list[MCPServerConfig] = []
    for s in servers:
        svc = (s.oracle_service or "").lower()
        name = (s.name or "").lower()
        host = (s.oracle_host or "").lower()

        # Exact oracle_host match (strongest signal)
        if instance_host and len(instance_host) >= _MIN_MATCH_LEN and instance_host == host:
            matched.append(s)
            logger.debug("MCP match: '%s' — exact host (instance='%s')", s.name, instance_host)
            continue

        # Partial: instance token in service/name/host
        if instance_host and len(instance_host) >= _MIN_MATCH_LEN and (
            instance_host in svc or instance_host in name or instance_host in host
        ):
            matched.append(s)
            logger.debug("MCP match: '%s' — partial (instance='%s')", s.name, instance_host)
            continue

        # DB label hints match service or server name
        if db_hints and any(hint in svc or hint in name for hint in db_hints):
            matched.append(s)
            logger.debug("MCP match: '%s' — db label hint %s", s.name, db_hints)
            continue

    if matched:
        logger.info(
            "MCP server match: %d server(s) for instance '%s': %s",
            len(matched), instance, [s.name for s in matched],
        )
    else:
        logger.info(
            "MCP server match: no servers for instance '%s' (db_hints=%s)",
            instance, db_hints or set(),
        )

    return matched


def _find_cross_domain_mcp_servers(
    mcp_servers: list[MCPServerConfig],
    ssh_host: str,
) -> list[MCPServerConfig]:
    """Find MCP servers co-located with an SSH server by host affinity.

    Used for OS→DB cross-domain diagnostics: when an OS alert matches an SSH
    server, find MCP databases running on the same host so we can check DB
    health alongside OS metrics.

    Requires at least 3 characters to prevent spurious matches.
    """
    if not mcp_servers or not ssh_host:
        return []

    host = ssh_host.lower().strip()
    if len(host) < 3:
        return []

    matched = []
    for mcp in mcp_servers:
        mcp_host = (mcp.oracle_host or "").lower()
        if mcp_host and (
            host == mcp_host
            or mcp_host.startswith(host)
            or host.startswith(mcp_host)
        ):
            matched.append(mcp)

    if matched:
        logger.info(
            "Cross-domain MCP match: SSH host '%s' → MCP servers %s",
            ssh_host, [m.name for m in matched],
        )

    return matched


# ---------------------------------------------------------------------------
# Phase-1 helper: ask AI to generate diagnostic SQL
# ---------------------------------------------------------------------------

_SQL_GEN_SYSTEM_PROMPT = """\
You are a database diagnostic SQL generator. Given an infrastructure/database alert, \
produce a set of read-only Oracle SQL SELECT statements that would help diagnose the issue.

Rules:
- Generate ONLY SELECT statements. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, \
  CREATE, GRANT, REVOKE, TRUNCATE, MERGE, or any DDL/DML.
- Each query must be a single SQL statement (no PL/SQL blocks).
- Target Oracle V$ views, DBA_/ALL_/USER_ dictionary views, or standard catalog views.
- Limit result sets with FETCH FIRST N ROWS ONLY or WHERE/HAVING filters where appropriate.
- Return between 2 and 8 queries, tailored to the specific alert type.
- Give each query a short snake_case name that describes what it checks.

Respond with valid JSON in this exact format:
{
  "queries": {
    "query_name_1": "SELECT ...",
    "query_name_2": "SELECT ..."
  }
}"""


async def _ai_generate_diagnostic_queries(
    ai_config: AIProviderConfig,
    alert: Alert,
    agent_system_prompt: str | None,
) -> dict[str, str]:
    """Ask the AI to generate diagnostic SQL queries for this alert."""
    prompt_parts = [
        "Generate diagnostic Oracle SQL queries for this alert:",
        f"- Alert name: {redact_text(alert.alertname or '')}",
        f"- Severity: {alert.severity}",
        f"- Instance: {redact_text(alert.instance or 'N/A')}",
        f"- Summary: {redact_text(alert.summary or 'N/A')}",
        f"- Description: {redact_text(alert.description or 'N/A')}",
    ]
    if alert.labels:
        safe_labels = redact_dict(alert.labels)
        prompt_parts.append("- Labels: " + ", ".join(f"{k}={v}" for k, v in safe_labels.items()))

    prompt = "\n".join(prompt_parts)

    response = await generate_raw_json(ai_config, prompt, _SQL_GEN_SYSTEM_PROMPT)
    raw_queries: dict = response.get("queries", {})

    # Validate and sanitise
    safe_queries: dict[str, str] = {}
    for name, sql in list(raw_queries.items())[:_MAX_GENERATED_QUERIES]:
        if _validate_sql_safe(sql):
            safe_queries[str(name)] = str(sql).strip().rstrip(";")
        else:
            logger.warning("AI generated unsafe SQL (rejected): %s → %s", name, sql)

    return safe_queries


# ---------------------------------------------------------------------------
# SQL safety gate — only SELECT allowed
# ---------------------------------------------------------------------------

_UNSAFE_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|REVOKE|TRUNCATE|MERGE|EXEC|EXECUTE|CALL|BEGIN|DECLARE)\b",
    re.IGNORECASE,
)


def _validate_sql_safe(sql: str) -> bool:
    """Return True only if the SQL is a read-only SELECT statement."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped.upper().startswith("SELECT"):
        return False
    if _UNSAFE_PATTERN.search(stripped):
        return False
    return True


# ---------------------------------------------------------------------------
# AI provider lookup
# ---------------------------------------------------------------------------

async def _get_ai_provider(db) -> AIProviderConfig | None:
    """Return the default (or any active) AI provider."""
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.is_default == True,
            AIProviderConfig.is_active == True,
        )
    )
    config = result.scalar_one_or_none()
    if config:
        return config
    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.is_active == True)
    )
    return result.scalar_one_or_none()
