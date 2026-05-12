from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid as _uuid
import logging
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.config import settings
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


async def require_operator(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator access required")
    return current_user


async def get_or_create_sso_user(
    db: AsyncSession,
    email: str,
    full_name: str,
    idp_id: _uuid.UUID,
    subject_id: str,
    groups: list[str],
    idp,  # IdentityProvider instance
    auth_source: str = "oidc",
) -> User:
    """Find or create a user from an SSO login.

    JIT (Just-In-Time) provisioning: if the user doesn't exist and
    ``idp.auto_provision`` is True, create one with the IDP's default role.

    Group → role mapping: if ``idp.group_role_mapping`` is set and the user
    doesn't have ``role_override=True``, update their role based on the
    highest-priority matching group.
    """
    # 1. Try by IDP subject ID (most reliable)
    result = await db.execute(
        select(User).where(
            and_(User.idp_id == idp_id, User.idp_subject_id == subject_id)
        )
    )
    user = result.scalar_one_or_none()

    # 2. Fallback: match by email (link existing local user to IDP)
    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            # Link existing user to this IDP
            user.idp_id = idp_id
            user.idp_subject_id = subject_id
            user.auth_source = auth_source
            logger.info("Linked existing user %s to IDP %s", email, idp.name)

    # 3. JIT provision
    if not user:
        if not idp.auto_provision:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not provisioned. Contact your administrator.",
            )
        user = User(
            email=email,
            full_name=full_name,
            hashed_password=None,
            role=idp.default_role or "viewer",
            is_active=True,
            auth_source=auth_source,
            idp_id=idp_id,
            idp_subject_id=subject_id,
            role_override=False,
        )
        db.add(user)
        await db.flush()
        logger.info("JIT provisioned user %s from IDP %s", email, idp.name)

    # 4. Update name if it changed at the IDP
    if full_name and user.full_name != full_name:
        user.full_name = full_name

    # 5. Apply group → role mapping (unless admin has overridden)
    if not user.role_override and idp.group_role_mapping and groups:
        role_priority = {"admin": 3, "operator": 2, "viewer": 1}
        best_role = None
        best_priority = 0
        for group in groups:
            mapped_role = idp.group_role_mapping.get(group)
            if mapped_role and role_priority.get(mapped_role, 0) > best_priority:
                best_role = mapped_role
                best_priority = role_priority[mapped_role]
        if best_role and user.role != best_role:
            logger.info("IDP group mapping: %s role %s → %s", email, user.role, best_role)
            user.role = best_role

    # 6. Sync IDP groups
    from app.models.idp import UserIdpGroup
    # Delete old group memberships for this IDP
    from sqlalchemy import delete
    await db.execute(
        delete(UserIdpGroup).where(
            and_(UserIdpGroup.user_id == user.id, UserIdpGroup.idp_id == idp_id)
        )
    )
    for group_name in groups:
        db.add(UserIdpGroup(user_id=user.id, idp_id=idp_id, group_name=group_name))

    await db.flush()
    await db.refresh(user)
    return user
