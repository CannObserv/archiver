"""Archiver service async engine + session factory.

Reads the database URL from ARCHIVER_DATABASE_URL, falling back to
DATABASE_URL for prototype convenience (single-instance Postgres on this VM).
"""

import os

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.logging import REDACTED, get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_database_url() -> str:
    url = os.environ.get("ARCHIVER_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Neither ARCHIVER_DATABASE_URL nor DATABASE_URL is set. "
            "Production's is the units' (/etc/archiver/.env); a _dev/_test run "
            "sets it explicitly. See AGENTS.md § Environment Files."
        )
    return url


def loggable_url(url: URL) -> str:
    """Where *url* points, for a log line: ``host:port/database``, no credentials (#448).

    Rebuilt from the URL SQLAlchemy parsed, the one it connects with, rather
    than sliced from the string: ``url.split("@")[-1]`` kept the query, and
    libpq and asyncpg both take ``?password=``. A query shows only as ``?***``.
    ``CredentialRedactingFilter`` cannot catch that one: it matches
    ``scheme://user:password@``, and this line has neither.
    """
    host = url.host or ""
    if ":" in host:  # IPv6 literal: SQLAlchemy strips the brackets
        host = f"[{host}]"
    if url.port is not None:
        host = f"{host}:{url.port}"
    shown = f"{host}/{url.database or ''}"
    return f"{shown}?{REDACTED}" if url.query else shown


def get_engine() -> AsyncEngine:
    """The process's one engine: request sessions, consumers, the outbox, the timers.

    ``pool_pre_ping`` tests each pooled connection at checkout and replaces a
    dead one (#510). A Postgres restart with the app up - the patch run's held
    ``postgres`` step - kills every idle pooled connection, and without the
    ping each one failed its next request. The ping covers checkout only: a
    connection that dies mid-transaction still fails that transaction once.
    """
    global _engine
    if _engine is None:
        url = get_database_url()
        _engine = create_async_engine(url, echo=False, pool_pre_ping=True)
        logger.info("archiver db engine created", extra={"url": loggable_url(_engine.url)})
    return _engine


def reset_engine() -> None:
    """Test-only: clear cached engine + factory."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory
