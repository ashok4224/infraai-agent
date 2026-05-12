"""Email notification service using aiosmtplib — reads SMTP config from database."""
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.app_settings import AppSetting

logger = logging.getLogger(__name__)


async def _get_smtp_settings() -> dict:
    """Read SMTP settings from database, fall back to env vars."""
    smtp = {
        "smtp_host": settings.SMTP_HOST,
        "smtp_port": str(settings.SMTP_PORT),
        "smtp_user": settings.SMTP_USER,
        "smtp_password": settings.SMTP_PASSWORD,
        "smtp_from": settings.SMTP_FROM,
        "smtp_use_tls": "true",
    }
    try:
        async with async_session() as db:
            for key in smtp:
                result = await db.execute(select(AppSetting).where(AppSetting.key == key))
                row = result.scalar_one_or_none()
                if row and row.value:
                    smtp[key] = row.value
    except Exception as e:
        logger.debug("Could not read SMTP settings from DB, using env vars: %s", e)
    return smtp


async def send_action_plan_email(
    to_email: str,
    alert_name: str,
    alert_id: str,
    analysis: dict,
):
    """Send an action plan email for an analyzed alert."""
    smtp = await _get_smtp_settings()

    if not smtp["smtp_user"]:
        logger.warning("SMTP not configured — skipping email for alert %s", alert_id)
        return

    subject = f"[InfraAI] Action Plan: {alert_name}"

    action_steps = "\n".join(f"  {i+1}. {step}" for i, step in enumerate(analysis.get("action_plan", [])))

    body_text = f"""InfraAI Agent — Action Plan
{'='*50}

Alert: {alert_name}
Risk Level: {analysis.get('risk_level', 'Unknown')}
Confidence: {analysis.get('confidence_score', 'N/A')}

Root Cause:
  {analysis.get('root_cause', 'Unknown')}

Action Plan:
{action_steps}

Prevention:
  {analysis.get('prevention_steps', 'N/A')}

View full details:
  {settings.CORS_ORIGINS.split(',')[0]}/alerts/{alert_id}

— InfraAI Agent by Winfo Solutions
"""

    body_html = f"""
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
  <div style="background: #0B3D91; padding: 16px 24px;">
    <h2 style="color: #fff; margin: 0;">InfraAI Agent</h2>
    <p style="color: #90CAF9; margin: 4px 0 0;">by Winfo Solutions</p>
  </div>
  <div style="padding: 24px; border: 1px solid #e0e0e0; border-top: none;">
    <h3 style="color: #0B3D91;">Action Plan: {alert_name}</h3>
    <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
      <tr><td style="padding: 8px; font-weight: bold;">Risk Level</td><td style="padding: 8px;">{analysis.get('risk_level', 'Unknown')}</td></tr>
      <tr><td style="padding: 8px; font-weight: bold;">Confidence</td><td style="padding: 8px;">{analysis.get('confidence_score', 'N/A')}</td></tr>
    </table>
    <h4 style="color: #333;">Root Cause</h4>
    <p>{analysis.get('root_cause', 'Unknown')}</p>
    <h4 style="color: #333;">Action Plan</h4>
    <ol>{''.join(f'<li style="margin: 4px 0;">{s}</li>' for s in analysis.get('action_plan', []))}</ol>
    <h4 style="color: #333;">Prevention</h4>
    <p>{analysis.get('prevention_steps', 'N/A')}</p>
    <a href="{settings.CORS_ORIGINS.split(',')[0]}/alerts/{alert_id}"
       style="display: inline-block; background: #0B3D91; color: #fff; padding: 10px 24px; text-decoration: none; border-radius: 4px; margin-top: 16px;">
      View Full Details
    </a>
  </div>
</div>
"""

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp["smtp_from"] or smtp["smtp_user"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

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
        logger.info("Action plan email sent for alert %s", alert_id)
    except Exception as e:
        logger.error("Failed to send email for alert %s: %s", alert_id, e)
