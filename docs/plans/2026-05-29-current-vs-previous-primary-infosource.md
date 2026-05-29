---
issue: "https://github.com/CannObserv/archiver/issues/44"
---

# Current vs Previous Primary InfoSource — Vocabulary, API Exposure, and Succession Event

## Problem

The Archiver correctly preserves deactivated primary bindings (`info_item_sources` rows with `role IS NULL AND deactivated_at IS NOT NULL`), but three gaps make primary succession unworkable in practice:

1. **Vocabulary gap.** "Primary" is used to mean both "the one active root binding" and, implicitly, "any root binding including retired ones." Callers can't reason about succession without a shared term for the distinction.

2. **API exposure gap.** `GET /info-items/{id}` and `GET /info-items` filter bindings to `deactivated_at IS NULL`. There is no way for Watcher — or any consumer — to discover what URLs an InfoItem previously used without a raw DB query.

3. **Change-bus gap.** No event fires when a primary is replaced. Watcher has no signal to start a Watch on the new URL or optionally retain a Watch on the old one.

These three gaps together mean that when a tracked URL is superseded (government document moves, regulatory page is renumbered), the surveillance value of the old URL is silently lost.

## Approach

Three coupled Archiver-side changes; Watcher changes are deferred (tracked in #44):

1. **Vocabulary.** Introduce "current primary" (active NULL-role binding) and "previous primary" (deactivated NULL-role binding) as standard terms in CLAUDE.md, the ORM model docstring, and relevant API field descriptions. No code change.

2. **API / SDK.** Add `is_active: bool` and `deactivated_at: datetime | None` to `InfoItemSourceOut`. Add `include_deactivated: bool = False` query param to `GET /info-items/{id}` (and `GET /info-items` list). When `True`, all bindings for the item(s) are returned regardless of `deactivated_at`; when `False` (default), behavior is unchanged. SDK wrapper updated to forward the param. No breaking change — additive only; minor version bump.

3. **Change-bus event.** Add `InfoItemPrimaryChangedEvent` payload type to `src/core/changes/payloads.py`. Emit from the `add_info_source` route (following the same outbox pattern as `source_revision_captured`) when a new NULL-role binding is created and a previous primary exists: query for the most-recently-deactivated NULL-role binding on the InfoItem to populate `old_info_source_id`. Both the new binding and the outbox row are flushed in the same transaction.

## Tradeoffs / alternatives

| Decision | Chosen | Rejected alternatives |
|---|---|---|
| API exposure shape | `include_deactivated=true` param — backward-compatible, consumer opt-in | Always include deactivated (breaks existing consumers); separate `/history` endpoint (unnecessary surface) |
| `is_active` placement | Always present in `InfoItemSourceOut` — consistent, no schema variance | Only when `include_deactivated=True` — confusing; schema depends on request params |
| Event emission point | At `add_info_source` route time, with DB lookback for previous primary | At deactivation time — new primary not known yet, requires two separate events; polling — adds latency and Watcher complexity |
| Event emission responsibility | Route (follows existing `source_revision_captured` pattern) | Inside `bind_info_source` tool — would add outbox coupling to a pure validation/write tool |

## Steps

- [ ] **1. Vocabulary update** — CLAUDE.md Vocabulary section: add "current primary" / "previous primary" definitions to the `InfoItemSource` row; update `src/core/models/info_item_source.py` module docstring and `add_info_source` route docstring to use the new terms.

- [ ] **2. Schema: `InfoItemSourceOut`** — add `is_active: bool` and `deactivated_at: datetime | None` fields to `InfoItemSourceOut` in `src/api/schemas/info_item.py`. Update `InfoItemOut.info_item_sources` field description.

- [ ] **3. Serializer: `info_item_source_to_out`** — populate the two new fields from the ORM row (`is_active = src.deactivated_at is None`).

- [ ] **4. Route — `GET /info-items/{id}`** — add `include_deactivated: bool = Query(default=False)` param; when `True`, load all `InfoItemSource` rows for the item (drop the `deactivated_at IS NULL` filter); pass them to `info_item_to_out`. Tests: `include_deactivated=False` returns only active (existing behavior); `True` returns active + deactivated; deactivated rows have `is_active=False`.

- [ ] **5. Route — `GET /info-items` (list)** — same `include_deactivated` param; when `True`, batch-load all bindings (not just active) and group by item. Tests: same shape as step 4.

- [ ] **6. SDK** — update `get_info_item` and `list_info_items` wrappers in `clients/python/` to accept and forward `include_deactivated`; regenerate openapi-python-client models if the schema change requires it.

- [ ] **7. Payload type: `InfoItemPrimaryChangedEvent`** — add to `src/core/changes/payloads.py`:
  ```python
  class InfoItemPrimaryChangedEvent(BaseModel):
      model_config = ConfigDict(extra="forbid")
      schema_version: int = 1
      event_type: Literal["info_item_primary_changed"] = "info_item_primary_changed"
      occurred_at: datetime
      info_item_id: str
      old_info_source_id: str
      new_info_source_id: str
  ```

- [ ] **8. Emit logic** — in `src/api/routes/info_items.py`, in `add_info_source`, after `bind_info_source` succeeds: if `body.role is None`, query for the most-recently-deactivated NULL-role binding on this InfoItem (`ORDER BY deactivated_at DESC LIMIT 1`); if found, append an `InfoItemPrimaryChangedEvent` outbox row to the session before commit. Tests: event emitted on succession; no event on first primary assignment; no event on fragment binding.

- [ ] **9. Full test sweep + lint** — `uv run pytest && uv run ruff check . && uv run ruff format --check .`

- [ ] **10. CHANGELOG + version bump** — service and SDK: minor version bump (additive API, no break). CHANGELOG entries tagged `[both]`.

## Open questions / risks

1. **API deactivate endpoint.** The `DELETE /info-items/{id}/info-sources/{source_id}` deactivation endpoint currently exists only in the dashboard (`src/dashboard/routes/info_items.py`), not in the API. For Watcher to perform primary succession programmatically (deactivate old → bind new), it needs an API-level deactivate endpoint. This plan does not add it; it should be a follow-on issue if Watcher needs it. (For now, primary succession can be performed via the dashboard.)

2. **First primary assignment.** Should a distinct `info_item_primary_set` event fire when a NULL-role binding is created with no prior primary? Currently the plan is silent — no event on first assignment. Confirm whether Watcher needs that signal.

3. **`include_deactivated` on list vs detail.** List (`GET /info-items`) with `include_deactivated=True` may be expensive at scale (many items × many historical bindings). Consider whether Watcher's discovery use case actually needs it on the list endpoint, or only on `GET /info-items/{id}`. Scope reduction is safe.
