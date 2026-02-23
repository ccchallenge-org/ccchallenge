from httpx_oauth.clients.discord import DiscordOAuth2
from httpx_oauth.clients.github import GitHubOAuth2
from httpx_oauth.clients.google import GoogleOAuth2

from backend.config import settings


def get_google_client() -> GoogleOAuth2 | None:
    if settings.google_client_id and settings.google_client_secret:
        return GoogleOAuth2(settings.google_client_id, settings.google_client_secret)
    return None


def get_github_client() -> GitHubOAuth2 | None:
    if settings.github_client_id and settings.github_client_secret:
        return GitHubOAuth2(settings.github_client_id, settings.github_client_secret)
    return None


def get_discord_client() -> DiscordOAuth2 | None:
    if settings.discord_client_id and settings.discord_client_secret:
        return DiscordOAuth2(settings.discord_client_id, settings.discord_client_secret)
    return None
