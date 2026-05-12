"""App settings router — SMTP, notification preferences, general config."""
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.app_settings import AppSetting
from app.schemas.app_settings import (
    AppSettingResponse,
    AppSettingsBulkUpdate,
    SMTPTestRequest,
)
from app.auth.jwt_handler import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Default settings seeded on first load ──
DEFAULT_SETTINGS = [
    # SMTP
    {"key": "smtp_host", "value": "", "category": "smtp", "description": "SMTP server hostname", "is_secret": "false"},
    {"key": "smtp_port", "value": "587", "category": "smtp", "description": "SMTP server port", "is_secret": "false"},
    {"key": "smtp_user", "value": "", "category": "smtp", "description": "SMTP username / email", "is_secret": "false"},
    {"key": "smtp_password", "value": "", "category": "smtp", "description": "SMTP password or app password", "is_secret": "true"},
    {"key": "smtp_from", "value": "noreply@winfosolutions.com", "category": "smtp", "description": "From email address", "is_secret": "false"},
    {"key": "smtp_use_tls", "value": "true", "category": "smtp", "description": "Use STARTTLS", "is_secret": "false"},
    # Notifications
    {"key": "notify_on_critical", "value": "true", "category": "notifications", "description": "Send email on critical alerts", "is_secret": "false"},
    {"key": "notify_on_warning", "value": "false", "category": "notifications", "description": "Send email on warning alerts", "is_secret": "false"},
    {"key": "notify_recipients", "value": "", "category": "notifications", "description": "Comma-separated email recipients for notifications", "is_secret": "false"},
    # General
    {"key": "app_name", "value": "InfraAI Agent", "category": "general", "description": "Application display name", "is_secret": "false"},
    {"key": "cors_origins", "value": "http://localhost:5173,http://localhost:3000", "category": "general", "description": "Allowed CORS origins (comma-separated)", "is_secret": "false"},
    {"key": "alert_retention_days", "value": "90", "category": "general", "description": "Days to keep resolved alerts", "is_secret": "false"},
    {"key": "auto_analyze", "value": "true", "category": "general", "description": "Automatically analyze incoming alerts with AI", "is_secret": "false"},
    {"key": "ai_mode", "value": "builtin", "category": "general", "description": "AI analysis mode: builtin or azure_foundry", "is_secret": "false"},
    # Webhook / Integration
    {"key": "webhook_secret", "value": "", "category": "integrations", "description": "Optional secret token for webhook authentication", "is_secret": "true"},
    {"key": "slack_webhook_url", "value": "", "category": "integrations", "description": "Slack incoming webhook URL for notifications", "is_secret": "true"},
    {"key": "teams_webhook_url", "value": "", "category": "integrations", "description": "Microsoft Teams webhook URL for notifications", "is_secret": "true"},
    # Authentication
    {"key": "auth_local_enabled", "value": "true", "category": "auth", "description": "Allow local username/password login (disable to force SSO)", "is_secret": "false"},
    # MFA
    {"key": "mfa_otp_expiry_seconds", "value": "300", "category": "auth", "description": "OTP code expiry time in seconds", "is_secret": "false"},
    # RAG / Knowledge Base
    {"key": "rag_enabled", "value": "false", "category": "rag", "description": "Enable RAG knowledge base for AI-enhanced analysis and chat", "is_secret": "false"},
    {"key": "rag_embedding_model", "value": "text-embedding-3-small", "category": "rag", "description": "Embedding model for vectorization (text-embedding-3-small or text-embedding-3-large)", "is_secret": "false"},
    {"key": "rag_chunk_size", "value": "500", "category": "rag", "description": "Target chunk size in tokens for document splitting", "is_secret": "false"},
    {"key": "rag_chunk_overlap", "value": "50", "category": "rag", "description": "Overlap tokens between consecutive chunks", "is_secret": "false"},
    {"key": "rag_top_k", "value": "5", "category": "rag", "description": "Number of top chunks to retrieve per search query", "is_secret": "false"},
    {"key": "rag_score_threshold", "value": "0.7", "category": "rag", "description": "Minimum cosine similarity score for chunk retrieval (0.0-1.0)", "is_secret": "false"},
]


async def seed_settings(db: AsyncSession):
    """Seed default settings if they don't exist."""
    for default in DEFAULT_SETTINGS:
        result = await db.execute(select(AppSetting).where(AppSetting.key == default["key"]))
        if not result.scalar_one_or_none():
            db.add(AppSetting(**default))
    await db.commit()


def _mask_setting(s: AppSetting) -> dict:
    """Mask secret values in responses."""
    return {
        "key": s.key,
        "value": "••••••••" if s.is_secret == "true" and s.value else s.value,
        "category": s.category,
        "description": s.description,
        "is_secret": s.is_secret,
    }


