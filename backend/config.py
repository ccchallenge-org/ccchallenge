from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///data/ccchallenge.db"
    secret_key: str = "CHANGE-ME-in-production"
    jwt_lifetime_seconds: int = 60 * 60 * 24 * 30  # 30 days

    # OAuth (optional — leave empty to disable)
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    discord_client_id: str = ""
    discord_client_secret: str = ""

    resend_key: str = ""
    discord_webhook_url: str = ""

    base_url: str = "http://localhost:8000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
