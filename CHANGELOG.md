# Changelog

All notable changes to archiver and its `archiver-client` SDK. Versions track
the service version; the SDK is pinned 1:1.

Format: human-readable narrative entries, newest first. Each change is
tagged `[service]` (server-only), `[sdk]` (client-only), or `[both]`
(coordinated). Update this file when merging changes to `main` that
affect callers (new endpoints, new SDK methods or types, behaviour
changes, breaking changes, public-surface fixes). Internal refactors,
test-only changes, and docs-only changes do not need entries.

## v3.0.0 (2026-05-16)

[both] **Breaking** — `info_item_sources.role` semantics are refactored
(archiver#21). The primary binding is now implicit: the unique active
root-shaped (URL-bearing) binding on an InfoItem is its primary by
construction, with `role IS NULL`. `role` is reserved for fragment-shaped
bindings and takes one of `'cross_check'` (same content, different
selector — used for selector-rot detection) or `'sub_aspect'` (different
content area on the same fetched page — operator-watchable).

The `'primary'` and `'secondary'` role strings are removed. Callers that
sent `role='primary'` get a 422 with `kind=body` (Pydantic Literal
rejection); callers that omitted `role` previously got a 422 (it was
required) and now succeed (defaults to `null`).

**Schema enforcement:**
- DB: `CHECK (role IS NULL OR role IN ('cross_check', 'sub_aspect'))`
  and unique active root binding per InfoItem
  (`uq_info_item_sources_active_root`).
- App: `bind_info_source` validates shape consistency (NULL ↔ root,
  fragment role ↔ fragment source) and that fragment bindings share
  the InfoItem's active root.

**Change-bus payload reshaped.** `SourceRevisionCapturedEvent.info_item_ids:
list[str]` is replaced by `bindings: list[InfoItemBinding]` where each
binding carries `{info_item_id, role}`. Consumers filter on `role` per
their semantics (Replicator typically wants `role IS NULL` only).

**SDK changes:**
- `add_info_source(info_item_id, info_source_id, role=None)` — `role` is
  now optional. Type is `Literal['cross_check', 'sub_aspect'] | None`.
- Regenerated models: `InfoItemSourceCreate.role` and
  `InfoItemSourceOut.role` are nullable; create-side enforces the enum.

**Migration:** Single Alembic revision normalizes existing
`role='primary'` rows to NULL, swaps the partial-unique index, and adds
the CHECK constraint. Pre-prod (no live data), so no compatibility shim.

See archiver#21 and CannObserv/watcher#157 (Watch reshape that this
unblocks).

## v2.2.0 (2026-05-13)

[both] Additive, non-breaking — `POST /source-revisions` now accepts an
optional `source_revision_id` in the request body. Watcher uses this to
pre-allocate the ULID so it can write the `content_cache_uri` scratch
file under its final `<source_revision_id>.bin` filename BEFORE the
POST round-trips (rather than holding bytes in memory or in a relational
column until the server returns an id).

Idempotency on `(info_source_id, content_fingerprint)` still wins on
re-POST — when an existing row matches, the server returns that row's id
and ignores the client-supplied value. A supplied ULID that's already
bound to a *different* `(info_source_id, content_fingerprint)` pair
returns **409 Conflict** with `data.existing_info_source_id` and
`data.existing_content_fingerprint` for triage.

**New SDK kwarg:**
- `post_source_revision(..., source_revision_id=None)` — pass-through to
  the body field. Default `None` preserves prior behavior (server
  allocates).

See CannObserv/watcher#156.

## v2.1.0 (2026-05-12)

[sdk] **Breaking (semi-private)** — the hand-written `ValidationIssue`
dataclass returned by `validate_source_spec`, `validate_rep_spec`, and
`validate_rep_fields` is replaced by the generated `FieldError` model
(`archiver_client.FieldError`). The two had the same shape on the wire,
but `ValidationIssue` silently dropped the server's optional `code`
field; the generated `FieldError` surfaces it. `ValidationIssue` was
never in `__all__`, so direct typed-import callers should be rare —
those that exist must rename to `FieldError`.

**New public exports:** `FieldError`, `ValidationResult`. Both now live
in `archiver_client.__all__` so consumers can type-annotate validate-tool
results directly. See archiver#19.

