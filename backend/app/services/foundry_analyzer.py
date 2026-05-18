"""Foundry analyzer — Azure AI Foundry multi-agent analysis pipeline.

This module is completely independent from the built-in alert_analyzer.py.
It reads the agent pipeline dynamically from foundry_agent_configs and
orchestrates: knowledge → researcher → collector → solver → notifier(s).
"""
import json
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.alert import Alert, AlertAnalysis
from app.models.foundry_config import FoundryAgentConfig
from app.models.mcp_config import MCPServerConfig
from app.services.tool_registry import execute_tool
from app.services.notification_resolver import resolve_recipients
from app.services.pii_redactor import redact_text, redact_dict
from app.config import settings

logger = logging.getLogger(__name__)


async def analyze_alert_with_foundry(alert_id: str, analyst_hint: str | None = None):
    """Run the full Azure AI Foundry multi-agent pipeline for an alert."""
    async with async_session() as db:
        try:
            result = await db.execute(select(Alert).where(Alert.id == alert_id))
            alert = result.scalar_one_or_none()
            if not alert:
                logger.error("Alert %s not found for Foundry analysis", alert_id)
                return

            alert.analysis_status = "analyzing"
            await db.commit()

            # ── Load the agent pipeline from the registry ──
            pipeline_result = await db.execute(
                select(FoundryAgentConfig)
                .where(FoundryAgentConfig.is_active == True)
                .order_by(FoundryAgentConfig.pipeline_order)
            )
            all_agents = pipeline_result.scalars().all()

            if not all_agents:
                logger.error("No Foundry agents configured — cannot analyze alert %s", alert_id)
                alert.analysis_status = "failed"
                await db.commit()
                return

            # ── Filter agents relevant to this alert ──
            alert_category = (alert.alert_category or "general").lower()
            workflow_pipeline, matched_specialists = _filter_pipeline(all_agents, alert_category, alert)

            # ── Determine system type from the pipeline agents ──
            # Use the most specific system_type from matched agents (not "all")
            system_type = _resolve_system_type(matched_specialists + workflow_pipeline, alert)

            # ── Execute pipeline steps ──
            context = {
                "alert": _alert_to_context(alert),
                "analyst_hint": redact_text(analyst_hint) if analyst_hint else None,
                "knowledge_docs": [],
                "triage_result": "",
                "diagnostic_plan": "",
                "collected_data": {},
                "specialist_reviews": [],
                "validation_result": "",
                "analysis_result": None,
                "system_type": system_type,
                "matched_specialists": [
                    {
                        "agent_name": agent.agent_name,
                        "system_type": agent.system_type,
                        "role": agent.role,
                    }
                    for agent in matched_specialists
                ],
            }
            tools_called = []
            pipeline_trace = []
            specialists_ran = False

            # ── Standard optimizations (apply to ALL severities) ──
            # 1. intake is skipped when triage_master is present — triage does the same classification
            # 2. collector runs tools-only (Python executes SQL/SSH) — no extra LLM interpreter call
            has_triage = any(a.role == "triage_master" for a in workflow_pipeline)

            for agent_config in workflow_pipeline:
                role = agent_config.role
                agent_id = agent_config.foundry_agent_name

                if not agent_id:
                    if agent_config.is_optional:
                        logger.debug("Skipping optional agent %s (no agent name)", agent_config.agent_name)
                        continue
                    else:
                        logger.warning("Required agent %s has no Foundry agent name", agent_config.agent_name)
                        continue

                # Optimization 1: skip intake — triage_master covers classification for all alerts
                if role == "intake" and has_triage:
                    logger.debug("Skipping intake — triage_master will classify")
                    pipeline_trace.append({"agent": agent_config.agent_name, "role": role, "status": "skipped", "reason": "merged into triage"})
                    continue

                # Optimization 2: collector runs Python tools directly, no LLM interpreter needed
                if role == "collector":
                    data, calls = await _run_collector_step(db, context, alert)
                    context["collected_data"] = data
                    tools_called.extend(calls)
                    pipeline_trace.append({"agent": agent_config.agent_name, "role": role, "status": "ok", "note": "tools-only, no LLM call"})
                    continue

                try:
                    if role == "intake":
                        # Fallback: only runs if no triage_master in pipeline
                        context["intake_result"] = await _run_intake_step(context, agent_id)
                        try:
                            intake_json = json.loads(context["intake_result"]) if isinstance(context["intake_result"], str) else context["intake_result"]
                            if isinstance(intake_json, dict) and intake_json.get("category"):
                                context["system_type"] = _normalize_system_type(intake_json["category"], alert)
                        except (json.JSONDecodeError, TypeError):
                            pass
                        pipeline_trace.append({"agent": agent_config.agent_name, "role": role, "status": "ok"})

                    elif role == "triage_master":
                        context["triage_result"] = await _run_triage_step(context, agent_id)
                        try:
                            triage_json = json.loads(context["triage_result"]) if isinstance(context["triage_result"], str) else context["triage_result"]
                            if isinstance(triage_json, dict):
                                if triage_json.get("technology"):
                                    context["system_type"] = _normalize_system_type(triage_json["technology"], alert)
                                required = triage_json.get("required_specialists") or []
                                _extend_specialists_from_triage(context, matched_specialists, all_agents, required)
                        except (json.JSONDecodeError, TypeError):
                            pass
                        pipeline_trace.append({"agent": agent_config.agent_name, "role": role, "status": "ok"})

                    elif role == "knowledge":
                        context["knowledge_docs"] = await _run_knowledge_step(alert, agent_config)
                        pipeline_trace.append({"agent": agent_config.agent_name, "role": role, "status": "ok"})

                    elif role == "researcher":
                        context["diagnostic_plan"] = await _run_researcher_step(context, agent_id)
                        pipeline_trace.append({"agent": agent_config.agent_name, "role": role, "status": "ok"})

                    elif role in ("solver", "solution"):
                        if matched_specialists and not specialists_ran:
                            specialist_results = await _run_specialist_steps(context, matched_specialists)
                            context["specialist_reviews"] = specialist_results
                            pipeline_trace.extend([
                                {
                                    "agent": item["agent_name"],
                                    "role": "technology_specialist",
                                    "status": item["status"],
                                    "system_type": item["system_type"],
                                }
                                for item in specialist_results
                            ])
                            specialists_ran = True
                        context["analysis_result"] = await _run_solver_step(context, agent_id)
                        pipeline_trace.append({"agent": agent_config.agent_name, "role": role, "status": "ok"})

                    elif role == "validation":
                        context["validation_result"] = await _run_validation_step(context, agent_id)
                        pipeline_trace.append({"agent": agent_config.agent_name, "role": role, "status": "ok"})

                    elif role == "notifier":
                        notif_result = await _run_notifier_step(db, context, alert, agent_config)
                        pipeline_trace.append({"agent": agent_config.agent_name, "role": role, "status": "ok", **notif_result})

                    else:
                        logger.debug("Unknown pipeline role '%s' for %s", role, agent_config.agent_name)

                except Exception as e:
                    logger.warning("Pipeline step %s (%s) failed: %s", agent_config.agent_name, role, e)
                    pipeline_trace.append({"agent": agent_config.agent_name, "role": role, "status": "error", "error": str(e)})
                    if not agent_config.is_optional:
                        pass

            # ── Parse and save analysis ──
            solver_text = context.get("analysis_result") or ""
            ai_response = _parse_solver_response(solver_text)
            ai_response["pipeline_trace"] = pipeline_trace
            ai_response["knowledge_docs"] = context.get("knowledge_docs", [])
            ai_response["triage_result"] = context.get("triage_result", "")
            ai_response["specialist_reviews"] = context.get("specialist_reviews", [])
            ai_response["validation_result"] = context.get("validation_result", "")
            ai_response["matched_specialists"] = context.get("matched_specialists", [])

            fix_commands = []
            for cmd in ai_response.get("fix_commands", []):
                if isinstance(cmd, dict) and "command" in cmd:
                    fix_commands.append({
                        "type": cmd.get("type", "sql"),
                        "description": cmd.get("description", ""),
                        "command": cmd["command"],
                        "risk_level": cmd.get("risk_level", "Medium"),
                        "requires_approval": cmd.get("requires_approval", True),
                    })

            # prevention_steps may be a dict/list from the AI — normalize to string for VARCHAR column
            prevention_raw = ai_response.get("prevention_steps")
            if isinstance(prevention_raw, list):
                prevention_str = "\n".join(str(s) for s in prevention_raw)
            elif isinstance(prevention_raw, dict):
                for key in ("text", "steps", "prevention", "content", "summary"):
                    if key in prevention_raw:
                        inner = prevention_raw[key]
                        prevention_str = "\n".join(str(i) for i in inner) if isinstance(inner, list) else str(inner)
                        break
                else:
                    prevention_str = json.dumps(prevention_raw)
            else:
                prevention_str = prevention_raw

            raw_action_plan = ai_response.get("action_plan", [])
            action_plan_normalized = []
            for _item in (raw_action_plan if isinstance(raw_action_plan, list) else []):
                if isinstance(_item, str):
                    action_plan_normalized.append(_item)
                elif isinstance(_item, dict):
                    _parts = []
                    if _item.get("step"): _parts.append(str(_item["step"]))
                    if _item.get("description"): _parts.append(str(_item["description"]))
                    action_plan_normalized.append(": ".join(_parts) if _parts else json.dumps(_item))
                else:
                    action_plan_normalized.append(str(_item))

            analysis = AlertAnalysis(
                alert_id=alert.id,
                root_cause=ai_response.get("root_cause") if isinstance(ai_response.get("root_cause"), (str, type(None))) else str(ai_response.get("root_cause")),
                confidence_score=ai_response.get("confidence_score"),
                action_plan=action_plan_normalized,
                fix_commands=fix_commands,
                prevention_steps=prevention_str,
                risk_level=ai_response.get("risk_level") if isinstance(ai_response.get("risk_level"), (str, type(None))) else str(ai_response.get("risk_level")),
                ai_provider_used="azure_foundry",
                ai_model_used="foundry-pipeline",
                tools_called=tools_called,
                logs_collected=context.get("collected_data", {}),
                full_ai_response=ai_response,
            )
            db.add(analysis)
            alert.analysis_status = "analyzed"
            # ── Update matched_agent_name with the actual pipeline agents that ran ──
            ran_agents = [
                t.get("agent", "") for t in pipeline_trace
                if t.get("status") == "ok" and t.get("role") not in ("intake",)
            ]
            if ran_agents:
                alert.matched_agent_name = ", ".join(ran_agents[:6])
            await db.commit()
            logger.info("Alert %s analyzed via Azure AI Foundry pipeline — agents: %s", alert_id, alert.matched_agent_name)

        except Exception as e:
            logger.exception("Foundry pipeline error for alert %s: %s", alert_id, e)
            try:
                alert.analysis_status = "failed"
                await db.commit()
            except Exception:
                pass


