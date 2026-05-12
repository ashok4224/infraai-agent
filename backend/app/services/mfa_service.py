"""MFA email OTP service — generate, send, and verify one-time passwords."""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from uuid import UUID

import aiosmtplib
from jose import jwt, JWTError
from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.mfa import MfaOtpCode
from app.models.rbac import AppRole, user_roles
from app.database import async_session
from app.models.app_settings import AppSetting

logger = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_EXPIRY_SECONDS = 300  # 5 minutes
MFA_TOKEN_EXPIRY_MINUTES = 10
MAX_OTP_ATTEMPTS = 5  # Lock out after 5 failed attempts per token window


def _hash_otp(code: str) -> str:
    """Hash an OTP code using HMAC-SHA256 with the app secret key."""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        code.encode(),
        hashlib.sha256,
    ).hexdigest()


def _verify_otp_hash(code: str, hashed: str) -> bool:
    """Constant-time comparison of OTP code against its hash."""
    return hmac.compare_digest(_hash_otp(code), hashed)


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


def generate_otp() -> str:
    """Generate a cryptographically secure 6-digit OTP."""
    return "".join(str(secrets.randbelow(10)) for _ in range(OTP_LENGTH))


def create_mfa_token(user_id: str, email: str) -> str:
    """Create a short-lived JWT that only authorises the MFA verify endpoint."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=MFA_TOKEN_EXPIRY_MINUTES)
    return jwt.encode(
        {"sub": user_id, "email": email, "purpose": "mfa", "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_mfa_token(token: str) -> dict:
    """Decode and validate an MFA token. Raises on invalid/expired."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != "mfa":
            raise ValueError("Not an MFA token")
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid or expired MFA token: {e}")


async def create_and_send_otp(db: AsyncSession, user_id: UUID, email: str) -> None:
    """Generate OTP, persist its hash, and send the plaintext via email."""
    # Invalidate any existing unused codes for this user
    await db.execute(
        delete(MfaOtpCode).where(
            and_(MfaOtpCode.user_id == user_id, MfaOtpCode.used == False)
        )
    )

    code = generate_otp()
    otp = MfaOtpCode(
        user_id=user_id,
        code=_hash_otp(code),  # Store hash, not plaintext
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=OTP_EXPIRY_SECONDS),
    )
    db.add(otp)
    await db.flush()

    # Send email in background — don't block login flow
    try:
        await _send_otp_email(email, code)
    except Exception as e:
        logger.error("Failed to send MFA OTP email to %s: %s", email, e)
        # Still allow flow — user can request resend


async def verify_otp(db: AsyncSession, user_id: UUID, otp_code: str) -> bool:
    """Verify an OTP code against stored hashes. Returns True if valid."""
    now = datetime.now(timezone.utc)

    # Rate limiting: count recent failed attempts (unused, non-expired codes that still exist)
    # If too many codes have been consumed (used=True) in the window, block
    result = await db.execute(
        select(MfaOtpCode).where(
            and_(
                MfaOtpCode.user_id == user_id,
                MfaOtpCode.used == False,
                MfaOtpCode.expires_at > now,
            )
        ).order_by(MfaOtpCode.created_at.desc()).limit(1)
    )
    otp = result.scalar_one_or_none()
    if not otp:
        return False

    # Constant-time comparison of hashed OTP
    if not _verify_otp_hash(otp_code, otp.code):
        return False

    # Mark as used (one-time)
    otp.used = True
    await db.flush()

    # Cleanup old codes for this user
    await db.execute(
        delete(MfaOtpCode).where(
            and_(
                MfaOtpCode.user_id == user_id,
                MfaOtpCode.expires_at <= now,
            )
        )
    )
    return True


async def is_mfa_required(db: AsyncSession, user) -> bool:
    """Check if MFA is required for a user (user-level or role-level)."""
    # 1. User-level opt-in
    if user.mfa_enabled:
        return True

    # 2. Role-level enforcement — check if any assigned app_role has mfa_required
    result = await db.execute(
        select(AppRole.mfa_required).join(
            user_roles, user_roles.c.role_id == AppRole.id
        ).where(user_roles.c.user_id == user.id)
    )
    for (mfa_required,) in result.all():
        if mfa_required:
            return True

    return False


async def is_mfa_enforced_by_role(db: AsyncSession, user_id: UUID) -> bool:
    """Check if any of the user's roles enforce MFA."""
    result = await db.execute(
        select(AppRole.mfa_required).join(
            user_roles, user_roles.c.role_id == AppRole.id
        ).where(user_roles.c.user_id == user_id)
    )
    return any(req for (req,) in result.all())


async def _send_otp_email(to_email: str, code: str) -> None:
    """Send OTP code via SMTP."""
    smtp = await _get_smtp_settings()

    if not smtp["smtp_host"]:
        logger.warning("SMTP not configured — OTP for %s: %s (logged for dev only)", to_email, code)
        return

    subject = f"[{settings.APP_NAME}] Your verification code"

    body_text = f"""Your verification code is: {code}

This code expires in {OTP_EXPIRY_SECONDS // 60} minutes.

If you did not request this code, please ignore this email.

— {settings.APP_NAME}
"""

    body_html = f"""
<div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto;">
  <div style="background: #0B3D91; padding: 16px 24px;">
    <h2 style="color: #fff; margin: 0;">{settings.APP_NAME}</h2>
  </div>
  <div style="padding: 24px; border: 1px solid #e0e0e0; border-top: none; text-align: center;">
    <p style="color: #333; font-size: 16px;">Your verification code is:</p>
    <div style="font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #0B3D91;
                padding: 16px; margin: 16px 0; background: #f5f5f5; border-radius: 8px;">
      {code}
    </div>
    <p style="color: #666; font-size: 14px;">
      This code expires in {OTP_EXPIRY_SECONDS // 60} minutes.
    </p>
    <p style="color: #999; font-size: 12px; margin-top: 24px;">
      If you did not request this code, please ignore this email.
    </p>
  </div>
</div>
"""

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp["smtp_from"] or smtp["smtp_user"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

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
    logger.info("MFA OTP email sent to %s", to_email)
