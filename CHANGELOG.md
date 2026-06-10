# Changelog

All notable changes to archiver and its `archiver-client` SDK.

Format: human-readable narrative entries, newest first. Each change is
tagged `[service]` (server-only), `[sdk]` (client-only), or `[both]`
(coordinated).

**When to add an entry:** only when a contract-visible path changes —
`alembic/versions/` (deployed migrations), `src/api/routes/` (HTTP surface),
or `clients/python/` (SDK). Dashboard UX, test-only, lint/tooling, and
docs-only changes do not need entries. The CI changelog job enforces this.

**Versioning:** service and SDK versions are independent. Service version bumps
with any notable release. SDK version in `clients/python/pyproject.toml` bumps
only when the SDK surface changes (new methods, changed types, removals); a
service-only patch does not require an SDK bump.

## v4.2.0 (2026-06-10)

[service] **Watcher control-plane integration — provisioning hooks** (archiver#55, Steps 1–3).

`POST /api/v1/info-items` (when `initial_url` is supplied) and `POST /api/v1/info-items/{id}/info-sources` now attempt a best-effort WatchedItem provisioning/sync call to the Watcher service after committing. `PATCH /api/v1/info-sources/{id}/source-specs` pushes updated specs to Watcher for any InfoItem whose active binding points at the updated source. All three calls are post-commit and fire-and-forget: a Watcher failure is logged but does not affect the HTTP response or roll back the Archiver write. Provisioning is a no-op when `WATCHER_BASE_URL` / `WATCHER_API_KEY` are not set.

New DB column: `information.info_items.watcher_item_id VARCHAR(50) NULL` — stores the Watcher-allocated WatchedItem ID once a WatchedItem has been provisioned. Not yet surfaced in `InfoItemOut`.

## v4.1.1 (2026-06-05)

[service] **`page_title` added to `POST /api/v1/tools/preview-extraction` response.**

`PreviewExtractionResult` gains `page_title: str` — the value of the HTML `<title>` element extracted from the full document before any CSS/XPath selector narrows scope. Empty string when absent. Non-breaking additive field; existing consumers are unaffected.

## v4.1.0 (2026-06-04)

[both] **Domain registry + dashboard UX redesign** (archiver#49).

**Schema (service).**
- New `information.domains` table: `id` (ULID PK), `name` (VARCHAR 253 UNIQUE), `notes`, `is_active`, `archived_at`, `created_at`, `updated_at`.
- `info_sources.domain_name VARCHAR(253) NULL REFERENCES domains(name) ON DELETE SET NULL` — auto-populated from URL hostname at create time via `get_or_create_domain`.
- Three Alembic migrations: `create_domains_table`, `add_domain_name_to_info_sources`, `backfill_info_sources_domain_name`.

**New API routes (service).**
- `GET/PATCH/DELETE /api/v1/domains/{name}` — upsert/fetch/delete a domain.
- `POST /api/v1/domains/{name}/archive` + `/restore` — lifecycle transitions.
- `GET /api/v1/domains` — paginated list with `?is_active=` and `?archived=` filters.
- `GET /api/v1/info-sources` gains `?domain_name=` filter.
- `InfoSourceOut` gains `domain_name: str | None`.

**New SDK methods (4.1.0, backward-compatible).**
- `list_domains`, `get_domain`, `upsert_domain`, `delete_domain`, `archive_domain`, `restore_domain`.

**Dashboard.** New workflow-first layout: Register flow (`/dashboard/register`), Domains pages (`/dashboard/domains/`), InfoItem hub page (5-section scroll replacing tabs), sortableChips Alpine component, expanded home page (CTA, health strip, domain overview, Recent Activity with Item column).

## v4.0.0 (2026-06-03)

[both] **InfoSource simplification — `source_specs` list, `url` column, no fragments** (archiver#48).

Ground-up simplification of the InfoSource and InfoItemSource data model. **Breaking API changes.**

**Schema.** `info_sources` table:
- `source_spec` (single JSONB object) → `source_specs` (mutable JSONB array of extraction specs)
- `url` promoted from computed column to a real `TEXT NOT NULL` column (not unique — multiple InfoSources may share the same URL for different extraction strategies)
- `parent_info_source_id`, XOR check constraint, and fragment pagination index removed
- `schema_version` column dropped (version lives inside each spec element)

`info_item_sources` table:
- `role` column and `ck_info_item_sources_role_values` CHECK constraint dropped
- Unique index condition simplified from `deactivated_at IS NULL AND role IS NULL` → `deactivated_at IS NULL`

**SourceSpec schema.** `target` section removed. Each spec element is now `{schema_version, extraction, fingerprint}` only.

**API changes.**
- `POST /info-sources`: body changes from `{source_spec, parent_info_source_id}` to `{url, source_specs}`. No more 409 on duplicate URL — multiple InfoSources at the same URL are valid.
- `PATCH /info-sources/{id}/source-specs`: new endpoint to update the spec list without URL succession.
- `GET /info-sources`: `?parent_info_source_id=` filter replaced with `?url=` exact-match filter.
- `POST /info-items/{id}/info-sources`: `role` field removed. Every binding is a primary binding; always emits `info_item_primary_changed` on the bus.
- `POST /info-items`: `initial_source_spec` replaced by `initial_url` + `initial_source_specs`.
- `POST /api/v1/tools/preview-extraction`: `url` is now an explicit required body field; `source_spec` contains only `extraction` + `fingerprint` (no `target`).

**Bus event.** `source_revision_captured` payload: `bindings[*].role` field removed; `schema_version` bumped from 1 to 2. Consumers must branch on `schema_version` before destructuring.

**SDK.** Breaking — bumped to v4.0.0.
- `create_info_source(url, source_specs)` replaces `(source_spec, parent_info_source_id=None)`
- `add_info_source(item_id, source_id)` — `role` parameter removed
- `list_info_sources(url=)` replaces `(parent_info_source_id=)`
- `create_info_item`: `initial_url` + `initial_source_specs` replace `initial_source_spec`
- `preview_extraction(url, source_spec)` — `url` now explicit
- New: `update_info_source_specs(info_source_id, source_specs)`
- `InfoSourceOut`: `url: str`, `source_specs: list` — no `parent_info_source_id`
- `InfoItemSourceOut`: no `role` field

**Deploy coordination required.** Watcher reads `source_spec` (singular) and `source_spec["target"]["url"]`; it must be updated to read `source_specs` (array) and top-level `url` in the same deploy window. Bus consumers that branch on `bindings[*].role` must be updated to handle `schema_version: 2` before this ships.

## v3.6.0 (2026-05-29)

[both] **Primary InfoSource succession — vocabulary, API exposure, and change-bus event** (archiver#44).

Closes the three gaps that made URL succession unworkable in practice:

**Vocabulary.** "Current primary" (`role IS NULL AND deactivated_at IS NULL`) and "previous primary" (`role IS NULL AND deactivated_at IS NOT NULL`) are now standard terms in the project's guidelines. Fragment bindings do not auto-transfer when a primary is replaced.

**API / SDK.** `InfoItemSourceOut` gains `is_active: bool` and `deactivated_at: datetime | null` (always present, backward-compatible additive fields). `GET /api/v1/info-items/{id}` accepts a new `include_deactivated: bool = false` query param; when `true`, previous primaries and other deactivated source bindings are included in `info_item_sources`. New `DELETE /api/v1/info-items/{id}/info-sources/{source_id}` deactivates an active binding and returns the updated row — use to retire the current primary before binding a new one. SDK: `get_info_item` accepts `include_deactivated`; new `deactivate_info_source_binding` wrapper; `InfoItemSourceOut` model updated (v3.2.1 → v3.3.0).

**Succession guard.** `POST /info-items/{id}/info-sources` with `role=null` now returns **409 Conflict** (with `data.existing_info_source_id`) when an active primary already exists, rather than letting the DB partial-unique index raise an opaque error. The error message guides callers to the explicit DELETE → POST succession workflow.

**Change-bus event.** New `info_item_primary_changed` event emitted to `info.changes` every time a NULL-role binding is successfully created. Fields: `schema_version=1`, `info_item_id`, `old_info_source_id` (null on first assignment, non-null on succession), `new_info_source_id`. Subscribers (Watcher, Replicator) use this to discover URL succession.

## v3.5.4 (2026-05-22)

[service] **OpenAPI field descriptions on entity Out schemas** (archiver#42). All fields in `InfoItemOut`, `InfoSourceOut`, `RepSpecOut`, and `SourceRevisionOut` now carry `Field(description=...)`, surfaced in `GET /openapi.json`. No response shape changes; no SDK changes.

## v3.5.3 (2026-05-21)

[both] **`dashboard_url` field on InfoItem responses** (archiver#41). All InfoItem GET/POST endpoints (`GET /api/v1/info-items`, `GET /api/v1/info-items/{id}`, `POST /api/v1/info-items`, `GET /api/v1/tools/find-info-items`) now include `dashboard_url: str | null` in the response body. When `ARCHIVER_PUBLIC_BASE_URL` is set in the environment, `dashboard_url` is `"{ARCHIVER_PUBLIC_BASE_URL}/info-items/{id}"`; otherwise it is `null`. Consumers (e.g. Watcher's dashboard) can use this to link users directly to the Archiver detail page without separately configuring the Archiver public URL. SDK: `InfoItemOut` gains a typed `dashboard_url: None | str | Unset` attribute (v3.2.0 → v3.2.1).

## v3.5.2 (2026-05-21)

[service] **SDK version decoupled from service version** (archiver#38). The SDK
(`archiver-client`) now versions independently — its version in
`clients/python/pyproject.toml` bumps only when the SDK surface changes (new
methods, changed types, removals). A service-only release does not imply an SDK
bump. No API or SDK surface changes in this release; `archiver-client` remains
at v3.2.0.

## v3.5.1 (2026-05-21)

[service] **API Keys settings page — data-persistence and UX fixes** (archiver#37). Three mutating routes (`POST`, `DELETE`, `PATCH /dashboard/settings/api-keys`) called `session.flush()` instead of `session.commit()`; mutations appeared to succeed but rolled back silently on request completion. Fixed. Also: Alpine component registration race on hard refresh resolved (script load order); `window.open` name collision in `x-init` resolved; toggle-to-create form, column reorder (Label before Prefix), and inline Edit/Save/Cancel row workflow added.

## v3.5.0 (2026-05-20)

[service] **Admin dashboard — Epics 3–7** — Five new dashboard route families (archiver#30–#34). All routes are HTML/HTMX; no API or SDK changes.

- **Info Items** (`/dashboard/info-items/`) — paginated list, three-step wizard create, detail with Sources / Rep Specs / Revision History tabs, bind-source, assign/deactivate rep-spec, PATCH public-url, bind-revision.
- **Info Sources** (`/dashboard/info-sources/`) — paginated list with shape and URL filters, create with SourceSpec JSON editor, detail with bound items and revision history.
- **Source Revisions** (`/dashboard/source-revisions/`) — paginated list with info-source filter, detail with cache status, danger-zone clear-cache action.
- **Replication Specifications** (`/dashboard/rep-specs/`) — paginated list with provider filter, create with document JSON editor, detail with active assignments.
- **Home** (`/dashboard/`) — summary count tiles, HTMX health badge (`/dashboard/health`), recent captures table.

## v3.4.0 (2026-05-19)

[service] **API key auth migrated from env-var to DB** — `require_api_key`
now validates `X-API-Key` against SHA-256 hashes stored in
`information.api_keys` instead of the `ARCHIVER_API_KEY` env var
(archiver#29). **Deployment note:** the env var is no longer read; operators
must seed at least one `api_keys` row before upgrading or all API calls will
return 401. `last_used_at` is updated on each successful auth. New
`GET/POST/DELETE/PATCH /dashboard/settings/api-keys` routes let dashboard
users manage their keys.

## v3.3.0 (2026-05-19)

[service] **Admin dashboard — Epic 1 foundation** — New `/dashboard/` route family
(archiver#28). Adds `information.app_users` and `information.api_keys` tables;
`AppUser` is upserted on every dashboard request from `X-ExeDev-UserID` /
`X-ExeDev-Email` proxy headers. Unauthenticated requests redirect 307 to
`/__exe.dev/login`. The dashboard shell (HTMX 2.0.8 + Alpine.js 3.x, CO purple
design-token CSS) is live at `/dashboard/`. No API contract changes; no SDK
changes.

## v3.2.0 (2026-05-16)

[service] **GET /info-items and GET /info-items/{id} now populate sub-resources** —
Both endpoints previously returned `info_item_sources: []` and
`info_item_rep_specs: []` regardless of bound state (archiver#26). Both fields
now reflect active (non-deactivated) rows. The list endpoint uses two batched
`IN` queries rather than per-item lookups. Callers that relied on the empty
arrays as a sentinel should switch to checking the returned values directly.

[service] **Bus event versioning** — `SourceRevisionCapturedEvent` now
carries `schema_version: int = 1` on the wire (archiver#24). The field
is producer-emitted and consumer-readable; future incompatible reshapes
bump this monotonically rather than requiring downstream consumers to
infer the shape from field presence. Additive fields do not require a
bump.

The convention applies to all current and future event types on
`info.changes`: every payload carries `schema_version`, and consumers
must parse with extra-field tolerance (`ConfigDict(extra="ignore")` for
Pydantic mirrors). See AGENTS.md "Bus event versioning convention".

No SDK change — the SDK does not consume `info.changes`. SDK version
is bumped 1:1 with the service per the pinning policy; no regen
required.

## v3.1.0 (2026-05-16)

[service] **Performance** — `find_info_item` (`GET /api/v1/tools/find-info-items`)
substring search is now backed by PostgreSQL `pg_trgm` GIN indexes on
`information.info_items(name)` and `(description)`, so case-insensitive
`ILIKE '%q%'` queries stay sub-linear as the catalog grows
(archiver#23). The migration enables the `pg_trgm` extension. Apply with
`uv run alembic upgrade head`; no SDK changes.

[both] **Behaviour change** — cross-family extraction algorithm bindings
are now rejected at bind time (archiver#22). The Archiver codifies the
"InfoItem = fetch group" invariant: every InfoSource bound to an InfoItem
(primary, cross_check, sub_aspect) has its `extraction.algorithm`
evaluated against the primary's fetched bytes — no chaining off primary's
extracted output. Mixed content-kind families silently misextract and are
now rejected.

**Content-kind families:**
- `html_text` — `css`, `xpath`, `regex`, `full_page`
- `json` — `jsonpath`

`regex` lives in `html_text` because the dominant production use is
regex-against-HTML; `full_page` lives in `html_text` because the natural
whole-document JSON extraction is `jsonpath: $`. Both are revisitable if
new use-cases emerge.

**Wire-format:** A cross-family bind attempt now returns `422 domain`
with `errors[0].code = "algorithm_family_mismatch"`,
`errors[0].path = "/extraction/algorithm"`, and structured
`data = {"expected_family": "...", "actual_algorithm": "..."}` so clients
can render a useful message without parsing the human-readable string.

**Docs (L1):**
- `src/core/source_spec_schema/v1.json` declares the cascade contract at
  the top level in its `description`.
- `AGENTS.md` (symlinked from `CLAUDE.md`) Vocabulary section anchors the
  fetch group invariant on `InfoItem` and points at the enforcement
  modules.

**SDK:** No code changes. OpenAPI response model is unchanged (errors
flow through the existing `ErrorEnvelope`). Version is bumped 1:1 with
the service per the pinning policy; no regen required.

See archiver#22 and watcher's InfoItem-first design
(`CannObserv/watcher/docs/plans/2026-05-15-watched-item-infoitem-first-design.md`)
for the downstream consumer (selector-rot detection).

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