@router.get("/", response_model=list[AppSettingResponse])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Get all app settings (secrets are masked)."""
    await seed_settings(db)
    result = await db.execute(select(AppSetting).order_by(AppSetting.category, AppSetting.key))
    settings = result.scalars().all()
    return [_mask_setting(s) for s in settings]


@router.put("/", response_model=list[AppSettingResponse])
async def update_settings_bulk(
    payload: AppSettingsBulkUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Update multiple settings at once. Skips empty values for secrets (keeps current)."""
    for key, value in payload.settings.items():
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()
        if not setting:
            continue
        # Don't overwrite secret with blank/masked value
        if setting.is_secret == "true" and (not value or value == "••••••••"):
            continue
        setting.value = value
    await db.commit()

    # Return updated list
    result = await db.execute(select(AppSetting).order_by(AppSetting.category, AppSetting.key))
    settings = result.scalars().all()
    return [_mask_setting(s) for s in settings]


@router.post("/test-smtp")
async def test_smtp(
    payload: SMTPTestRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Send a test email using current SMTP settings."""
    # Read SMTP settings from DB
    smtp_keys = ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from", "smtp_use_tls"]
    smtp = {}
    for key in smtp_keys:
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        smtp[key] = row.value if row else ""

    if not smtp["smtp_host"] or not smtp["smtp_user"]:
        raise HTTPException(status_code=400, detail="SMTP host and user must be configured first")

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp["smtp_from"] or smtp["smtp_user"]
    msg["To"] = payload.to_email
    msg["Subject"] = "[InfraAI Agent] SMTP Test"
    msg.attach(MIMEText("This is a test email from InfraAI Agent.\n\nSMTP configuration is working correctly.", "plain"))
    msg.attach(MIMEText("""
<div style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto;">
  <div style="background: #0B3D91; padding: 16px 24px;">
    <h2 style="color: #fff; margin: 0;">InfraAI Agent</h2>
    <p style="color: #90CAF9; margin: 4px 0 0; font-size: 11px;">by Winfo Solutions</p>
  </div>
  <div style="padding: 24px; border: 1px solid #e0e0e0; border-top: none;">
    <h3 style="color: #0B3D91;">SMTP Test Successful</h3>
    <p>Your SMTP configuration is working correctly. InfraAI Agent can now send email notifications for alert action plans.</p>
  </div>
</div>
""", "html"))

    try:
        use_tls = smtp["smtp_use_tls"].lower() == "true"
        await aiosmtplib.send(
            msg,
            hostname=smtp["smtp_host"],
            port=int(smtp["smtp_port"] or 587),
            username=smtp["smtp_user"],
            password=smtp["smtp_password"],
            use_tls=False,
            start_tls=use_tls,
        )
        return {"success": True, "message": f"Test email sent to {payload.to_email}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SMTP test failed: {str(e)}")


@router.post("/test-slack")
async def test_slack(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Send a test message to the configured Slack webhook."""
    import httpx

    result = await db.execute(select(AppSetting).where(AppSetting.key == "slack_webhook_url"))
    row = result.scalar_one_or_none()
    if not row or not row.value:
        raise HTTPException(status_code=400, detail="Slack webhook URL is not configured")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(row.value, json={
                "text": ":white_check_mark: *InfraAI Agent* — Slack integration test successful!"
            })
            if resp.status_code == 200:
                return {"success": True, "message": "Test message sent to Slack"}
            raise HTTPException(status_code=400, detail=f"Slack returned HTTP {resp.status_code}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Slack test failed: {str(e)}")


@router.post("/test-teams")
async def test_teams(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Send a test message to the configured Teams webhook."""
    import httpx

    result = await db.execute(select(AppSetting).where(AppSetting.key == "teams_webhook_url"))
    row = result.scalar_one_or_none()
    if not row or not row.value:
        raise HTTPException(status_code=400, detail="Teams webhook URL is not configured")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(row.value, json={
                "text": "✅ **InfraAI Agent** — Teams integration test successful!"
            })
            if resp.status_code == 200:
                return {"success": True, "message": "Test message sent to Teams"}
            raise HTTPException(status_code=400, detail=f"Teams returned HTTP {resp.status_code}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Teams test failed: {str(e)}")


@router.get("/keyvault/status")
async def keyvault_status(
    _user: User = Depends(require_admin),
):
    """Check Azure Key Vault connectivity status."""
    from app.services.keyvault_service import keyvault_service
    return keyvault_service.test_connection()


@router.post("/keyvault/test")
async def keyvault_test(
    _user: User = Depends(require_admin),
):
    """Write and read a test secret to verify Key Vault end-to-end."""
    from app.services.keyvault_service import keyvault_service

    if not keyvault_service.enabled:
        raise HTTPException(status_code=400, detail="Key Vault is not enabled. Set AZURE_KEY_VAULT_URL.")

    import uuid
    test_name = f"infraai-test-{uuid.uuid4().hex[:8]}"
    test_value = f"test-{uuid.uuid4().hex[:8]}"

    ref = keyvault_service.store_secret(test_name, test_value)
    if not ref:
        raise HTTPException(status_code=500, detail="Failed to write test secret to Key Vault")

    retrieved = keyvault_service.get_secret(ref)
    if retrieved != test_value:
        raise HTTPException(status_code=500, detail="Failed to read test secret from Key Vault")

    # Clean up
    keyvault_service.delete_secret(ref)

    return {"success": True, "message": "Key Vault read/write test passed", "vault_url": keyvault_service._vault_url}
