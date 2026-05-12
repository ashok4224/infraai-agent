"""MFA-related Pydantic schemas."""
from pydantic import BaseModel, EmailStr
from typing import Optional


class MfaVerifyRequest(BaseModel):
    """Submit OTP code to complete MFA login."""
    mfa_token: str
    otp_code: str


class MfaLoginResponse(BaseModel):
    """Returned when MFA is required after successful password auth."""
    mfa_required: bool = True
    mfa_token: str
    message: str = "OTP code sent to your email"


class MfaStatusResponse(BaseModel):
    """Current MFA status for a user."""
    mfa_enabled: bool
    enforced_by_role: bool  # True if any assigned role requires MFA
    enforced: bool  # True if MFA is active (user-level OR role-level)


class MfaEnableRequest(BaseModel):
    """Admin can enable/disable MFA for a specific user."""
    enabled: bool


class MfaRoleEnforceRequest(BaseModel):
    """Admin sets MFA enforcement on a role."""
    mfa_required: bool
