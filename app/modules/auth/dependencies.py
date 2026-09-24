from typing import Any, Callable, Optional
from fastapi import Depends, HTTPException, status, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.integrations.firebase import (
    verify_firebase_token,
    FirebaseVerificationError,
    FirebaseNotInitializedError,
)
from app.modules.auth.service import AuthService
from app.modules.users.models import User, UserStatus, UserRole

# Tắt auto_error để chuẩn hóa response lỗi xác thực
security = HTTPBearer(auto_error=False)


async def get_token_payload(
    auth_header: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """
    Extracts and verifies the Firebase ID token from the Bearer Authorization header.
    """
    if not auth_header or not auth_header.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header.credentials
    try:
        payload = verify_firebase_token(token)
        return payload
    except FirebaseNotInitializedError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is currently unavailable.",
        ) from e
    except FirebaseVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_user(
    token_payload: dict[str, Any] = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Resolves the authenticated Firebase identity into an internal User model.
    """
    auth_service = AuthService(db)
    user = await auth_service.get_or_create_user_from_token_payload(token_payload)
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Ensures the user account is in ACTIVE status.
    Rejects BANNED and INACTIVE users with HTTP 403 Forbidden.
    """
    if current_user.status == UserStatus.BANNED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is banned.",
        )
    if current_user.status == UserStatus.INACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )
    return current_user


def require_role(*allowed_roles: str) -> Callable[[User], User]:
    """
    Dependency factory that checks if the authenticated active user has one of the allowed roles.
    """
    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for your user role.",
            )
        return current_user

    return role_checker


require_admin = require_role(UserRole.ADMIN.value)


async def authenticate_user_token(token: str, db: AsyncSession) -> User:
    """
    Authenticates a raw token string (e.g. for WebSockets) and returns the active User model.
    Raises HTTPException 401 on invalid token or 403 on banned/inactive status.
    """
    try:
        payload = verify_firebase_token(token)
    except (FirebaseNotInitializedError, FirebaseVerificationError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    auth_service = AuthService(db)
    user = await auth_service.get_or_create_user_from_token_payload(payload)
    if user.status in (UserStatus.BANNED, UserStatus.INACTIVE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản của bạn đã bị khóa hoặc chưa kích hoạt.",
        )
    return user


async def get_admin_for_evidence(
    request: Request,
    token: Optional[str] = Query(None, description="Admin token cho video/media streaming"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to authenticate an admin for media streaming.
    Supports Bearer header and optional ?token= query parameter (for native HTML5 video/media).
    """
    if token:
        user = await authenticate_user_token(token, db)
        if user.role != UserRole.ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for your user role.",
            )
        return user

    from app.main import app
    if get_admin_for_evidence in app.dependency_overrides:
        return app.dependency_overrides[get_admin_for_evidence]()
    if get_current_active_user in app.dependency_overrides:
        user = app.dependency_overrides[get_current_active_user]()
        if user.role != UserRole.ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for your user role.",
            )
        return user
    if get_current_user in app.dependency_overrides:
        override_fn = app.dependency_overrides[get_current_user]
        user = override_fn()
        if user.role != UserRole.ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for your user role.",
            )
        return user

    auth_header = await security(request)
    payload = await get_token_payload(auth_header)
    user = await get_current_user(payload, db)
    active_user = await get_current_active_user(user)
    if active_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted for your user role.",
        )
    return active_user

