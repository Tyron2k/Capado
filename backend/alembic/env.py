"""Alembic-Umgebungskonfiguration.

Liest DATABASE_URL aus der Umgebungsvariable und konfiguriert async Migrations.
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context

# Arbitrary constant key for the Postgres advisory lock that serializes
# concurrent migration runs (e.g. multiple uvicorn workers each running
# `alembic upgrade head` at startup). Without this they race and collide on
# CREATE TABLE / CREATE TYPE.
_MIGRATION_LOCK_KEY = 0x00CA_9AD0

# Alembic Config-Objekt
config = context.config

# Logging-Konfiguration aus alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLModel-Metadaten für Autogenerate
# Alle Models müssen hier importiert werden, damit sie in den Metadaten registriert sind.
from app.models import *  # noqa: F401, F403

target_metadata = SQLModel.metadata

# DATABASE_URL aus Umgebungsvariable (async-Variante für asyncpg)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/capado",
)

# Für Alembic brauchen wir die synchrone URL (psycopg2) oder async
# Wir verwenden hier die async-Variante
config.set_main_option("sqlalchemy.url", DATABASE_URL)


def run_migrations_offline() -> None:
    """Migrationen im 'offline'-Modus ausführen (SQL generieren ohne DB-Verbindung)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Migrationen mit einer bestehenden Verbindung ausführen.

    Serialisiert konkurrierende Migrationsläufe über einen
    transaktions-gebundenen Advisory-Lock: Der erste Worker migriert, weitere
    Worker warten und finden die DB anschließend bereits auf head vor (No-op).
    """
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        # Held for the duration of this transaction; released automatically on
        # commit/rollback. Concurrent runners block here until it is free.
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": _MIGRATION_LOCK_KEY},
        )
        context.run_migrations()


async def run_async_migrations() -> None:
    """Async-Engine erstellen und Migrationen ausführen."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Migrationen im 'online'-Modus ausführen (mit DB-Verbindung)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
