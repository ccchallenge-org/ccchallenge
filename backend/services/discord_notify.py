import asyncio
import logging

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# Embed colors
COLOR_CREATE = 0x57F287  # green
COLOR_UPDATE = 0xFEE75C  # yellow
COLOR_DELETE = 0xED4245  # red
COLOR_STATUS = 0x5865F2  # blue


async def _send(payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.discord_webhook_url, json=payload)
            resp.raise_for_status()
    except Exception as e:
        logger.warning("Discord webhook failed: %s", e)


def notify(
    action: str,
    description: str,
    user_name: str = "",
    url: str | None = None,
    color: int = COLOR_STATUS,
) -> None:
    """Fire-and-forget Discord webhook notification.

    Safe to call from sync or async context — never raises, never blocks the response.
    """
    if not settings.discord_webhook_url:
        return

    embed: dict = {
        "title": action,
        "description": description,
        "color": color,
    }
    if url:
        embed["url"] = url
    if user_name:
        embed["footer"] = {"text": f"by {user_name}"}

    payload = {"embeds": [embed]}

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send(payload))
    except RuntimeError:
        pass
