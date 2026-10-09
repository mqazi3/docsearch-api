from logging.config import fileConfig

from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (registers the models on Base.metadata)
from alembic import context
from app.config import get_settings
from app.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    """Skip vector columns when comparing types; use Alembic's default for everything else.

    The reflected pgvector type doesn't reliably include its dimension, which would make
    `alembic check` report a false difference.
    """
    if isinstance(metadata_type, Vector):
        return False
    return None


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=compare_type,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=compare_type,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
