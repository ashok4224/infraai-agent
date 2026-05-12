"""Notification resolver — determines email recipients for an alert."""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_config import MCPServerConfig
from app.models.agent_profile import AgentProfile
from app.models.app_settings import AppSetting
from app.config import settings

logger = logging.getLogger(__name__)


async def resolve_recipients(
    db: AsyncSession,
    alert,
    matched_mcp: MCPServerConfig | None = None,
    matched_profile: AgentProfile | None = None,
) -> dict:
    """Resolve email recipients for an alert.

    Priority chain:
    1. MCP server config (per-database) — notification_emails / notification_cc
    2. Agent profile (per-category) — notification_emails / notification_cc
    3. App setting: notify_recipients (global)
    4. Config: ADMIN_EMAIL (last resort)

    Returns: {"to": [...], "cc": [...]}
    """
    to_emails: list[str] = []
    cc_emails: list[str] = []

    # 1. Per-database recipients from MCP config
    if matched_mcp:
        mcp_to = getattr(matched_mcp, "notification_emails", None) or []
        mcp_cc = getattr(matched_mcp, "notification_cc", None) or []
        if mcp_to:
            to_emails.extend(mcp_to)
            cc_emails.extend(mcp_cc)

    # 2. Per-category recipients from agent profile
    if not to_emails and matched_profile:
        profile_to = getattr(matched_profile, "notification_emails", None) or []
        profile_cc = getattr(matched_profile, "notification_cc", None) or []
        if profile_to:
            to_emails.extend(profile_to)
            cc_emails.extend(profile_cc)

    # 3. Global notify_recipients setting
    if not to_emails:
        try:
            result = await db.execute(
                select(AppSetting).where(AppSetting.key == "notify_recipients")
            )
            setting = result.scalar_one_or_none()
            if setting and setting.value:
                to_emails.extend(
                    e.strip() for e in setting.value.split(",") if e.strip()
                )
        except Exception:
            pass

    # 4. Fall back to admin email
    if not to_emails:
        to_emails.append(settings.ADMIN_EMAIL)

    # Deduplicate while preserving order
    seen_to = set()
    unique_to = []
    for e in to_emails:
        if e not in seen_to:
            seen_to.add(e)
            unique_to.append(e)

    seen_cc = set()
    unique_cc = []
    for e in cc_emails:
        if e not in seen_cc and e not in seen_to:
            seen_cc.add(e)
            unique_cc.append(e)

    return {"to": unique_to, "cc": unique_cc}
