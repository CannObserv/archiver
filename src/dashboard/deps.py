"""Dashboard-specific FastAPI dependencies."""

import hashlib
import secrets
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.core.models import AppUser


class DashboardAuthRequired(Exception):
    """Raised when proxy auth headers are absent; triggers a login redirect."""

    def __init__(self, redirect_to: str) -> None:
        self.redirect_to = redirect_to


async def get_dashboard_user(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> AppUser:
    """Resolve the current operator from exe.dev proxy headers, upsert into DB.

    Raises ``DashboardAuthRequired`` (307 redirect) when either header is
    absent.  Email is updated if it changed since the last login.

    **Reads take the read path.** The steady state - a known ``external_id``
    whose email has not moved - is one indexed SELECT and no write. The upsert
    below runs only on first sight or a genuine email change, because running
    it unconditionally cost more than the write (#180): ``ON CONFLICT DO
    UPDATE`` takes a row lock even when its ``WHERE`` skips the update, and
    this dependency resolves before the route body, so the lock was held for
    the whole request and an operator's concurrent partials queued on their
    own ``app_users`` row.

    The write commits here rather than riding the route's transaction.
    ``get_db_session`` does not commit and read-only routes do not either, so
    an identity established on a page view was inserted and then rolled back
    at session close - every visit re-inserting a row that never landed.

    The insert keeps ``ON CONFLICT (external_id) DO UPDATE`` so two concurrent
    first-logins cannot race the unique constraint (#177); the loser of the
    race gets the winner's row back from RETURNING.
    """
    external_id = request.headers.get("X-ExeDev-UserID")
    email = request.headers.get("X-ExeDev-Email")
    if not external_id or not email:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise DashboardAuthRequired(redirect_to=f"/__exe.dev/login?redirect={quote(target)}")

    result = await session.execute(select(AppUser).where(AppUser.external_id == external_id))
    user = result.scalar_one_or_none()
    if user is not None and user.email == email:
        return user

    stmt = (
        pg_insert(AppUser)
        .values(external_id=external_id, email=email)
        .on_conflict_do_update(
            index_elements=[AppUser.external_id],
            set_={"email": email, "updated_at": datetime.now(UTC)},
        )
        .returning(AppUser)
    )
    orm_stmt = select(AppUser).from_statement(stmt).execution_options(populate_existing=True)
    user = (await session.execute(orm_stmt)).scalar_one()
    await session.commit()

    return user


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        (raw_key, key_prefix, key_hash) - raw_key is shown once to the user and
        never stored.  key_prefix is the first 8 chars for display. key_hash is
        SHA-256(raw_key) and is what gets persisted.
    """
    token = secrets.token_hex(16)  # 32 hex chars
    raw_key = f"co_{token}"
    key_prefix = raw_key[:8]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, key_prefix, key_hash
