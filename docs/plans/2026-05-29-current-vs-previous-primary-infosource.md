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

Four coupled Archiver-side changes; Watcher changes are deferred (tracked in #44):

1. **Vocabulary.** Introduce "current primary" (active NULL-role binding) and "previous primary" (deactivated NULL-role binding) as standard terms in CLAUDE.md, the ORM model docstring, and relevant API field descriptions. No code change.

2. **API / SDK.** Add `is_active: bool` and `deactivated_at: datetime | None` to `InfoItemSourceOut`. Add `include_deactivated: bool = False` query param to `GET /info-items/{id}`. When `True`, all bindings for the item are returned regardless of `deactivated_at`; when `False` (default), behavior is unchanged. Also add `DELETE /api/v1/info-items/{id}/info-sources/{source_id}` (mirroring the existing dashboard endpoint). SDK wrappers updated. No breaking change — additive only; minor version bump.

3. **Explicit succession workflow.** When `POST /info-items/{id}/info-sources` is called with `role=null` and an active primary already exists, `bind_info_source` raises a typed `ActiveRootAlreadyExistsError` (carrying the existing `info_source_id`). The route returns 409 with a structured payload identifying the current primary and guiding the caller to deactivate it first via the DELETE endpoint. Auto-deactivation is deliberately not performed — the succession step should be explicit to avoid accidental replacement.

   Normal succession workflow:
   1. `DELETE /api/v1/info-items/{id}/info-sources/{old_source_id}` — deactivate current primary
   2. `POST /api/v1/info-items/{id}/info-sources` with `role=null` — bind new primary; event emitted

4. **Change-bus event.** Add `InfoItemPrimaryChangedEvent` payload type to `src/core/changes/payloads.py` with `old_info_source_id: str | None` (null on first assignment). Emit from the `add_info_source` route every time a NULL-role binding is successfully created: if a previous primary exists (most-recently-deactivated NULL-role binding), populate `old_info_source_id`; otherwise emit with `old_info_source_id=null` to signal first primary assignment. Both binding and outbox row flushed in the same transaction.

## Tradeoffs / alternatives

| Decision | Chosen | Rejected alternatives |
|---|---|---|
| API exposure shape | `include_deactivated=true` param on `GET /info-items/{id}` — backward-compatible, consumer opt-in | Always include deactivated (breaks existing consumers); separate `/history` endpoint (unnecessary surface); also on list endpoint (deferred — not needed by Watcher's use case) |
| `is_active` placement | Always present in `InfoItemSourceOut` — consistent, no schema variance | Only when `include_deactivated=True` — confusing; schema varies by request params |
| Succession UX | Explicit two-step (DELETE old → POST new); 409 with guidance on conflict | Auto-deactivate on POST — destructive without explicit intent; could silently replace primary on a caller mistake |
| Atomic succession endpoint | Future `PUT /info-items/{id}/primary-source` noted as ergonomic option; not in scope | Would couple deactivation + bind into one call; deferred until Watcher's actual workflow is known |
| Event on first assignment | `old_info_source_id: str \| None = None` on `InfoItemPrimaryChangedEvent` — single event type covers both first assignment (old=null) and succession (old=str) | Separate `info_item_primary_set` event type — unnecessary split; consumers branch on `old_info_source_id` |
| Event emission point | At `add_info_source` route time, with DB lookback for previous deactivated primary | At deactivation time — new primary not known yet; polling — adds latency and Watcher complexity |
| Event emission responsibility | Route (follows existing `source_revision_captured` pattern) | Inside `bind_info_source` tool — adds outbox coupling to a pure validation/write tool |

## Steps

- [ ] **1. Vocabulary update** — CLAUDE.md Vocabulary section: add "current primary" / "previous primary" definitions to the `InfoItemSource` row; update `src/core/models/info_item_source.py` module docstring and `add_info_source` route docstring to use the new terms.

- [ ] **2. Schema: `InfoItemSourceOut`** — add `is_active: bool` and `deactivated_at: datetime | None` fields to `InfoItemSourceOut` in `src/api/schemas/info_item.py`. Update `InfoItemOut.info_item_sources` field description.

- [ ] **3. Serializer: `info_item_source_to_out`** — populate the two new fields from the ORM row (`is_active = src.deactivated_at is None`).

- [ ] **4. Route — `GET /info-items/{id}`** — add `include_deactivated: bool = Query(default=False)` param; when `True`, load all `InfoItemSource` rows for the item (drop the `deactivated_at IS NULL` filter); pass them to `info_item_to_out`. Tests: `include_deactivated=False` returns only active (existing behavior); `True` returns active + deactivated; deactivated rows have `is_active=False`.

- [ ] **5. SDK** — update `get_info_item` wrapper in `clients/python/` to accept and forward `include_deactivated`; regenerate openapi-python-client models if the schema change requires it.

- [ ] **6. `ActiveRootAlreadyExistsError` in `bind_info_source`** — before inserting a NULL-role binding, query for an existing active NULL-role binding; if found, raise `ActiveRootAlreadyExistsError(existing_info_source_id=...)`. In `add_info_source` route: catch it and return 409 `conflict` with `data={"existing_info_source_id": str(...)}` and a message explaining the DELETE-then-POST succession workflow.

- [ ] **7. Extract shared deactivation tool** — add `deactivate_info_item_source_binding(session, item_id, source_id)` to `src/core/tools/` (raises typed `BindingNotFoundError` when not found or already deactivated). Refactor existing dashboard `DELETE /{item_id}/info-sources/{source_id}` to call it.

- [ ] **8. `DELETE /api/v1/info-items/{id}/info-sources/{source_id}`** — add to `src/api/routes/info_items.py`; calls the shared tool from step 7; translates `BindingNotFoundError` → 404. SDK: add `deactivate_info_source_binding(info_item_id, info_source_id)` wrapper. Tests: 200 on success; 404 on missing/already-deactivated; verify `deactivated_at` is set.

- [ ] **9. Payload type: `InfoItemPrimaryChangedEvent`** — add to `src/core/changes/payloads.py`:
  ```python
  class InfoItemPrimaryChangedEvent(BaseModel):
      model_config = ConfigDict(extra="forbid")
      schema_version: int = 1
      event_type: Literal["info_item_primary_changed"] = "info_item_primary_changed"
      occurred_at: datetime
      info_item_id: str
      old_info_source_id: str | None  # None = first primary assignment
      new_info_source_id: str
  ```

- [ ] **10. Emit logic** — in `src/api/routes/info_items.py`, in `add_info_source`, after `bind_info_source` succeeds and `body.role is None`: query for the most-recently-deactivated NULL-role binding (`ORDER BY deactivated_at DESC LIMIT 1`); append an `InfoItemPrimaryChangedEvent` outbox row with `old_info_source_id=str(...)` if found, or `old_info_source_id=None` on first assignment. Tests: event with `old=str` on succession; event with `old=None` on first assignment; no event on fragment binding.

- [ ] **11. Full test sweep + lint** — `uv run pytest && uv run ruff check . && uv run ruff format --check .`

- [ ] **12. CHANGELOG + version bump** — service and SDK: minor version bump (additive API, no break). CHANGELOG entries tagged `[both]`.

## Open questions / risks

None — all design questions resolved. Atomic succession ergonomics deferred to [#45](https://github.com/CannObserv/archiver/issues/45).
