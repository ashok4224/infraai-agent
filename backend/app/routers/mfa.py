"""MFA management endpoints — enable/disable, verify OTP, resend, role enforcement."""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.rbac import AppRole
from app.schemas.mfa import (
    MfaVerifyRequest,
    MfaStatusResponse,
    MfaEnableRequest,
    MfaRoleEnforceRequest,
)
from app.schemas.user import Token
from app.auth.jwt_handler import (
    get_current_user,
    require_admin,
    create_access_token,
)
from app.services.mfa_service import (
    decode_mfa_token,
    verify_otp,
    create_and_send_otp,
    is_mfa_enforced_by_role,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory rate limiter for MFA verify attempts: {mfa_token_hash: (count, first_attempt_time)}
_verify_attempts: dict[str, tuple[int, float]] = {}
_MAX_VERIFY_ATTEMPTS = 5
_VERIFY_WINDOW_SECONDS = 300  # 5 minutes


def _check_rate_limit(mfa_token: str) -> None:
    """Block after too many failed OTP attempts for the same MFA session."""
    import hashlib
    import time

    key = hashlib.sha256(mfa_token.encode()).hexdigest()[:16]
    now = time.time()

    # Clean up expired entries
    expired = [k for k, (_, t) in _verify_attempts.items() if now - t > _VERIFY_WINDOW_SECONDS]
    for k in expired:
        del _verify_attempts[k]

    count, first_time = _verify_attempts.get(key, (0, now))
    if now - first_time > _VERIFY_WINDOW_SECONDS:
        count, first_time = 0, now

    if count >= _MAX_VERIFY_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many verification attempts. Please request a new code.",
        )

    _verify_attempts[key] = (count + 1, first_time)


# ── Verify OTP (public — uses mfa_token, not bearer) ────────────────────────

@router.post("/verify", response_model=Token)
async def mfa_verify(
    payload: MfaVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify OTP code and return a full access token."""
    # Rate limit: max 5 attempts per MFA session within 5 minutes
    _check_rate_limit(payload.mfa_token)

    try:
        mfa_payload = decode_mfa_token(payload.mfa_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user_id = mfa_payload["sub"]
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    valid = await verify_otp(db, user.id, payload.otp_code)
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid or expired OTP code")

    token = create_access_token(
        data={"sub": str(user.id), "role": user.role, "email": user.email}
    )
    return Token(access_token=token)


# ── Resend OTP (public — uses mfa_token) ─────────────────────────────────────

# Rate limiter for resend: {mfa_token_hash: last_resend_time}
_resend_cooldown: dict[str, float] = {}
_RESEND_COOLDOWN_SECONDS = 30


@router.post("/resend")
async def mfa_resend(
    mfa_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Resend OTP code to the user's email."""
    import hashlib
    import time

    # Resend cooldown: 30 seconds between resends
    key = hashlib.sha256(mfa_token.encode()).hexdigest()[:16]
    now = time.time()
    last = _resend_cooldown.get(key, 0)
    if now - last < _RESEND_COOLDOWN_SECONDS:
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {int(_RESEND_COOLDOWN_SECONDS - (now - last))} seconds before resending",
        )
    _resend_cooldown[key] = now

    try:
        mfa_payload = decode_mfa_token(mfa_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user_id = mfa_payload["sub"]
    email = mfa_payload["email"]

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    await create_and_send_otp(db, user.id, email)
    return {"message": "OTP code resent to your email"}


# ── Self-service: current user MFA status ────────────────────────────────────

@router.get("/status", response_model=MfaStatusResponse)
async def mfa_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get MFA status for the current user."""
    enforced = await is_mfa_enforced_by_role(db, current_user.id)
    return MfaStatusResponse(
        mfa_enabled=current_user.mfa_enabled,
        enforced_by_role=enforced,
        enforced=current_user.mfa_enabled or enforced,
    )


# ── Self-service: enable/disable own MFA ─────────────────────────────────────

@router.post("/enable")
async def mfa_self_enable(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable MFA for the current user."""
    current_user.mfa_enabled = True
    await db.flush()
    return {"message": "MFA enabled for your account"}


@router.post("/disable")
async def mfa_self_disable(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable MFA for the current user (unless enforced by role)."""
    enforced = await is_mfa_enforced_by_role(db, current_user.id)
    if enforced:
        raise HTTPException(
            status_code=400,
            detail="MFA is enforced by your assigned role and cannot be disabled",
        )
    current_user.mfa_enabled = False
    await db.flush()
    return {"message": "MFA disabled for your account"}


# ── Admin: manage MFA for any user ───────────────────────────────────────────

@router.patch("/users/{user_id}")
async def admin_set_user_mfa(
    user_id: UUID,
    payload: MfaEnableRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Admin: enable or disable MFA for a specific user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.mfa_enabled = payload.enabled
    await db.flush()
    return {"message": f"MFA {'enabled' if payload.enabled else 'disabled'} for {user.email}"}


# ── Admin: manage MFA enforcement on roles ───────────────────────────────────

@router.patch("/roles/{role_id}")
async def admin_set_role_mfa(
    role_id: UUID,
    payload: MfaRoleEnforceRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Admin: set MFA enforcement on a role. All users with this role will require MFA."""
    result = await db.execute(select(AppRole).where(AppRole.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    role.mfa_required = payload.mfa_required
    await db.flush()
    return {
        "message": f"MFA {'enforced' if payload.mfa_required else 'no longer enforced'} for role '{role.name}'"
    }