# ── Pipeline Step Implementations ──


async def _run_intake_step(context: dict, agent_id: str) -> str:
    """Ask the intake agent to normalize the alert and classify its domain."""
    alert_ctx = context["alert"]
    parts = [
        "Normalize this infrastructure alert and classify its technology domain.",
        "Return ONLY JSON: {title, severity, host, service, category, raw_summary}",
        "category must be one of: linux, cloud, oracle, postgresql, mysql, sqlserver,",
        "  mongodb, kubernetes, network, security, application, unknown",
        "",
        f"alertname: {alert_ctx['alertname']}",
        f"severity: {alert_ctx['severity']}",
        f"status: {alert_ctx['status']}",
        f"instance: {alert_ctx.get('instance', 'N/A')}",
        f"summary: {alert_ctx.get('summary', 'N/A')}",
        f"description: {alert_ctx.get('description', 'N/A')}",
        f"labels: {json.dumps(alert_ctx.get('labels', {}))}",
    ]
    if context.get("analyst_hint"):
        parts.insert(0, f"ANALYST GUIDANCE: {context['analyst_hint']}")
    messages = [{"role": "user", "content": "\n".join(parts)}]
    from app.services.azure_foundry_service import run_agent
    return await run_agent(agent_id, messages, timeout=30.0)


def _extend_specialists_from_triage(
    context: dict,
    matched_specialists: list,
    all_agents: list,
    required_domains: list[str],
) -> None:
    """Add any triage-recommended specialist agents not already in matched_specialists."""
    already_matched = {a.system_type for a in matched_specialists}
    for domain in required_domains:
        domain_lower = domain.lower().strip()
        if domain_lower in already_matched:
            continue
        for agent in all_agents:
            if (
                getattr(agent, "agent_line", "workflow") == "technology"
                and agent.system_type == domain_lower
                and agent.is_active
                and agent.foundry_agent_name
            ):
                matched_specialists.append(agent)
                already_matched.add(domain_lower)
                # Update context metadata too
                context.setdefault("matched_specialists", []).append({
                    "agent_name": agent.agent_name,
                    "system_type": agent.system_type,
                    "role": agent.role,
                    "added_by": "triage",
                })
                break


