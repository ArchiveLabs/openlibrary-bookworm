from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from bookworm.config import get_settings
from bookworm.imports import models as import_models  # noqa: F401
from bookworm.projects import models as project_models  # noqa: F401


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"options": "-c search_path=public,procrastinate"},
    )


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
