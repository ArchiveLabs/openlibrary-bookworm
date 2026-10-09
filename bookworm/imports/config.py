from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ImportSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOOKWORM_", env_file=".env", extra="ignore")

    dispatcher_concurrency: int = Field(default=50, ge=1, le=50)
    dispatcher_lock_key: int = 824731
    poll_interval: float = Field(default=1.0, gt=0)


@lru_cache
def get_import_settings() -> ImportSettings:
    return ImportSettings()