async def _run_knowledge_step(alert: Alert, agent_config: FoundryAgentConfig) -> list[dict]:
    """Ask the infraai-knowledge Foundry agent to find relevant docs for this alert.

    The agent has the file_search tool enabled with the infraai-knowledge-store
    vector store attached.  Azure AI Foundry handles chunking, embedding, and
    semantic search natively — no external services needed.

    Falls back to direct Azure AI Search / SharePoint search if the agent call fails.
    """
    from app.services.azure_foundry_service import run_agent

    agent_id = agent_config.foundry_agent_name
    query = f"{alert.alertname} {alert.alert_category or ''} {alert.summary or ''}".strip()

    # ── Primary: call the Foundry knowledge agent (uses built-in file_search) ──
    if agent_id:
        try:
            prompt = (
                f"Find relevant runbooks, past incidents, and documentation for this alert:\n\n"
                f"Alert: {alert.alertname}\n"
                f"Category: {alert.alert_category or 'general'}\n"
                f"Summary: {alert.summary or 'N/A'}\n"
                f"Description: {alert.description or 'N/A'}\n\n"
                f"Return up to 5 items. For each item include: title, source, and a brief relevant excerpt."
            )
            response = await run_agent(agent_id, [{"role": "user", "content": prompt}], timeout=45.0)
            # Wrap the agent's synthesized response as a single knowledge doc
            if response and response.strip():
                return [{"title": "Knowledge Base", "content": response, "source": "foundry:file_search", "score": 1.0}]
        except Exception as e:
            logger.warning("infraai-knowledge agent call failed, falling back to direct search: %s", e)

    # ── Fallback: direct search (Azure AI Search + SharePoint + RAG pgvector) ──
    from app.services.azure_graph_service import search_sharepoint, search_ai_index
    docs = []

    try:
        from app.database import async_session
        from app.services.knowledge_retrieval_service import search_knowledge_base
        async with async_session() as db:
            rag_chunks = await search_knowledge_base(query, db, top_k=3)
            for chunk in rag_chunks:
                docs.append({
                    "title": chunk.document_title,
                    "content": chunk.chunk_content,
                    "source": f"RAG:{chunk.source_name}",
                    "score": chunk.score,
                })
    except Exception as e:
        logger.debug("RAG search skipped in foundry knowledge step: %s", e)

    ai_docs = await search_ai_index(query, max_results=3)
    docs.extend(ai_docs)

    # Try Foundry live SharePoint search via the infraai-knowledge agent
    # if the Foundry endpoint is configured. This avoids using Microsoft
    # Graph API when Foundry has been granted access and the agent has
    # `sharepoint_grounding` enabled.
    if settings.AZURE_AI_FOUNDRY_ENDPOINT:
        try:
            from app.services.azure_foundry_service import run_agent
            prompt = (
                f"Search SharePoint for the following query and return up to 3 items as JSON array"
                f" with fields title, snippet, url.\nQuery: {query}"
            )
            response = await run_agent("infraai-knowledge", [{"role": "user", "content": prompt}], timeout=30.0)
            if response and response.strip():
                try:
                    import json as _json
                    parsed = _json.loads(response)
                    if isinstance(parsed, list):
                        for item in parsed[:3]:
                            docs.append({
                                "title": item.get("title", ""),
                                "snippet": item.get("snippet", item.get("content", ""))[:500],
                                "url": item.get("url", item.get("webUrl", "")),
                            })
                except Exception:
                    # Non-JSON response — attach as a single synthesized doc
                    docs.append({"title": "Foundry SharePoint Search", "content": response, "source": "foundry:sharepoint"})
        except Exception as e:
            logger.debug("Foundry live SharePoint search failed: %s", e)

    # Fallback: direct search via AI Search + Graph API (if Foundry path produced no docs)
    if not docs:
        sp_docs = await search_sharepoint(query, max_results=3)
        docs.extend(sp_docs)

    return docs[:5]


async def _run_triage_step(context: dict, agent_id: str) -> str:
    """Ask the triage agent to classify the incident and frame the investigation."""
    alert_ctx = context["alert"]
    parts = [
        "Triage this alert before deep diagnosis.",
        "Determine the most likely technology domain, blast radius, and best investigation direction.",
        "Respond in concise JSON with fields: likely_domain, urgency_summary, likely_impacted_layers, recommended_focus.",
        "",
        f"Alert: {alert_ctx['alertname']}",
        f"Severity: {alert_ctx['severity']}",
        f"Status: {alert_ctx['status']}",
        f"Category: {alert_ctx.get('category', 'general')}",
        f"Summary: {alert_ctx.get('summary', 'N/A')}",
        f"Description: {alert_ctx.get('description', 'N/A')}",
    ]
    if context.get("analyst_hint"):
        parts.insert(0, f"ANALYST GUIDANCE: {context['analyst_hint']}")

    messages = [{"role": "user", "content": "\n".join(parts)}]
    from app.services.azure_foundry_service import run_agent
    return await run_agent(agent_id, messages, timeout=45.0)


