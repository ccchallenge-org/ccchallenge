import uuid
from typing import Optional

from fastapi import APIRouter
from fastapi_users import schemas as fu_schemas

from backend.auth.oauth import get_discord_client, get_github_client, get_google_client
from backend.auth.users import auth_backend, fastapi_users
from backend.config import settings


class UserRead(fu_schemas.BaseUser[uuid.UUID]):
    username: str


class UserCreate(fu_schemas.BaseUserCreate):
    username: str


class UserUpdate(fu_schemas.BaseUserUpdate):
    username: Optional[str] = None


router = APIRouter()

# Email / password auth
router.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth")
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
)

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
        ),
        prefix="/auth/discord",
    )
