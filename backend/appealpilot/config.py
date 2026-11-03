from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # LLM. With no key the agent falls back to the deterministic offline planner,
    # so the demo, tests and retrieval eval all run for free.
    anthropic_api_key: str | None = None
    appealpilot_model: str = "claude-opus-5-5"
    appealpilot_effort: str = "medium"
    appealpilot_max_turns: int = 12

    # Storage. Empty means in-memory (great for tests and the local demo).
    database_url: str | None = None

    # Retrieval
    embed_dim: int = 384
    search_top_k: int = 5

    # CORS for the Next.js frontend
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