async def _run_researcher_step(context: dict, agent_id: str) -> str:
    """Ask the Researcher agent to analyze the alert and suggest diagnostics."""
    messages = []

    alert_ctx = context["alert"]
    system_type = context.get("system_type", "general")

    msg_parts = [
        "Analyze this infrastructure alert and determine what diagnostic data should be collected.",
        "You can request BOTH database queries AND OS-level commands. The collector will execute both.",
        "",
        f"Alert: {alert_ctx['alertname']}",
        f"Severity: {alert_ctx['severity']}",
        f"Status: {alert_ctx['status']}",
        f"Instance: {alert_ctx.get('instance', 'N/A')}",
        f"Category: {alert_ctx.get('category', 'general')}",
        f"System Type: {system_type}",
        f"Summary: {alert_ctx.get('summary', 'N/A')}",
        f"Description: {alert_ctx.get('description', 'N/A')}",
    ]

    if context.get("triage_result"):
        msg_parts.append(f"\nTRIAGE CONTEXT:\n{context['triage_result']}")

    # Add platform-specific guidance with cross-domain awareness
    if system_type in ("oracle", "sqlcl"):
        msg_parts.append("\nPLATFORM CONTEXT: This is an Oracle Database alert. Suggest Oracle-specific diagnostic queries (V$ views, DBA_ views, tablespace checks, AWR, ASH). Use Oracle SQL syntax.")
        msg_parts.append("CROSS-DOMAIN: Also suggest OS-level commands if the issue may involve disk space, memory, or process-level problems (e.g., df -h, du -sh /u01/*, ps aux | grep ora_).")
    elif system_type == "postgresql":
        msg_parts.append("\nPLATFORM CONTEXT: This is a PostgreSQL alert. Suggest PostgreSQL-specific diagnostic queries (pg_stat_*, pg_catalog, pg_locks, pg_settings). Use PostgreSQL SQL syntax.")
        msg_parts.append("CROSS-DOMAIN: Also suggest OS-level commands if relevant (e.g., disk usage on pg_data, PostgreSQL process checks).")
    elif system_type == "mysql":
        msg_parts.append("\nPLATFORM CONTEXT: This is a MySQL alert. Suggest MySQL-specific diagnostic queries (SHOW STATUS, INFORMATION_SCHEMA, SHOW PROCESSLIST, performance_schema). Use MySQL syntax.")
        msg_parts.append("CROSS-DOMAIN: Also suggest OS-level commands if relevant (e.g., disk usage, MySQL process checks).")
    elif system_type == "sqlserver":
        msg_parts.append("\nPLATFORM CONTEXT: This is a SQL Server alert. Suggest SQL Server-specific diagnostic queries (sys.dm_*, sys.databases, sp_who2). Use T-SQL syntax.")
        msg_parts.append("CROSS-DOMAIN: Also suggest OS-level commands if relevant.")
    elif system_type == "mongodb":
        msg_parts.append("\nPLATFORM CONTEXT: This is a MongoDB alert. Suggest MongoDB-specific diagnostics (db.serverStatus, db.currentOp, rs.status, collection stats).")
        msg_parts.append("CROSS-DOMAIN: Also suggest OS-level commands if relevant.")
    elif system_type in ("os", "linux", "aws", "azure", "cloud", "kubernetes", "infrastructure"):
        msg_parts.append("\nPLATFORM CONTEXT: This is an OS/infrastructure alert. Suggest OS-level diagnostics (df, free, top, ps, systemctl, journalctl).")
        msg_parts.append("CROSS-DOMAIN: If the OS issue may indicate a database problem (e.g., disk full on a DB data directory), also suggest relevant database diagnostic queries.")

    msg_parts.append("")
    msg_parts.append("FORMAT: Return SQL queries in ```sql code blocks and OS commands in ```bash code blocks.")

    if context.get("analyst_hint"):
        msg_parts.insert(0, f"⚠️ ANALYST GUIDANCE (highest priority): {context['analyst_hint']}")

    if context.get("knowledge_docs"):
        msg_parts.append("\nRelevant knowledge base documents:")
        for doc in context["knowledge_docs"][:3]:
            msg_parts.append(f"- {doc.get('title', 'Untitled')}: {doc.get('snippet', '')[:200]}")

    messages.append({"role": "user", "content": "\n".join(msg_parts)})
    from app.services.azure_foundry_service import run_agent
    return await run_agent(agent_id, messages, timeout=60.0)


async def _run_collector_step(
    db: AsyncSession,
    context: dict,
    alert: Alert,
) -> tuple[dict, list]:
    """Execute diagnostic data collection — SQL via MCP AND OS via SSH.

    Cross-domain: always attempts both database and OS diagnostics when
    the relevant infrastructure is configured, regardless of alert type.
    """
    collected = {}
    calls = []
    system_type = context.get("system_type", "general")

    # ── Database diagnostics via MCP ──
    mcp_result = await db.execute(
        select(MCPServerConfig).where(MCPServerConfig.is_active == True)
    )
    mcps = mcp_result.scalars().all()

    if mcps:
        # Try to extract SQL from the researcher's diagnostic plan
        diagnostic_plan = context.get("diagnostic_plan", "")
        queries = _extract_queries_from_plan(diagnostic_plan)

        # If no queries extracted, use default diagnostic queries per DB type
        if not queries:
            queries = _default_queries_for_system_type(system_type)

        for mcp in mcps:
            mcp_type = (mcp.server_type or "").lower()
            tool_name = _mcp_to_tool_name(mcp_type)
            if not tool_name:
                continue  # skip unknown MCP types

            for qname, sql in queries.items():
                try:
                    data = await execute_tool(tool_name, {
                        "config_id": str(mcp.id),
                        "sql": sql,
                    })
                    collected[f"{mcp.name}_{qname}"] = data
                    calls.append({
                        "tool": tool_name,
                        "server": mcp.name,
                        "query": qname,
                        "sql": sql,
                    })
                except Exception as e:
                    collected[f"{mcp.name}_{qname}_error"] = str(e)

    # ── OS diagnostics via SSH (cross-domain) ──
    from app.models.server_config import ServerConfig
    from app.services.ssh_service import run_ssh_command

    srv_result = await db.execute(
        select(ServerConfig).where(ServerConfig.is_active == True)
    )
    all_servers = srv_result.scalars().all()

    # ── Cloud diagnostics via MCP (independent of SSH servers) ──
    # "cloud" is the umbrella category for aws/azure — match any cloud MCP
    if system_type in ("aws", "azure", "kubernetes", "cloud") and mcps:
        for mcp in mcps:
            mcp_type = (mcp.server_type or "").lower()
            # For "cloud" alerts, match any cloud MCP (aws, azure, kubernetes)
            matches = (
                (system_type in ("cloud", "aws") and mcp_type == "aws") or
                (system_type in ("cloud", "azure") and mcp_type == "azure") or
                (system_type in ("cloud", "kubernetes") and mcp_type == "kubernetes") or
                (mcp_type == system_type)
            )
            if matches:
                try:
                    tool_name = f"{mcp_type}_exec"
                    tool_params = {"config_id": str(mcp.id)}
                    if mcp_type == "aws":
                        tool_params.update({"service": "ec2", "operation": "describe_instances", "params": {"Filters": [{"Name": "instance-id", "Values": [alert.instance or ""]}]}})
                    elif mcp_type == "azure":
                        rg = (mcp.env_vars or {}).get("AZURE_RESOURCE_GROUP", "")
                        tool_params.update({"service": "compute", "operation": "list", "resource_group": rg})
                    elif mcp_type == "kubernetes":
                        tool_params.update({"verb": "get", "resource": "nodes"})

                    data = await execute_tool(tool_name, tool_params)
                    collected[f"{mcp.name}_{mcp_type}"] = data
                    calls.append({
                        "tool": tool_name,
                        "server": mcp.name,
                        "system_type": mcp_type,
                    })
                except Exception as e:
                    collected[f"{mcp.name}_{mcp_type}_error"] = str(e)

    if all_servers:
        # Extract OS commands from the researcher's plan, or use defaults
        diagnostic_plan = context.get("diagnostic_plan", "")
        os_commands = _extract_os_commands_from_plan(diagnostic_plan)

        if not os_commands:
            # Default OS diagnostics — always useful for cross-domain analysis
            os_commands = [
                ("disk_usage", "df -h"),
                ("memory_usage", "free -h"),
                ("cpu_load", "uptime"),
                ("top_processes", "ps aux --sort=-%mem | head -15"),
            ]
            # Add DB-specific OS checks if this is a database alert
            if system_type in ("oracle", "sqlcl"):
                os_commands.extend([
                    ("u01_disk", "du -sh /u01/* 2>/dev/null | sort -rh | head -15"),
                    ("large_files_u01", "find /u01 -xdev -type f -size +500M 2>/dev/null | head -15"),
                    ("oracle_processes", "ps aux | grep -i '[o]ra_\\|[t]nslsnr\\|[d]b_' | head -20"),
                ])
            elif system_type == "postgresql":
                os_commands.extend([
                    ("pg_data_disk", "du -sh /var/lib/postgresql/* 2>/dev/null | sort -rh | head -15"),
                    ("pg_processes", "ps aux | grep -i '[p]ostgres' | head -20"),
                ])
            elif system_type == "mysql":
                os_commands.extend([
                    ("mysql_data_disk", "du -sh /var/lib/mysql/* 2>/dev/null | sort -rh | head -15"),
                    ("mysql_processes", "ps aux | grep -i '[m]ysql' | head -20"),
                ])
            elif system_type in ("aws", "azure", "cloud", "kubernetes"):
                os_commands.extend([
                    ("disk_usage", "df -h"),
                    ("memory_usage", "free -h"),
                    ("cpu_load", "uptime"),
                ])

        matched_server = _match_ssh_server(all_servers, alert)
        if matched_server:
            for cmd_name, command in os_commands:
                try:
                    result = await run_ssh_command(matched_server, command, use_sudo=False, timeout=30)
                    collected[f"ssh_{cmd_name}"] = result
                    calls.append({
                        "tool": "ssh_command",
                        "server": matched_server.name,
                        "command_name": cmd_name,
                        "command": command,
                    })
                except Exception as e:
                    collected[f"ssh_{cmd_name}_error"] = str(e)

    return collected, calls


