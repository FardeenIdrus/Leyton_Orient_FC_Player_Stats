"""Alembic migration environment.

The database URL is taken from the application Settings (which reads DATABASE_URL
from the environment / .env), so migrations and the app always agree on the target.
``target_metadata`` stays None until the ORM models land in Phase 3; the Phase 0
baseline is intentionally empty.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from lofc.config import settings
from lofc.store.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the URL from Settings rather than hard-coding it in alembic.ini.
config.set_main_option("sqlalchemy.url", settings.database_url)

# ORM metadata, so `alembic revision --autogenerate` sees the model tables.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DBAPI connection (emits SQL)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
