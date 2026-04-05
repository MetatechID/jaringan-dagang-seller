"""Alembic environment configuration for async SQLAlchemy migrations."""

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ensure the app package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import settings
from app.models import Base  # noqa: F401  -- registers all models

# Alembic Config object
config = context.config

# Set the database URL from application settings
# Replace asyncpg with psycopg2 for offline mode, keep asyncpg for online mode
db_url = os.getenv("DATABASE_URL") or settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", db_url)

# Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    # For offline mode we need a sync URL
    url = config.get_main_option("sqlalchemy.url")
    if url and "+asyncpg" in url:
        url = url.replace("+asyncpg", "")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Run migrations against the provided connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using an async engine."""
    configuration = config.get_section(config.config_ini_section, {})

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations -- delegates to async runner."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
