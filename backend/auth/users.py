import secrets
import uuid
from typing import Optional

import resend
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, exceptions, models, schemas
from fastapi_users.authentication import AuthenticationBackend, CookieTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_async_session
from backend.models import OAuthAccount, User

resend.api_key = settings.resend_key


def _normalize_email(email: str) -> str:
    """Strip +tag from the local part of an email address."""
    local, domain = email.lower().rsplit("@", 1)
    if "+" in local:
        local = local[: local.index("+")]
    return f"{local}@{domain}"


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = settings.secret_key
    verification_token_secret = settings.secret_key

    async def create(
        self,
        user_create: schemas.UC,
        safe: bool = False,
        request: Request | None = None,
    ) -> models.UP:
        user_create.email = _normalize_email(user_create.email)
        # Check username uniqueness (fastapi-users only checks email)
        session = self.user_db.session
        existing = await session.execute(
            select(User).where(User.username == user_create.username)
        )
        if existing.unique().scalar_one_or_none() is not None:
            raise exceptions.UserAlreadyExists()
        return await super().create(user_create, safe=safe, request=request)

    async def _unique_username(self, base: str) -> str:
        """Ensure a username is unique, appending a suffix if needed."""
        base = base[:20]
        session = self.user_db.session
        result = await session.execute(select(User).where(User.username == base))
        if result.unique().scalar_one_or_none() is None:
            return base
        return f"{base}_{secrets.token_hex(3)}"

    async def _fetch_oauth_username(self, oauth_name: str, access_token: str) -> str | None:
        """Fetch the display username from the OAuth provider."""
        try:
            from backend.auth.oauth import get_github_client, get_discord_client
            if oauth_name == "github":
                client = get_github_client()
                if client:
                    profile = await client.get_profile(access_token)
                    return profile.get("login")
            elif oauth_name == "discord":
                client = get_discord_client()
                if client:
                    profile = await client.get_profile(access_token)
                    return profile.get("username")
        except Exception as e:
            print(f"Failed to fetch {oauth_name} profile: {e}")
        return None

    async def oauth_callback(
        self,
        oauth_name: str,
        access_token: str,
        account_id: str,
        account_email: str,
        expires_at: int | None = None,
        refresh_token: str | None = None,
        request: Request | None = None,
        *,
        associate_by_email: bool = False,
        is_verified_by_default: bool = False,
    ) -> models.UP:
        oauth_account_dict = {
            "oauth_name": oauth_name,
            "access_token": access_token,
            "account_id": account_id,
            "account_email": account_email,
            "expires_at": expires_at,
            "refresh_token": refresh_token,
        }

        try:
            user = await self.get_by_oauth_account(oauth_name, account_id)
        except exceptions.UserNotExists:
            try:
                user = await self.get_by_email(account_email)
                if not associate_by_email:
                    raise exceptions.UserAlreadyExists()
                user = await self.user_db.add_oauth_account(user, oauth_account_dict)
            except exceptions.UserNotExists:
                password = self.password_helper.generate()
                oauth_username = await self._fetch_oauth_username(oauth_name, access_token)
                username = await self._unique_username(
                    oauth_username or account_email.split("@")[0]
                )
                user_dict = {
                    "email": _normalize_email(account_email),
                    "hashed_password": self.password_helper.hash(password),
                    "is_verified": is_verified_by_default,
                    "username": username,
                }
                user = await self.user_db.create(user_dict)
                user = await self.user_db.add_oauth_account(user, oauth_account_dict)
                await self.on_after_register(user, request)
        else:
            for existing_oauth_account in user.oauth_accounts:
                if (
                    existing_oauth_account.account_id == account_id
                    and existing_oauth_account.oauth_name == oauth_name
                ):
                    user = await self.user_db.update_oauth_account(
                        user, existing_oauth_account, oauth_account_dict
                    )

        return user

    async def on_after_register(self, user: User, request: Optional[Request] = None):
        print(f"User {user.id} ({user.username}) registered.")
        if not user.is_verified:
            await self.request_verify(user, request)

    async def on_after_request_verify(self, user: User, token: str, request: Optional[Request] = None):
        verify_link = f"{settings.base_url}/verify?token={token}"
        print(f"Verification link for {user.email}: {verify_link}")
        if not settings.resend_key:
            print("RESEND_KEY not set — skipping email send.")
            return
        try:
            resend.Emails.send({
                "from": "ccchallenge <noreply@ccchallenge.org>",
                "to": [user.email],
                "subject": "Verify your ccchallenge account",
                "html": (
                    f"<p>Hi {user.username},</p>"
                    f"<p>Click the link below to verify your email address:</p>"
                    f'<p><a href="{verify_link}">{verify_link}</a></p>'
                    f"<p>If you didn't sign up for ccchallenge, you can ignore this email.</p>"
                ),
            })
        except Exception as e:
            print(f"Failed to send verification email to {user.email}: {e}")

    async def authenticate(self, credentials):
        """Authenticate by username instead of email. Rejects unverified users."""
        session = self.user_db.session
        result = await session.execute(
            select(User).where(User.username == credentials.username)
        )
        user = result.unique().scalar_one_or_none()
        if user is None:
            self.password_helper.hash(credentials.password)
            return None
        verified, updated_hash = self.password_helper.verify_and_update(
            credentials.password, user.hashed_password
        )
        if not verified:
            return None
        if updated_hash is not None:
            await self.user_db.update(user, {"hashed_password": updated_hash})
        if not user.is_verified:
            return None
        return user


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


cookie_transport = CookieTransport(
    cookie_max_age=settings.jwt_lifetime_seconds,
    cookie_httponly=True,
    cookie_samesite="lax",
    cookie_secure=settings.base_url.startswith("https"),
)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=settings.secret_key, lifetime_seconds=settings.jwt_lifetime_seconds)


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
current_optional_user = fastapi_users.current_user(active=True, optional=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
