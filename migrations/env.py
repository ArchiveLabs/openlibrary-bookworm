from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

from bookworm.config import get_settings
from bookworm.database import get_engine
from bookworm.imports import models as import_models  # noqa: F401
from bookworm.projects import models as project_models  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url,
        target_metadata=SQLModel.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=SQLModel.metadata)
        with context.begin_transaction():
            # Keep queue tables out of Alembic's application-schema comparison.
            connection.exec_driver_sql("SET LOCAL search_path TO public")
            context.run_migrations()