async def _run_solver_step(context: dict, agent_id: str) -> str:
    """Ask the Solution agent to produce the final analysis."""
    alert_ctx = context["alert"]
    system_type = context.get("system_type", "general")

    parts = [
        "Analyze this alert and provide a comprehensive diagnosis:",
        f"\n## Alert: {alert_ctx['alertname']}",
        f"Severity: {alert_ctx['severity']}, Status: {alert_ctx['status']}",
        f"Instance: {alert_ctx.get('instance', 'N/A')}",
        f"System Type: {system_type}",
        f"Summary: {alert_ctx.get('summary', 'N/A')}",
        f"Description: {alert_ctx.get('description', 'N/A')}",
    ]

    if context.get("analyst_hint"):
        parts.insert(0, f"⚠️ ANALYST GUIDANCE: {context['analyst_hint']}")

    if context.get("knowledge_docs"):
        parts.append("\n## Knowledge Base Context:")
        for doc in context["knowledge_docs"]:
            parts.append(f"- {doc.get('title', '')}: {doc.get('snippet', '')[:300]}")

    if context.get("triage_result"):
        parts.append(f"\n## Triage Summary:\n{context['triage_result']}")

    if context.get("diagnostic_plan"):
        parts.append(f"\n## Diagnostic Plan:\n{context['diagnostic_plan']}")

    if context.get("collected_data"):
        parts.append("\n## Live Diagnostic Data:")
        for source, data in context["collected_data"].items():
            safe = redact_dict(data) if isinstance(data, dict) else redact_text(str(data))
            parts.append(f"### {source}\n```json\n{json.dumps(safe, default=str)}\n```")

    if context.get("specialist_reviews"):
        parts.append("\n## Technology Specialist Reviews:")
        for review in context["specialist_reviews"]:
            parts.append(
                f"### {review.get('agent_name')} ({review.get('system_type', 'general')})\n"
                f"{review.get('response', '')}"
            )

    # Platform-specific fix_commands constraints
    if system_type in ("oracle", "sqlcl"):
        parts.append("\nIMPORTANT — ORACLE DATABASE: Use type=\"sql\" for Oracle SQL commands (ALTER TABLESPACE, PURGE, etc.) and type=\"os\" for OS-level operations related to Oracle (e.g., clearing audit/trace files). Use Oracle-specific syntax.")
    elif system_type == "postgresql":
        parts.append("\nIMPORTANT — POSTGRESQL: Use type=\"sql\" for PostgreSQL commands (VACUUM, REINDEX, ALTER, pg_terminate_backend, etc.). Use PostgreSQL syntax — NOT Oracle syntax.")
    elif system_type == "mysql":
        parts.append("\nIMPORTANT — MYSQL: Use type=\"sql\" for MySQL commands (OPTIMIZE TABLE, KILL, SET GLOBAL, etc.). Use MySQL syntax.")
    elif system_type == "sqlserver":
        parts.append("\nIMPORTANT — SQL SERVER: Use type=\"sql\" for T-SQL commands (DBCC, ALTER DATABASE, KILL, sp_configure, etc.). Use T-SQL syntax.")
    elif system_type in ("os", "linux", "aws", "azure", "cloud", "kubernetes", "infrastructure"):
        parts.append("\nCRITICAL — OS/INFRASTRUCTURE ALERT: Only provide fix_commands with type=\"bash\". Do NOT suggest any SQL or database commands. All commands must be standard shell commands.")
    elif system_type == "network":
        parts.append("\nIMPORTANT — NETWORK ALERT: Use type=\"bash\" for all diagnostic and remediation commands (ip, iptables, ss, dig, curl, openssl). Do NOT suggest SQL commands.")
    elif system_type == "security":
        parts.append("\nIMPORTANT — SECURITY ALERT: Prioritize containment actions before remediation. Use type=\"bash\" for OS-level commands. Flag any command that could destroy forensic evidence.")
    elif system_type == "application":
        parts.append("\nIMPORTANT — APPLICATION ALERT: Use type=\"bash\" for process/service commands, type=\"kubectl\" for K8s-based app commands. Correlate with recent deployments and config changes.")

    parts.append(
        "\nRespond with JSON: {problem_statement, root_cause, confidence_score, "
        "action_plan, fix_commands, prevention_steps, risk_level, estimated_impact}"
    )

    messages = [{"role": "user", "content": "\n".join(parts)}]
    from app.services.azure_foundry_service import run_agent
    return await run_agent(agent_id, messages, timeout=120.0)


