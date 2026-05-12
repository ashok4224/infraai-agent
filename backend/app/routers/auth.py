from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.schemas.user import Token, LoginRequest, UserResponse, UserCreate
from app.auth.jwt_handler import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
)
from app.services.mfa_service import (
    is_mfa_required,
    create_mfa_token,
    create_and_send_otp,
)
from app.models.app_settings import AppSetting

router = APIRouter()


async def _is_local_auth_enabled(db: AsyncSession) -> bool:
    """Check if local (password) authentication is enabled."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == "auth_local_enabled"))
    row = result.scalar_one_or_none()
    if row and row.value:
        return row.value.lower() in ("true", "1", "yes")
    return True  # default enabled


@router.post("/login", response_model=Token)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    if not await _is_local_auth_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Local authentication is disabled. Please use SSO.",
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    # ── MFA check ─────────────────────────────────────────────────────────
    if await is_mfa_required(db, user):
        mfa_token = create_mfa_token(str(user.id), user.email)
        await create_and_send_otp(db, user.id, user.email)
        return Token(
            access_token="",
            mfa_required=True,
            mfa_token=mfa_token,
        )

    token = create_access_token(data={"sub": str(user.id), "role": user.role, "email": user.email})
    return Token(access_token=token)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    if not await _is_local_auth_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Local registration is disabled. Please contact your administrator.",
        )

    # Check if self-registration is allowed (default: disabled for security)
    reg_result = await db.execute(select(AppSetting).where(AppSetting.key == "auth_registration_enabled"))
    reg_setting = reg_result.scalar_one_or_none()
    if not reg_setting or reg_setting.value.lower() not in ("true", "1", "yes"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-registration is disabled. Please contact your administrator.",
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=get_password_hash(payload.password),
        role="viewer",  # self-registration always viewer
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
