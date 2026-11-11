from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/qulay_davo"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me"
    access_token_minutes: int = 60 * 24
    timezone: str = "Asia/Tashkent"

    telegram_bot_token: str = ""
    eskiz_email: str = ""
    eskiz_password: str = ""
    eskiz_sender: str = "4546"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
