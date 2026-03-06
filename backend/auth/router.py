import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import schemas as fu_schemas
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.oauth import get_discord_client, get_github_client, get_google_client
from backend.auth.users import (
    UserNotVerifiedError,
    auth_backend,
    fastapi_users,
    get_user_manager,
)
from backend.config import settings
from backend.database import get_async_session
from backend.models import User


class UserRead(fu_schemas.BaseUser[uuid.UUID]):
    username: str


class UserCreate(fu_schemas.BaseUserCreate):
    username: str


class UserUpdate(fu_schemas.BaseUserUpdate):
    username: Optional[str] = None


router = APIRouter()


# Custom login that distinguishes unverified users — registered BEFORE default auth router
@router.post("/auth/login")
async def custom_login(
    request: Request,
    credentials: OAuth2PasswordRequestForm = Depends(),
    user_manager=Depends(get_user_manager),
):
    try:
        user = await user_manager.authenticate(credentials)
    except UserNotVerifiedError:
        raise HTTPException(status_code=400, detail="LOGIN_USER_NOT_VERIFIED")
    if user is None:
        raise HTTPException(status_code=400, detail="LOGIN_BAD_CREDENTIALS")
    strategy = auth_backend.get_strategy()
    response = await auth_backend.login(strategy, user)
    return response


# Custom register — returns minimal response (no email/UUID) and hides enumeration
@router.post("/auth/register", status_code=201)
async def custom_register(
    request: Request,
    data: UserCreate,
    user_manager=Depends(get_user_manager),
):
    from fastapi_users import exceptions as fu_exceptions

    try:
        await user_manager.create(data, safe=True, request=request)
    except fu_exceptions.UserAlreadyExists:
        pass  # Don't reveal whether email/username exists
    except fu_exceptions.InvalidPasswordException as e:
        raise HTTPException(status_code=400, detail={
            "code": "REGISTER_INVALID_PASSWORD",
            "reason": e.reason,
        })
    return {"status": "ok"}


# Custom verify — returns minimal response (no email/UUID)
@router.post("/auth/verify")
async def custom_verify(
    request: Request,
    data: dict,
    user_manager=Depends(get_user_manager),
):
    from fastapi_users import exceptions as fu_exceptions

    try:
        await user_manager.verify(data.get("token", ""), request)
    except (fu_exceptions.InvalidVerifyToken, fu_exceptions.UserNotExists):
        raise HTTPException(status_code=400, detail="VERIFY_USER_BAD_TOKEN")
    except fu_exceptions.UserAlreadyVerified:
        pass  # Already verified is fine
    return {"status": "ok"}


# Default auth router (login/register/verify shadowed by custom routes above, logout still works)
router.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth")
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
)
router.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
)


class ResendVerificationRequest(BaseModel):
    username: str


@router.post("/auth/resend-verification")
async def resend_verification(
    data: ResendVerificationRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user_manager=Depends(get_user_manager),
):
    """Resend verification email for an unverified user identified by username."""
    result = await session.execute(
        select(User).where(User.username == data.username)
    )
    user = result.unique().scalar_one_or_none()
    if user is None or user.is_verified:
        # Don't reveal whether the user exists
        return {"status": "ok"}
    await user_manager.request_verify(user, request)
    return {"status": "ok"}

# "Me" endpoint
router.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users")

# OAuth — only mount if credentials are configured
google = get_google_client()
if google:
    router.include_router(
        fastapi_users.get_oauth_router(
            google,
            auth_backend,
            settings.secret_key,
            redirect_url=f"{settings.base_url}/api/auth/google/callback",
        ),
        prefix="/auth/google",
    )

github = get_github_client()
if github:
    router.include_router(
        fastapi_users.get_oauth_router(
            github,
            auth_backend,
            settings.secret_key,
            redirect_url=f"{settings.base_url}/api/auth/github/callback",
            associate_by_email=True,
            is_verified_by_default=True,
        ),
        prefix="/auth/github",
    )

discord = get_discord_client()
if discord:
    router.include_router(
        fastapi_users.get_oauth_router(
            discord,
            auth_backend,
            settings.secret_key,
            redirect_url=f"{settings.base_url}/api/auth/discord/callback",
            associate_by_email=True,
            is_verified_by_default=True,
        ),
        prefix="/auth/discord",
    )