async def _run_specialist_steps(context: dict, specialist_agents: list[FoundryAgentConfig]) -> list[dict]:
    """Run matched technology specialists against the gathered alert context."""
    results = []
    for agent in specialist_agents:
        if not agent.foundry_agent_name:
            results.append({
                "agent_name": agent.agent_name,
                "system_type": agent.system_type,
                "status": "skipped",
                "response": "No Foundry agent name configured",
            })
            continue
        try:
            response = await _run_specialist_step(context, agent)
            results.append({
                "agent_name": agent.agent_name,
                "system_type": agent.system_type,
                "status": "ok",
                "response": response,
            })
        except Exception as exc:
            results.append({
                "agent_name": agent.agent_name,
                "system_type": agent.system_type,
                "status": "error",
                "response": str(exc),
            })
    return results


async def _run_specialist_step(context: dict, agent_config: FoundryAgentConfig) -> str:
    """Ask a technology specialist to produce a domain-specific assessment."""
    alert_ctx = context["alert"]
    parts = [
        "Provide a domain-specific assessment for this alert from your specialty.",
        "Focus on likely failure modes, strongest evidence, and safest next actions.",
        "",
        f"Technology Domain: {agent_config.system_type}",
        f"Alert: {alert_ctx['alertname']}",
        f"Severity: {alert_ctx['severity']}",
        f"Status: {alert_ctx['status']}",
        f"Instance: {alert_ctx.get('instance', 'N/A')}",
        f"Summary: {alert_ctx.get('summary', 'N/A')}",
        f"Description: {alert_ctx.get('description', 'N/A')}",
    ]
    if context.get("triage_result"):
        parts.append(f"\nTriage:\n{context['triage_result']}")
    if context.get("diagnostic_plan"):
        parts.append(f"\nDiagnostic Plan:\n{context['diagnostic_plan']}")
    if context.get("knowledge_docs"):
        parts.append("\nKnowledge Context:")
        for doc in context["knowledge_docs"][:3]:
            parts.append(f"- {doc.get('title', '')}: {doc.get('snippet', '')[:220]}")
    if context.get("collected_data"):
        parts.append("\nLive Diagnostic Data:")
        for source, data in context["collected_data"].items():
            safe = redact_dict(data) if isinstance(data, dict) else redact_text(str(data))
            parts.append(f"### {source}\n```json\n{json.dumps(safe, default=str)}\n```")

    messages = [{"role": "user", "content": "\n".join(parts)}]
    from app.services.azure_foundry_service import run_agent
    return await run_agent(agent_config.foundry_agent_name, messages, timeout=75.0)


async def _run_validation_step(context: dict, agent_id: str) -> str:
    """Ask the validation agent to review the proposed solution for safety and completeness."""
    parts = [
        "Review the proposed incident analysis for technical correctness, safety, and completeness.",
        "Highlight missing evidence, risky commands, and unsupported assumptions.",
        "Respond in concise JSON with: verdict, concerns, suggested_improvements, command_safety_notes.",
        "",
        f"System Type: {context.get('system_type', 'general')}",
        f"Solver Output:\n{context.get('analysis_result') or '{}'}",
    ]
    if context.get("specialist_reviews"):
        parts.append("\nSpecialist Reviews:")
        for review in context["specialist_reviews"]:
            parts.append(f"- {review.get('agent_name')}: {review.get('response', '')[:600]}")

    messages = [{"role": "user", "content": "\n".join(parts)}]
    from app.services.azure_foundry_service import run_agent
    return await run_agent(agent_id, messages, timeout=60.0)


async def _run_notifier_step(
    db: AsyncSession,
    context: dict,
    alert: Alert,
    agent_config: FoundryAgentConfig,
) -> dict:
    """Send notification (email via Outlook).

    Dual-path: if the notifier agent has a Foundry agent name configured,
    try invoking the Foundry notifier agent (which may use the OpenAPI email
    tool). Falls back to the direct Graph API ``send_outlook_email`` call.
    """
    analysis = context.get("analysis_result", "")
    parsed = _parse_solver_response(analysis)

    # Try to find matching MCP and profile for recipient resolution
    from app.models.agent_profile import AgentProfile
    matched_mcp = None
    matched_profile = None
    try:
        mcp_result = await db.execute(
            select(MCPServerConfig).where(MCPServerConfig.is_active == True)
        )
        mcps = mcp_result.scalars().all()
        if mcps:
            matched_mcp = mcps[0]  # Use first active MCP (pipeline already filtered by system)

        profile_result = await db.execute(
            select(AgentProfile).where(AgentProfile.is_active == True)
        )
        profiles = profile_result.scalars().all()
        # Try to match by alert category
        alert_cat = (alert.alert_category or "").lower()
        for p in profiles:
            kw_match = any(kw.lower() in alert_cat for kw in (p.match_keywords or []))
            if kw_match:
                matched_profile = p
                break
    except Exception:
        pass

    recipients = await resolve_recipients(db, alert, matched_mcp=matched_mcp, matched_profile=matched_profile)

    subject = f"[InfraAI] {parsed.get('risk_level', 'Alert')}: {alert.alertname}"
    html_body = _build_email_html(alert, parsed)

    # ── Dual-path: try Foundry notifier agent first ──
    if agent_config.foundry_agent_name:
        try:
            from app.services.azure_foundry_service import run_agent
            prompt_parts = [
                "Send an email notification for this infrastructure alert.",
                f"To: {', '.join(recipients['to'])}",
            ]
            if recipients.get("cc"):
                prompt_parts.append(f"CC: {', '.join(recipients['cc'])}")
            prompt_parts.extend([
                f"Subject: {subject}",
                f"Body (HTML):\n{html_body}",
            ])
            await run_agent(
                agent_config.foundry_agent_name,
                [{"role": "user", "content": "\n".join(prompt_parts)}],
                timeout=60.0,
            )
            logger.info("Notification sent via Foundry notifier agent")
            return {"success": True, "message": "Notification sent via Foundry agent"}
        except Exception as e:
            logger.warning(
                "Foundry notifier agent failed, falling back to Graph API: %s", e
            )

    # ── Fallback: direct Graph API email ──
    from app.services.azure_graph_service import send_outlook_email

    result = await send_outlook_email(
        to_list=recipients["to"],
        cc_list=recipients["cc"],
        subject=subject,
        html_body=html_body,
    )
    return result


