"""
Alembic migration environment.

Reads DATABASE_URL from the environment (or .env file) and wires up
the SQLAlchemy metadata from backend.repositories.pg.schema so that
`alembic revision --autogenerate` can diff the ORM models against the
live database schema.

Usage
-----
    # Generate a new auto migration:
    alembic revision --autogenerate -m "description"

    # Apply all pending migrations:
    alembic upgrade head

    # Roll back one migration:
    alembic downgrade -1
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Make project root importable ─────────────────────────────────────────────
# Alembic runs from the project root, but add it explicitly to be safe.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Import ORM metadata ───────────────────────────────────────────────────────
from backend.repositories.pg.schema import Base  # noqa: E402

# ── Alembic config ────────────────────────────────────────────────────────────
config = context.config

# Allow DATABASE_URL to override the value in alembic.ini
database_url = os.getenv("DATABASE_URL", "")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Set up logging from the config file section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Generates SQL statements to stdout without connecting to the database.
    Useful for reviewing changes or running in environments without DB access.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    Connects to the live database and applies pending migrations.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
