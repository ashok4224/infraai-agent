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
