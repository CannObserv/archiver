"""Alembic environment for the Archiver service.

Tables are scoped to a Postgres `information` schema (legacy name retained
to avoid migration churn — this is an internal DB detail).
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.db_safety import (
    ALLOW_PRODUCTION_DB_ENV,
    ProductionDatabaseRefused,
    assert_production_db_allowed,
)
from src.core.models import Base
from src.core.models.base import ULIDType

config = context.config

if config.config_file_name is not None:
    # Not the default True: the test session migrates after importing every
    # src module, and disabling their loggers hid logging-time crashes (#327).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

INFORMATION_SCHEMA = "information"


def include_object(object_, name, type_, reflected, compare_to):
    """Restrict autogenerate to objects in the `information` schema."""
    if type_ == "table":
        return getattr(object_, "schema", None) == INFORMATION_SCHEMA
    if type_ in ("index", "unique_constraint", "foreign_key_constraint"):
        table = getattr(object_, "table", None)
        if table is None:
            return True
        return getattr(table, "schema", None) == INFORMATION_SCHEMA
    return True


def render_item(type_, obj, autogen_context):
    if type_ == "type" and isinstance(obj, ULIDType):
        return "sa.String(length=26)"
    return False


def get_url() -> str:
    url = (
        os.environ.get("ARCHIVER_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or config.get_main_option("sqlalchemy.url", "")
    )
    if not url:
        raise RuntimeError(
            "Set ARCHIVER_DATABASE_URL or DATABASE_URL before running alembic. "
            "Load env: set -a; "
            "[ -f /etc/archiver/.env ] && . /etc/archiver/.env; "
            "[ -f .env ] && . .env; set +a"
        )
    return url


def _common_configure_kwargs() -> dict:
    return dict(
        target_metadata=target_metadata,
        include_object=include_object,
        include_schemas=True,
        version_table_schema=INFORMATION_SCHEMA,
        render_item=render_item,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_common_configure_kwargs(),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, **_common_configure_kwargs())
    with context.begin_transaction():
        context.run_migrations()


async def _ensure_schema(engine) -> None:
    """Create the target schema if missing, in its own AUTOCOMMIT connection
    so the DDL lands independently of alembic's transaction below."""
    autocommit = engine.execution_options(isolation_level="AUTOCOMMIT")
    async with autocommit.connect() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {INFORMATION_SCHEMA}"))


def assert_migration_target_allowed(url: str) -> None:
    """Refuse an un-opted-in production database before connecting (archiver#330 D9).

    ``scripts/deploy.sh`` is the one sanctioned migrator of production: it alone
    passes ``ARCHIVER_ALLOW_PRODUCTION_DB=1``. A shell that sourced
    ``/etc/archiver/.env`` holds the production URL, so without this an
    ``upgrade`` or ``downgrade`` from it reaches the live registry. Offline
    (``--sql``) runs connect to nothing and are not checked (status#15).
    """
    try:
        assert_production_db_allowed(url, allow_flag=os.environ.get(ALLOW_PRODUCTION_DB_ENV))
    except ProductionDatabaseRefused as e:
        raise ProductionDatabaseRefused(
            f"{e}\n  alembic: production migrates only through scripts/deploy.sh. "
            'Against the dev database: DATABASE_URL="$ARCHIVER_DEV_DATABASE_URL" '
            "with ARCHIVER_DATABASE_URL unset."
        ) from e


async def run_migrations_online() -> None:
    url = get_url()
    assert_migration_target_allowed(url)
    connectable = create_async_engine(url)
    await _ensure_schema(connectable)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