## v2.0.1 (2026-05-12)

[sdk] **Bug fix** — `ValidationIssue.path` returned by `validate_source_spec`,
`validate_rep_spec`, and `validate_rep_fields` is now a JSON-Pointer string
(e.g. `"/target"`), matching the server's `FieldError.path` contract.
Previously the parser ran `list(...)` over the server's string and emitted a
character-split list (`['/', 't', 'a', ...]`). The dataclass field type
changed from `list[str | int]` to `str`. `ValidationIssue` is not in
`__all__`, so impact on typed consumers is minimal. See archiver#17.

## v2.0.0 (2026-05-12)

[both] **Breaking** — all error response bodies now use a unified envelope
shape (`{detail: {kind, message, errors[], data}}`). `InformationError`
subclasses surface `.kind`, `.message`, `.errors`, `.data` parsed from the
envelope. New `Conflict` subclass of `InformationError` is raised for 409
responses; inspect `.data` (e.g. `existing_info_source_id`) for the bind
target. See archiver#15.

[sdk] **SDK surface fix** — `PageInfoItemOut` and `PageInfoSourceOut` are
now re-exported from `archiver_client` directly. Both were documented as
v1.2.0 exports but never landed in `__all__`. Callers no longer need to
reach into `archiver_client.generated.models.*` to type-annotate list
responses. See archiver#14.

## v1.3.0 (2026-05-11)

[both] Additive over v1.2.0 — backwards compatible. New `/rep-specs`
endpoints with matching SDK methods.

**New SDK methods:**
- `create_rep_spec(provider, name, document) -> RepSpecOut`
- `get_rep_spec(rep_spec_id) -> RepSpecOut`
- `list_rep_specs(*, provider=None, limit=None, offset=None) -> PageRepSpecOut`

**New typed exports:** `RepSpecOut`, `PageRepSpecOut`.

## v1.2.0 (2026-05-11)

[both] **Breaking** — list endpoints now return a `Page` envelope instead of a bare list.

**Changed SDK signatures:**
- `list_info_items(*, limit=None, offset=None) -> PageInfoItemOut`
- `list_info_sources(*, parent_info_source_id=None, limit=None, offset=None) -> PageInfoSourceOut`

Both envelopes carry `items`, `has_more`, `limit`, `offset`. `limit` defaults to
100 server-side (max 500); `offset` defaults to 0. Pass `None` from the SDK to
accept server defaults. `has_more` is derived via a `limit+1` probe — no total
count is computed. Ordering is stable across pages via a unique tiebreaker on
the row id, so offset-paged iteration is safe.

**New typed exports:** `PageInfoItemOut`, `PageInfoSourceOut`.

**Migration for callers:**
```python
# Before (v1.1.0)
items = await client.list_info_items()
for it in items: ...

# After (v1.2.0)
page = await client.list_info_items()
for it in page.items: ...
while page.has_more:
    page = await client.list_info_items(offset=page.offset + page.limit)
    for it in page.items: ...
```

## v1.1.0 (2026-05-10)

[both] Additive over v1.0.0 — every v1.0.0 method retains its signature and return type.

**New SDK methods:**
- `create_info_source(source_spec, *, parent_info_source_id=None) -> InfoSourceOut`
- `get_info_source(info_source_id) -> InfoSourceOut`
- `list_info_sources(*, parent_info_source_id=None) -> list[InfoSourceOut]` *(return shape updated to `PageInfoSourceOut` in v1.2.0)*

**New typed export:** `InfoSourceOut`.

[service] **Implicit server behaviour change:** `POST /info-items` with an
`initial_source_spec.target.url` that already has an InfoSource row now
returns **409 Conflict** (with `existing_info_source_id` and `url` in
`detail`). Previously the duplicate would surface as a 500
`IntegrityError`. SDK callers that pattern-match on status codes (Watcher
retry logic in particular) should treat 409 as "InfoSource already
exists; bind via `add_info_source` instead of recreating."

## v1.0.0 (2026-05-09)

[both] Phase 4 cutover. Replaces the retired v0.x `InfoSpec` model with the
`InfoItem`/`InfoSource`/`SourceRevision`/`RepSpec` v2 model. Not
compatible with v0.x clients.