# ── Helpers ──


def _alert_to_context(alert: Alert) -> dict:
    """Convert alert to a safe dict for prompt context."""
    return {
        "alertname": redact_text(alert.alertname or ""),
        "severity": alert.severity,
        "status": alert.status,
        "instance": redact_text(alert.instance or ""),
        "summary": redact_text(alert.summary or ""),
        "description": redact_text(alert.description or ""),
        "category": alert.alert_category or "general",
        "source": alert.source or "",
        "labels": redact_dict(alert.labels or {}),
    }


def _filter_pipeline(agents: list, alert_category: str, alert: Alert) -> tuple[list, list]:
    """Split applicable agents into workflow pipeline and technology specialists."""
    normalized_system_type = _normalize_system_type(alert_category, alert)
    workflow_agents = []
    specialist_agents = []

    for agent in agents:
        agent_line = (getattr(agent, "agent_line", None) or "workflow").lower()
        if agent_line == "technology":
            if _agent_matches_alert(agent, normalized_system_type, alert, strict_labels=True):
                specialist_agents.append(agent)
            continue

        if _agent_matches_alert(agent, normalized_system_type, alert, strict_labels=False):
            workflow_agents.append(agent)

    return workflow_agents, specialist_agents


def _agent_matches_alert(agent: FoundryAgentConfig, normalized_system_type: str, alert: Alert, strict_labels: bool) -> bool:
    """Check whether an agent should participate for this alert."""
    agent_system_type = (agent.system_type or "all").lower()
    if agent_system_type != "all" and agent_system_type != normalized_system_type:
        return False

    if not agent.trigger_labels:
        return True

    alert_labels = {k.lower(): str(v).lower() for k, v in (alert.labels or {}).items()}
    for key, values in agent.trigger_labels.items():
        key_lower = key.lower()
        if key_lower not in alert_labels:
            continue
        if isinstance(values, list):
            if alert_labels[key_lower] in [str(v).lower() for v in values]:
                return True
        elif alert_labels[key_lower] == str(values).lower():
            return True

    if strict_labels:
        return False

    return (agent.role or "").lower() in (
        "solver", "solution", "validation", "notifier", "knowledge", "triage_master"
    )


def _resolve_system_type(pipeline: list, alert: Alert) -> str:
    """Determine the most specific system type from the pipeline and alert context.

    Priority:
    1. Specific system_type from a matched pipeline agent (not 'all')
    2. alert_category if it maps to a known platform
    3. Heuristic from alert labels (e.g., job='oracle-exporter' -> oracle)
    4. Fallback to 'general'
    """
    # Check pipeline agents for a specific system_type
    for agent in pipeline:
        if agent.system_type and agent.system_type != "all":
            return agent.system_type

    # Check alert_category
    category = _normalize_system_type(alert.alert_category or "", alert)
    if category in ("oracle", "postgresql", "mysql", "sqlserver", "mongodb", "linux", "cloud", "kubernetes", "infrastructure"):
        return category

    # Heuristic: inspect alert labels for known patterns
    labels = {k.lower(): str(v).lower() for k, v in (alert.labels or {}).items()}
    label_text = " ".join(labels.values()) + " " + (alert.alertname or "").lower()

    if any(kw in label_text for kw in ("oracle", "ora-", "tablespace", "asm", "rman", "oracledb")):
        return "oracle"
    if any(kw in label_text for kw in ("postgres", "pg_", "postgresql", "pgbouncer")):
        return "postgresql"
    if any(kw in label_text for kw in ("mysql", "mariadb", "innodb")):
        return "mysql"
    if any(kw in label_text for kw in ("mssql", "sqlserver", "sql_server", "tsql")):
        return "sqlserver"
    if any(kw in label_text for kw in ("mongo", "mongodb", "replica_set")):
        return "mongodb"
    if any(kw in label_text for kw in ("aks", "eks", "gke", "kube_", "pod", "deployment", "namespace", "container")):
        return "kubernetes"
    if any(kw in label_text for kw in ("aws", "azure", "oci", "ec2", "app service", "rds", "vmss", "vnet", "load balancer")):
        return "cloud"
    if any(kw in label_text for kw in ("node_exporter", "cpu", "memory", "disk", "filesystem", "systemd", "linux", "kernel")):
        return "linux"
    if any(kw in label_text for kw in ("network", "dns", "tls", "ssl", "firewall", "latency", "packet", "tcp", "bgp", "vlan")):
        return "network"
    if any(kw in label_text for kw in ("security", "auth", "brute", "cve", "intrusion", "anomaly", "certificate", "privilege")):
        return "security"
    if any(kw in label_text for kw in ("jvm", "heap", "gc", "tomcat", "nginx", "apache", "iis", "gunicorn", "kafka", "application")):
        return "application"

    return "general"


def _normalize_system_type(alert_category: str, alert: Alert) -> str:
    """Normalize built-in alert categories to Foundry specialist domains."""
    category = (alert_category or "").lower().strip()
    mapping = {
        "oracle_db": "oracle",
        "oracle": "oracle",
        "postgresql": "postgresql",
        "mysql": "mysql",
        "sqlserver": "sqlserver",
        "mongodb": "mongodb",
        "linux_os": "linux",
        "os": "linux",
        "linux": "linux",
        "aws": "cloud",
        "azure": "cloud",
        "oci": "cloud",
        "cloud": "cloud",
        "k8s": "kubernetes",
        "kubernetes": "kubernetes",
        "network": "network",
        "security": "security",
        "application": "application",
        "app": "application",
        "infrastructure": "infrastructure",
        "general": "general",
    }
    if category in mapping:
        return mapping[category]

    labels = {k.lower(): str(v).lower() for k, v in (alert.labels or {}).items()}
    label_text = " ".join(labels.values()) + " " + (alert.alertname or "").lower()
    if any(kw in label_text for kw in ("aks", "eks", "gke", "kube_", "pod", "namespace")):
        return "kubernetes"
    if any(kw in label_text for kw in ("aws", "azure", "oci", "ec2", "vm", "rds", "app service")):
        return "cloud"
    if any(kw in label_text for kw in ("network", "dns", "tls", "firewall")):
        return "network"
    if any(kw in label_text for kw in ("security", "auth", "brute", "cve")):
        return "security"
    if any(kw in label_text for kw in ("jvm", "heap", "nginx", "kafka", "application")):
        return "application"
    return category or "general"


