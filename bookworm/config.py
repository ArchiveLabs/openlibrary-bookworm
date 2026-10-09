from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOOKWORM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://bookworm:bookworm@localhost:5432/bookworm"


@lru_cache
def get_settings() -> Settings:
    return Settings()
