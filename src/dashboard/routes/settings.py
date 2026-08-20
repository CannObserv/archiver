"""Dashboard settings — API key management.

**A refusal is a 200 with a flash, never a 4xx** — the rule `docs/STYLE.md`
states and `src/dashboard/replication_actions.py` explains. Both label checks
here used to `raise_422`, and under `hx-boost` htmx discarded the response
whole: no key created, no row renamed, nothing said (archiver#178).
"""

import json
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
from src.dashboard.exceptions import DashboardNotFound

router = APIRouter(prefix="/dashboard/settings")

# A label of spaces passes the input's `required` attribute, so this is a real
# operator path rather than a broken template.
_BLANK_LABEL_FLASH = json.dumps(
    {"showFlash": {"level": "error", "body": "Label is required — nothing was saved."}}
)

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _get_user_keys(session: AsyncSession, user: AppUser) -> list[ApiKey]:
    result = await session.execute(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at)
    )
    return list(result.scalars().all())


async def _resolve_key(key_id: str, user: AppUser, session: AsyncSession) -> ApiKey:
    """Fetch an ApiKey by id, raising 404 if absent or owned by a different user."""
    try:
        uid = ULID.from_str(key_id)
    except Exception as e:
        raise DashboardNotFound("API key not found") from e

    result = await session.execute(select(ApiKey).where(ApiKey.id == uid))
    api_key = result.scalar_one_or_none()
    if api_key is None or api_key.user_id != user.id:
        raise DashboardNotFound("API key not found")
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
    label = label.strip()
    if not label:
        keys = await _get_user_keys(session, user)
        return _templates.TemplateResponse(
            request,
            "settings/api_keys.html",
            {"user": user, "keys": keys, "new_raw_key": None},
            headers={"HX-Trigger": _BLANK_LABEL_FLASH},
        )

    raw_key, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        user_id=user.id,
        label=label,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    session.add(api_key)
    await session.commit()

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
    await session.commit()
    return Response(status_code=200)


@router.patch("/api-keys/{key_id}", response_class=HTMLResponse)
async def settings_rename_api_key(
    request: Request,
    key_id: str,
    label: str = Form(...),
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Rename one of the current user's API keys; returns updated row fragment.

    Ownership is resolved before the label is judged: someone else's key is a
    404 whatever was typed into it.
    """
    api_key = await _resolve_key(key_id, user, session)

    label = label.strip()
    if not label:
        # The unchanged row, so the swap still happens — a refused swap looks
        # exactly like a rename that worked.
        return _templates.TemplateResponse(
            request,
            "settings/_api_key_row.html",
            {"key": api_key},
            headers={"HX-Trigger": _BLANK_LABEL_FLASH},
        )

    api_key.label = label
    await session.commit()

    return _templates.TemplateResponse(request, "settings/_api_key_row.html", {"key": api_key})