def _extract_queries_from_plan(plan_text: str) -> dict[str, str]:
    """Try to extract SQL queries from the researcher agent's output."""
    import re
    queries = {}
    # Try JSON extraction first
    try:
        json_match = re.search(r'\{[^}]*"queries"[^}]*\}', plan_text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            if "queries" in parsed:
                return {k: v for k, v in parsed["queries"].items() if isinstance(v, str)}
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: extract SQL from code blocks
    code_blocks = re.findall(r'```(?:sql)?\s*(SELECT[^`]+)```', plan_text, re.IGNORECASE | re.DOTALL)
    for i, sql in enumerate(code_blocks[:8]):
        queries[f"query_{i+1}"] = sql.strip().rstrip(";")

    return queries


def _parse_solver_response(text: str) -> dict:
    """Parse the solver agent's text response into a dict."""
    import re
    if not text:
        return {}
    # Try JSON extraction
    try:
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except (json.JSONDecodeError, AttributeError):
        pass
    # Fallback: return as root_cause text
    return {"root_cause": text, "confidence_score": 0.5, "action_plan": [], "risk_level": "Medium"}


def _mcp_to_tool_name(mcp_type: str) -> str | None:
    """Map MCP server_type to the registered tool name."""
    mapping = {
        "oracle": "oracle_sql",
        "sqlcl": "oracle_sql",
        "postgresql": "postgres_query",
        "mysql": "mysql_query",
        "sqlserver": "sqlserver_query",
        "mongodb": "mongodb_query",
        "slack": "slack_send",
        "prometheus": "prometheus_query",
    }
    return mapping.get(mcp_type)


def _default_queries_for_system_type(system_type: str) -> dict[str, str]:
    """Return default diagnostic queries for each database type."""
    if system_type in ("oracle", "sqlcl"):
        return {
            "tablespace_usage": "SELECT tablespace_name, SUM(bytes)/1024/1024 AS mb_used FROM dba_data_files GROUP BY tablespace_name",
            "free_space": "SELECT tablespace_name, SUM(bytes)/1024/1024 AS mb_free FROM dba_free_space GROUP BY tablespace_name",
            "sessions": "SELECT status, COUNT(*) FROM v$session GROUP BY status",
        }
    elif system_type == "postgresql":
        return {
            "active_connections": "SELECT state, COUNT(*) FROM pg_stat_activity GROUP BY state",
            "locks": "SELECT pid, relation::regclass, mode, granted FROM pg_locks WHERE NOT granted",
            "db_size": "SELECT pg_database_size(current_database())/1024/1024 AS mb_size",
            "long_running": "SELECT pid, now()-query_start AS duration, state, query FROM pg_stat_activity WHERE state != 'idle' AND now()-query_start > interval '1 minute'",
        }
    elif system_type == "mysql":
        return {
            "connections": "SHOW STATUS LIKE 'Threads_connected'",
            "processlist": "SELECT id, user, host, db, command, time, state FROM information_schema.processlist",
            "innodb_status": "SHOW ENGINE INNODB STATUS",
            "slow_queries": "SHOW GLOBAL STATUS LIKE 'Slow_queries'",
            "db_size": "SELECT table_schema AS db_name, ROUND(SUM(data_length + index_length)/1024/1024, 2) AS size_mb FROM information_schema.tables GROUP BY table_schema",
        }
    elif system_type == "mongodb":
        return {
            "server_status": "db.serverStatus()",
            "current_ops": "db.currentOp()",
            "collection_stats": "db.getCollectionNames().map(function(c) { return {name: c, stats: db.getCollection(c).stats()} })",
            "replication_status": "rs.status()",
        }
    elif system_type == "sqlserver":
        return {
            "active_sessions": "SELECT session_id, status, cpu_time, memory_usage, login_name FROM sys.dm_exec_sessions WHERE is_user_process = 1",
            "blocking": "SELECT session_id, blocking_session_id, wait_time, wait_type FROM sys.dm_exec_requests WHERE blocking_session_id > 0",
            "db_size": "SELECT DB_NAME(database_id) AS db_name, CAST(SUM(size)*8/1024 AS DECIMAL(10,2)) AS size_mb FROM sys.master_files GROUP BY database_id",
        }
    return {}


def _build_email_html(alert: Alert, analysis: dict) -> str:
    """Build HTML email body for the notification."""
    action_items = "".join(
        f"<li style='margin:4px 0;'>{s}</li>" for s in analysis.get("action_plan", [])
    )
    return f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
  <div style="background:#0B3D91;padding:16px 24px;">
    <h2 style="color:#fff;margin:0;">InfraAI Agent</h2>
    <p style="color:#90CAF9;margin:4px 0 0;">Azure AI Foundry Analysis</p>
  </div>
  <div style="padding:24px;border:1px solid #e0e0e0;border-top:none;">
    <h3 style="color:#0B3D91;">{alert.alertname}</h3>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;">
      <tr><td style="padding:8px;font-weight:bold;">Risk Level</td><td style="padding:8px;">{analysis.get('risk_level','Unknown')}</td></tr>
      <tr><td style="padding:8px;font-weight:bold;">Confidence</td><td style="padding:8px;">{analysis.get('confidence_score','N/A')}</td></tr>
      <tr><td style="padding:8px;font-weight:bold;">Severity</td><td style="padding:8px;">{alert.severity}</td></tr>
      <tr><td style="padding:8px;font-weight:bold;">Instance</td><td style="padding:8px;">{alert.instance or 'N/A'}</td></tr>
    </table>
    {"<h4>What's Happening</h4><p>" + analysis.get('problem_statement','') + "</p>" if analysis.get('problem_statement') else ""}
    <h4 style="color:#333;">Root Cause</h4>
    <p>{analysis.get('root_cause','Unknown')}</p>
    <h4 style="color:#333;">Action Plan</h4>
    <ol>{action_items}</ol>
    <h4 style="color:#333;">Prevention</h4>
    <p>{analysis.get('prevention_steps','N/A')}</p>
  </div>
</div>
"""
