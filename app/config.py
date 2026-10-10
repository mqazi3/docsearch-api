from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
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
    upload_dir: str = "data/uploads"
    max_upload_mb: int = 25
    embedding_provider: Literal["openai", "fake"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_batch_size: int = 64
    openai_api_key: SecretStr | None = None
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 75
    answer_provider: Literal["openai", "fake"] = "openai"
    answer_model: str = "gpt-6-luna"
    answer_max_output_tokens: int = 1000
    ask_max_context_tokens: int = 6000
    hybrid_keyword_any: bool = True
    identifier_routing: bool = True
    chunk_split_on_headings: bool = False
    rate_limit_search_per_minute: int = 60
    rate_limit_ask_per_minute: int = 10
    ask_daily_budget: int = 500


@lru_cache
def get_settings() -> Settings:
    return Settings()
