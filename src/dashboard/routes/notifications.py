"""Dashboard — the Notifications page (archiver#363 D5, #367 D5-D6).

A list grouped by scope, and create, edit and delete through the service the
API uses (``src.core.services.notification_subscriptions``). Plain forms:
POST→303 on success, the form again with a 422 on a refusal.

- **The scope and its ref are fixed after create**, as on the API: the edit
  form shows them, read-only.
- **The Jinja fields are on the form, with a live preview beside them** (#367
  D5): ``POST /preview`` renders the posted form strict against the canned
  fixtures, locally, with no Notifier call (``src.dashboard.notification_form``).
- **The one send is the edit page's test-send** (#367 D6): ``POST
  /{id}/test-send`` renders the row's saved options against the canned change,
  titles it ``[Test]``, and makes one dispatch to the row's channel. Dashboard
  only: no API route and no SDK method, so an API key can't post to Slack or an
  inbox. On 8000 it reaches real people, and that is the operator's action.

Forms are read with ``request.form()``: a typed ``Form`` param would be coerced
before any dashboard code ran (``test_no_dashboard_route_declares_a_coercible_param``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session, get_notifier
from src.core.logging import get_logger
from src.core.models import Domain, InfoItem, NotificationSubscription
from src.core.models.notification_subscription import NOTIFICATION_EVENTS, SCOPES
from src.core.notifications.content import compose, resolve_options
from src.core.notifications.default_templates import (
    DEFAULT_BODY_TEMPLATES,
    DEFAULT_TITLE_TEMPLATES,
    TEMPLATE_VARIABLES,
)
from src.core.notifications.preview_fixtures import PREVIEW_ITEM, preview_diff, preview_event
from src.core.notifier.client import Notifier, NotifierUnavailable
from src.core.services import notification_subscriptions as subs
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound
from src.dashboard.notification_form import (
    EVENT_LABELS,
    TEMPLATE_FIELDS,
    TOGGLES,
    content_config_from_form,
    event_labels,
    options_view,
    posted_view,
    render_preview,
)
from src.dashboard.pagination import Pagination, pagination

logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard/notifications")

#: The event a test-send renders, whatever the row hears (D6).
TEST_SEND_EVENT = "change_detected"

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_LIST = "/dashboard/notifications/"
_SCOPE_ORDER = case({s: i for i, s in enumerate(SCOPES)}, value=NotificationSubscription.scope)


async def _get_or_404(session: AsyncSession, subscription_id: str) -> NotificationSubscription:
    try:
        key = ULID.from_str(subscription_id)
    except ValueError as e:
        raise DashboardNotFound("Notification subscription not found") from e
    sub = await session.get(NotificationSubscription, key)
    if sub is None:
        raise DashboardNotFound("Notification subscription not found")
    return sub


async def _refs(session: AsyncSession, rows: list[NotificationSubscription]) -> dict[str, Any]:
    """Domain names and item names for the rows' refs, keyed by id."""
    domain_ids = {s.domain_id for s in rows if s.domain_id}
    item_ids = {s.info_item_id for s in rows if s.info_item_id}
    domains = (
        dict(
            (
                await session.execute(
                    select(Domain.id, Domain.name).where(Domain.id.in_(domain_ids))
                )
            ).all()
        )
        if domain_ids
        else {}
    )
    items = (
        dict(
            (
                await session.execute(
                    select(InfoItem.info_item_id, InfoItem.name).where(
                        InfoItem.info_item_id.in_(item_ids)
                    )
                )
            ).all()
        )
        if item_ids
        else {}
    )
    return {"domain_names": domains, "item_names": items}


