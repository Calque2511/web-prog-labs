from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str = "sqlite:///./app.db"
    # без redis_url работает fakeredis
    redis_url: str | None = None
    secret_key: str = Field(default="dev-secret-change-me-dev-secret-0123456789", min_length=32)
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 7
    bcrypt_rounds: int = 12
    cors_origins: str = "http://localhost:3000"
    cookie_secure: bool = False
    log_level: str = "INFO"
    user_cache_ttl_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
