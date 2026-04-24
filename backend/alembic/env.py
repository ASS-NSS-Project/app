"""
alembic/env.py - Alembic migration environment configuration

Alembic needs to know:
1. Where the database is (URL)
2. Which models to track (metadata)

This allows it to auto-generate migrations when models change.
"""

import logging
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Load configuration from alembic.ini
config = context.config

# Only configure logging via alembic.ini when running alembic CLI standalone
# (root logger has no handlers yet). When called from main.py / worker.py,
# setup_logging() has already installed the JSON root handler — calling
# fileConfig() here would add alembic.ini's stderr handler and produce
# duplicate plain-text log lines alongside the JSON output.
if config.config_file_name is not None and not logging.root.handlers:
    fileConfig(config.config_file_name)

# Import our models – Alembic needs to know the schema to generate migrations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import Base
from models import *  # noqa: F401, F403 – required to register all models in Base.metadata

# Metadata for all tables – Alembic reads the schema from this
target_metadata = Base.metadata


def get_url() -> str:
    """
    Read the database URL from environment variables instead of alembic.ini.
    This is how Docker configuration works – secrets never go into code.
    """
    from config import get_settings
    return get_settings().database_url


def run_migrations_offline() -> None:
    """
    'Offline' mode: generates SQL scripts without connecting to the database.
    Useful for reviewing migrations before deployment.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    'Online' mode: connects to the database and runs migrations directly.
    This is the standard usage on application startup or in CI/CD.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No pooling – migrations run and that's it
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


# Run the appropriate mode based on context
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