# ---------------------------------------------------------------------------
# GET /dashboard/notifications/
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def list_subscriptions(
    request: Request,
    page: Pagination = Depends(pagination),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Every subscription, grouped by scope (global, domain, item), oldest first."""
    rows = list(
        (
            await session.execute(
                select(NotificationSubscription)
                .order_by(
                    _SCOPE_ORDER,
                    NotificationSubscription.created_at,
                    NotificationSubscription.id,
                )
                .offset(page.offset)
                .limit(page.limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(rows) > page.limit
    rows = rows[: page.limit]
    groups = {scope: [s for s in rows if s.scope == scope] for scope in SCOPES}
    # Headings count every row, not the page (SCREENS.md, #82; CR 4).
    counted = dict(
        (
            await session.execute(
                select(NotificationSubscription.scope, func.count()).group_by(
                    NotificationSubscription.scope
                )
            )
        ).all()
    )
    totals = {scope: counted.get(scope, 0) for scope in SCOPES}
    return _templates.TemplateResponse(
        request,
        "notifications/list.html",
        {
            "user": user,
            "groups": groups,
            "totals": totals,
            "has_more": has_more,
            "limit": page.limit,
            "offset": page.offset,
            "event_labels": event_labels,
            **await _refs(session, rows),
        },
    )


# ---------------------------------------------------------------------------
# New / edit form
# ---------------------------------------------------------------------------


async def _form_context(
    session: AsyncSession,
    *,
    sub: NotificationSubscription | None,
    values: dict[str, Any],
    content: dict | None,
    errors: list[str],
    posted=None,
) -> dict[str, Any]:
    """``posted``: a refused form, re-shown as typed (CR 2); else ``content``, stored."""
    domains = list((await session.execute(select(Domain.name).order_by(Domain.name))).scalars())
    refs = await _refs(session, [sub]) if sub else {"domain_names": {}, "item_names": {}}
    return {
        "sub": sub,
        "values": values,
        "options": posted_view(posted) if posted is not None else options_view(content),
        "errors": errors,
        "domains": domains,
        "scopes": SCOPES,
        "events": [(e, EVENT_LABELS[e]) for e in NOTIFICATION_EVENTS],
        "toggles": TOGGLES,
        "template_fields": TEMPLATE_FIELDS,
        "template_variables": TEMPLATE_VARIABLES,
        "event_labels_map": EVENT_LABELS,
        "default_templates": [
            (EVENT_LABELS[e], DEFAULT_TITLE_TEMPLATES[e], DEFAULT_BODY_TEMPLATES[e])
            for e in NOTIFICATION_EVENTS
        ],
        **refs,
    }


def _render(request, user, context, *, status_code: int = 200) -> HTMLResponse:
    return _templates.TemplateResponse(
        request, "notifications/form.html", {"user": user, **context}, status_code=status_code
    )


@router.get("/new", response_class=HTMLResponse)
async def new_subscription_form(
    request: Request,
    scope: str | None = None,
    domain: str | None = None,
    info_item_id: str | None = None,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """The create form; ``scope``, ``domain`` and ``info_item_id`` prefill it."""
    values = {
        "title": "",
        "scope": scope if scope in SCOPES else "global",
        "domain": domain or "",
        "info_item_id": info_item_id or "",
        "events": list(NOTIFICATION_EVENTS),
        "remote_channel_id": "",
        "is_active": True,
    }
    context = await _form_context(session, sub=None, values=values, content=None, errors=[])
    return _render(request, user, context)


def _posted(form) -> dict[str, Any]:
    return {
        "title": (form.get("title") or "").strip(),
        "scope": form.get("scope") or "",
        "domain": (form.get("domain") or "").strip(),
        "info_item_id": (form.get("info_item_id") or "").strip(),
        "events": form.getlist("events"),
        "remote_channel_id": (form.get("remote_channel_id") or "").strip(),
        "is_active": bool(form.get("is_active")),
    }


def _common_errors(values: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The fields create and edit share, checked; the cleaned values beside the problems."""
    errors: list[str] = []
    cleaned: dict[str, Any] = {"is_active": values["is_active"]}
    if not 1 <= len(values["title"]) <= 100:
        errors.append("Title must be 1-100 characters.")
    cleaned["title"] = values["title"]
    try:
        cleaned["events"] = subs.canonical_events(values["events"])
    except subs.SubscriptionRefused as e:
        errors.extend(message for _, message in e.errors)
    try:
        cleaned["remote_channel_id"] = subs.normalize_channel_id(values["remote_channel_id"])
    except ValueError as e:
        errors.append(str(e))
    return cleaned, errors


@router.post("/new", response_class=HTMLResponse)
async def create_subscription_view(
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Create through the service; 303 to the list, or the form again with a 422."""
    form = await request.form()
    values = _posted(form)
    cleaned, errors = _common_errors(values)
    content, content_errors = content_config_from_form(form)
    errors += content_errors
    if values["scope"] not in SCOPES:
        errors.append("Choose a scope.")
    info_item_id = values["info_item_id"] if values["scope"] == "item" else None
    if info_item_id is not None:
        try:
            info_item_id = str(ULID.from_str(info_item_id))
        except ValueError:
            errors.append(f"InfoItem id {info_item_id!r} is not a ULID.")
    if not errors:
        try:
            await subs.create_subscription(
                session,
                scope=values["scope"],
                domain=(values["domain"] or None) if values["scope"] == "domain" else None,
                info_item_id=info_item_id or None,
                content_config=content,
                **cleaned,
            )
        except subs.SubscriptionRefused as e:
            errors.extend(message for _, message in e.errors)
    if errors:
        # CR 2: the content options are re-shown as posted, not reset.
        context = await _form_context(
            session, sub=None, values=values, content=None, posted=form, errors=errors
        )
        return _render(request, user, context, status_code=422)
    await session.commit()
    return RedirectResponse(url=_LIST, status_code=303)


@router.get("/{subscription_id}/edit", response_class=HTMLResponse)
async def edit_subscription_form(
    subscription_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """The edit form; the scope and its ref show read-only."""
    sub = await _get_or_404(session, subscription_id)
    values = {
        "title": sub.title,
        "events": sub.events,
        "remote_channel_id": sub.remote_channel_id,
        "is_active": sub.is_active,
    }
    context = await _form_context(
        session, sub=sub, values=values, content=sub.content_config, errors=[]
    )
    return _render(request, user, context)


@router.post("/{subscription_id}/edit", response_class=HTMLResponse)
async def update_subscription_view(
    subscription_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Save the editable fields, the Jinja templates as the form holds them."""
    sub = await _get_or_404(session, subscription_id)
    form = await request.form()
    values = _posted(form)
    cleaned, errors = _common_errors(values)
    content, content_errors = content_config_from_form(form)
    errors += content_errors
    if errors:
        context = await _form_context(
            session, sub=sub, values=values, content=None, posted=form, errors=errors
        )
        return _render(request, user, context, status_code=422)
    subs.update_subscription(sub, {**cleaned, "content_config": content})
    await session.commit()
    return RedirectResponse(url=_LIST, status_code=303)


@router.post("/{subscription_id}/delete")
async def delete_subscription_view(
    subscription_id: str,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    """Delete, then back to the list."""
    sub = await _get_or_404(session, subscription_id)
    await session.delete(sub)
    await session.commit()
    return RedirectResponse(url=_LIST, status_code=303)


# ---------------------------------------------------------------------------
# POST /dashboard/notifications/preview  (#367 D5)
# ---------------------------------------------------------------------------


@router.post("/preview", response_class=HTMLResponse)
async def preview_subscription(
    request: Request,
    user=Depends(get_dashboard_user),
) -> HTMLResponse:
    """The posted form's options for one event, rendered strict against the fixtures.

    Local: no Notifier call, no database. Shares the save path's validator.
    """
    form = await request.form()
    # A worker thread: an operator's template must not block the loop (CR 1).
    view = await asyncio.to_thread(render_preview, form, str(form.get("preview_event") or ""))
    return _templates.TemplateResponse(
        request,
        "notifications/_preview.html",
        {"user": user, "preview": view, "labels": EVENT_LABELS},
    )


# ---------------------------------------------------------------------------
# POST /dashboard/notifications/{id}/test-send  (#367 D6)
# ---------------------------------------------------------------------------


@router.post("/{subscription_id}/test-send", response_class=HTMLResponse)
async def test_send_subscription(
    subscription_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    notifier: Notifier | None = Depends(get_notifier),
) -> HTMLResponse:
    """One dispatch of the row's saved options against the canned change, titled ``[Test]``.

    Idempotency key ``archiver:test:{subscription_id}:{ULID}``, so each press is
    its own dispatch; metadata marks it a test. Answers with the dispatch id or
    the reason, as a flash and in the page. One INFO line: the ids, never the
    text or the key.
    """
    sub = await _get_or_404(session, subscription_id)
    channel_id = sub.remote_channel_id
    if notifier is None:
        return _test_send_result(
            request, "error", "Notifier is not configured in this process: nothing was sent."
        )
    event = preview_event(TEST_SEND_EVENT)
    composed = await asyncio.to_thread(  # off the loop, as the preview (CR 1)
        compose,
        event,
        PREVIEW_ITEM,
        resolve_options(sub.content_config, TEST_SEND_EVENT),
        diff=preview_diff(TEST_SEND_EVENT),
        subscription_id=str(sub.id),
    )
    try:
        dispatched = await notifier.dispatch_composed(
            channel_id=channel_id,
            title=f"[Test] {composed.title}",
            body=composed.body,
            idempotency_key=f"archiver:test:{sub.id}:{ULID()}",
            metadata={"test": True, "subscription_id": str(sub.id)},
        )
    except NotifierUnavailable as e:
        logger.info(
            "notification test-send refused",
            extra={"subscription_id": str(sub.id), "channel_id": channel_id, "reason": str(e)},
        )
        return _test_send_result(request, "error", f"Test-send not sent: {e}")
    logger.info(
        "notification test-send dispatched",
        extra={
            "subscription_id": str(sub.id),
            "channel_id": channel_id,
            "dispatch_id": dispatched.id,
            "status": dispatched.status,
        },
    )
    if dispatched.status == "succeeded":
        return _test_send_result(
            request, "success", f"Test-send dispatched to {channel_id}: {dispatched.id}."
        )
    return _test_send_result(
        request,
        "warning",
        f"Test-send dispatch {dispatched.id} to {channel_id}: delivery {dispatched.status}.",
    )


def _test_send_result(request: Request, level: str, message: str) -> HTMLResponse:
    """The outcome, as the ``#test-send-result`` fragment and as a flash."""
    response = _templates.TemplateResponse(
        request, "notifications/_test_send_result.html", {"level": level, "message": message}
    )
    response.headers["HX-Trigger"] = json.dumps({"showFlash": {"level": level, "body": message}})
    return response
