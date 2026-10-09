from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or a local .env file).

    Defaults point at the local Docker Compose services and contain no secrets.
    Real secrets (the OpenAI key in Stage 2) will have no default, so the app
    fails fast if one is missing.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://docsearch:docsearch@localhost:5434/docsearch"
    redis_url: str = "redis://localhost:6380/0"
    environment: str = "development"
    app_version: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
