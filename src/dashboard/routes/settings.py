"""Dashboard settings — API key management."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.core.models import ApiKey, AppUser
from src.dashboard.deps import generate_api_key, get_dashboard_user

router = APIRouter(prefix="/dashboard/settings", tags=["dashboard-settings"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _get_user_keys(session: AsyncSession, user: AppUser) -> list[ApiKey]:
    result = await session.execute(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at)
    )
    return list(result.scalars().all())


async def _resolve_key(key_id: str, user: AppUser, session: AsyncSession) -> ApiKey:
    """Fetch an ApiKey by id, raising 404 if absent or owned by a different user."""
    from src.api.errors import raise_envelope

    try:
        uid = ULID.from_str(key_id)
    except Exception as e:
        raise_envelope(404, "lookup", "API key not found", source_exc=e)

    result = await session.execute(select(ApiKey).where(ApiKey.id == uid))
    api_key = result.scalar_one_or_none()
    if api_key is None or api_key.user_id != user.id:
        raise_envelope(404, "lookup", "API key not found")
    return api_key


@router.get("/api-keys", response_class=HTMLResponse)
async def settings_api_keys(
    request: Request,
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """List the current user's API keys."""
    keys = await _get_user_keys(session, user)
    return _templates.TemplateResponse(
        request, "settings/api_keys.html", {"user": user, "keys": keys, "new_raw_key": None}
    )


@router.post("/api-keys", response_class=HTMLResponse)
async def settings_create_api_key(
    request: Request,
    label: str = Form(...),
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Create a new API key; returns the page with the raw key shown once."""
    from src.api.errors import raise_422

    label = label.strip()
    if not label:
        raise_422("label is required")

    raw_key, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        user_id=user.id,
        label=label,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    session.add(api_key)
    await session.flush()

    keys = await _get_user_keys(session, user)
    return _templates.TemplateResponse(
        request,
        "settings/api_keys.html",
        {"user": user, "keys": keys, "new_raw_key": raw_key},
    )


@router.delete("/api-keys/{key_id}")
async def settings_delete_api_key(
    key_id: str,
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Delete one of the current user's API keys."""
    api_key = await _resolve_key(key_id, user, session)
    await session.delete(api_key)
    await session.flush()
    return Response(status_code=200)


@router.patch("/api-keys/{key_id}", response_class=HTMLResponse)
async def settings_rename_api_key(
    request: Request,
    key_id: str,
    label: str = Form(...),
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Rename one of the current user's API keys; returns updated row fragment."""
    from src.api.errors import raise_422

    label = label.strip()
    if not label:
        raise_422("label is required")

    api_key = await _resolve_key(key_id, user, session)
    api_key.label = label
    await session.flush()

    return _templates.TemplateResponse(request, "settings/_api_key_row.html", {"key": api_key})
