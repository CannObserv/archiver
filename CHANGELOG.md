# Changelog

All notable changes to archiver and its `archiver-client` SDK.

Format: human-readable narrative entries, newest first. Each change is
tagged `[service]` (server-only), `[sdk]` (client-only), or `[both]`
(coordinated).

**When to add an entry:** only when a contract-visible path changes —
`alembic/versions/` (deployed migrations), `src/api/routes/` (HTTP surface),
`src/api/schemas/` (Pydantic request/response models), or `clients/python/`
(SDK). Dashboard UX, test-only, lint/tooling, and docs-only changes do not
need entries. The CI changelog job and the pre-push guard both enforce this
with the same path regex.

**Versioning:** service and SDK versions are independent. Service version bumps
with any notable release. SDK version in `clients/python/pyproject.toml` bumps
only when the SDK surface changes (new methods, changed types, removals); a
service-only patch does not require an SDK bump.

## v4.7.0 (2026-08-10)

[both] **WatchSpec — Archiver owns scheduling policy, SDK v5.2.0** (archiver#150, step 4b of the #137 epic). Cadence and active/paused state were Watcher's, round-tripped over the SDK; they become `information.info_items.watch_spec`, a validated JSONB document on the registry's own row.

The document is `{"schema_version": 1, "active": true, "interval": "1d"}`, validated against the new `src/core/watch_spec_schema/v1.json`. `active` is required — `false` means *registered but deliberately paused*, which is distinct from revocation. **`interval` is optional, and absent means "the consumer applies its own default"**: Watcher's per-domain `default_schedule_config` is a real fallback layer, so a resolved interval on every row would silently retire it. The column's server default is `{"schema_version": 1, "active": true}` for the same reason — the migration must not fabricate a cadence for rows that never had one. The schema validates the interval *grammar* (`^[0-9]+[smhd]$`); the four options the dashboard offers stay in `src/dashboard/cadence.py`.

New HTTP surface: `PUT /info-items/{id}/watch-spec` (whole-document replace, not a merge — a merge would make "no interval" unreachable once one had been set) and `POST /tools/validate-watch-spec`. `watch_spec` is additive on `InfoItemOut`. Both are generated-only on the SDK; no hand-written wrapper, because no SDK consumer needs one yet.

**No dashboard behaviour changes.** Pause/resume still PATCHes Watcher and cadence still displays Watcher's `default_schedule_config`; the control-plane cutover lands with the announcement channel, so the flip happens once against a live path rather than leaving an authoritative-looking column that nothing enforces.

`scripts/import_watch_specs.py` carries the live values across. It joins from Watcher's `archiver_info_item_id` rather than Archiver's drift-prone `watcher_item_id`, dry-runs by default, exits non-zero on anomalies, and is idempotent **by design** — it runs once here and again immediately before the announcement producer's first publish, because Watcher stays authoritative in between.

## v4.6.0 (2026-08-09)

[both] **SourceRevision records observation provenance — `source_media_type`, `spec_fingerprint`, `command_id`, SDK v5.1.0** (archiver#139, step 3 of the #137 epic). Three new nullable `information.source_revisions` columns, all three additive on `SourceRevisionOut`.

They exist because the forthcoming `content.revisions` consumer receives them on `SourceRevisionObservedEvent` (cannobserv#301) and had nowhere to put them. Read-only for now: no request body accepts them, so rows written through `POST /source-revisions` carry `null` in all three, and existing rows are unaffected — no backfill.

- **`source_media_type`** is what the *origin* served. It does not duplicate `content_media_type`, which describes the text extracted under `source_specs` — an HTML page is served `text/html` and the text extracted from it is not, so the two differ for one revision and neither substitutes for the other. It inherits `BlobAvailableEvent.media_type`'s normalization (charset dropped, `application/octet-stream` for an absent header), so it cannot express "the origin sent no `Content-Type` at all".
- **`spec_fingerprint`** identifies which `source_specs` the producer extracted under. **Recorded and compared, never enforced** — a value that disagrees with the InfoSource's current specs does not invalidate the revision and does not fail the write. archiver#140 moves spec delivery onto an eventually-consistent announcement channel, making "extracted under a superseded spec" an expected transient state. Without the column, *the origin changed*, *our extraction spec changed*, and *the producer was behind on announcements* are one indistinguishable new fingerprint. The comparison itself landed later in this same release — see the `spec_match` / `spec_position` entry below.
- **`command_id`** correlates the revision back to the `content.fetch` command that produced the bytes.

SDK: `SourceRevisionOut` gains the three optional fields; no wrapper signature changes. Consumers on v5.0.0 keep working — additive response fields only.

[service] **Archiver ingests SourceRevisions from the bus — new `content.revisions` consumer** (archiver#139, answers #118). Its **first consumer role**; it has only ever produced. Watcher publishes `source_revision_observed` (cannobserv#301, co-core ≥0.8) and the registry decides what to persist, replacing Watcher's `POST /source-revisions`.

The write goes through the same `record_revision` call the HTTP route makes, so `source_revision_captured` on `info.changes` is unchanged for existing subscribers — the outbox row still commits in the revision's transaction, and the event is still keyed on `source_revision_id`. Idempotency is the existing `(info_source_id, content_fingerprint)` constraint, which makes at-least-once redelivery a no-op emitting no duplicate event. Archiver allocates the `source_revision_id`: it is deliberately absent from the wire, because a service that does not own the registry does not mint registry ids.

Operationally:

- **Group `archiver.revisions`** on `content.revisions`, created at `0` rather than `$` so nothing published before the group existed is dropped. Consumer-group lag is now Archiver's own health concern for the first time — threshold work is #130.
- **Gated on `ARCHIVER_BUS_CONSUMER=1`**, set only in `deploy/archiver.service`. Presence of `ARCHIVER_REDIS_URL` is not sufficient: consuming *removes* messages from the group, so a stray process sourcing `/etc/archiver/.env` would silently swallow revisions. Same never-in-an-env-file rule as `ARCHIVER_ALLOW_PRODUCTION_DB`.
- **Ack strictly after commit.** A crash between the two redelivers into an idempotent write; the other order loses a revision.
- **Unknown `info_source_id` is ack-and-drop** with a WARNING — the registry is the authority on what exists. Unusable or undecodable frames go to `content.revisions.dlq`; transient failures stay pending for redelivery or `XAUTOCLAIM`.
- **`blob_uri` lands in `content_cache_uri`, not durable storage.** It is a VM-local `file://` on Replicator's host with a TTL clocked from last fetch reference. An absent `blob_expires_at` records absence rather than a guessed horizon.

**`spec_fingerprint` is now compared, not only recorded — new `spec_match` / `spec_position`** (cannobserv#309, co-core ≥0.8.1). This entry originally shipped the recording half alone, because the contract said only that the value be *stable for a given spec*: Archiver held the authoritative `source_specs` with no way to derive the same string the producer had, and reimplementing the producer's derivation would have flagged mismatches on specs that never changed. co-core now owns the derivation (`co_core.pure.extract`), so both sides run one function.

Two new nullable columns, additive on `SourceRevisionOut`, computed at ingest on **both** write paths (inert on the HTTP path, which reports no fingerprint):

- **`spec_match`** — `current` (matched a spec the registry still holds), `superseded` (**the flag**: well-formed and matching none of them), or `incomparable`. `NULL` means nothing was reported to compare.
- **`spec_position`** — which `source_specs` index the producer extracted under, set only for `current`. `0` is the primary spec; **anything higher is selector rot in progress** — the primary stopped matching and the producer fell through to a cross-check alternative. Arguably the more actionable of the two signals, and it exists only because the derivation is per-spec rather than over the whole list.

**Every uncertain branch resolves to `incomparable`, never `superseded`** — an unrecognised derivation tag, a malformed value, or `source_specs` of our own with no canonical form. That asymmetry is the design: a false mismatch is indistinguishable from the real condition the field exists to detect. Two of those rules come from the contract rather than from registry policy — an absent fingerprint is not a mismatch (a producer that has not adopted the field yet would otherwise flag on every revision), and a derivation this co-core cannot compute must skip.

All three `spec_*` columns track the **most recent** observation of a revision, not the one that created it: a re-observation is an idempotent no-op for the row's identity but refreshes the verdict (and emits no event). Otherwise a registry that moved to a new spec would leave already-recorded content asserting `current` for a spec it no longer holds — and a producer stuck on the old spec, the case the flag exists for, would never raise one. The WARNING fires on a change of verdict rather than on every at-least-once redelivery.

Still **flag, never reject**: nothing here fails a write, and `superseded` / fallback positions are logged at WARNING alongside being stored. Because appending a cross-check alternative changes the list but not the fingerprint of the spec in use, a spec edit does not flag every subsequent revision — the flag fires when the fallback actually moves.

Dependency floor moves to `co-core>=0.8.1,<0.9` (from `>=0.8,<0.9`); the derivation does not exist below it.

**Minor validation tightening on `content_fingerprint`.** The rule moved to `src/core/fingerprints.py` so both write paths share it, and testing it directly surfaced a hole: the pattern was `^sha256:[0-9a-f]{64}$` matched with `re.match`, and Python's `$` also matches immediately *before* a trailing newline — so `"sha256:<hex>\n"` was accepted. Under the `(info_source_id, content_fingerprint)` uniqueness key that is a second spelling of one digest, and therefore a second row rather than an idempotent no-op. Now matched with `fullmatch`. A request body whose fingerprint carries a trailing newline changes from **201** to **422**; no stored row can have been affected without already being a duplicate.

`POST` and `PATCH /source-revisions` are unchanged and stay — they are the authoring/backfill path, and retiring them is a separate call from retiring Watcher's use of them (CannObserv/watcher#253, which must land *after* this).

## v4.5.1 (2026-07-29)

[service] **Outbox publisher dead-letters poison rows instead of retrying them forever** (archiver#107). New nullable `information.changes_outbox.dead_lettered_at` column; the unpublished partial index (`ix_changes_outbox_unpublished_created`) is narrowed to `published_at IS NULL AND dead_lettered_at IS NULL`.

The drain loop now distinguishes *permanent* from *transient* per-row failures. A **deterministic** build failure — unknown `event_type`, or an unvalidatable payload (e.g. the pre-`bindings` legacy `source_revision_captured` rows that flooded the journal on the archiver#109 activation) — stamps `dead_lettered_at` on the first failure, so the row stops being selected. A **transient** publish failure (Redis down/slow/loading — the builtin and redis-py `ConnectionError`/`TimeoutError` plus `BusyLoadingError`) retries **indefinitely** and is exempt from the dead-letter ceiling, so a long-but-genuine outage can never silently drop a valid event. A high ceiling (`MAX_PUBLISH_ATTEMPTS = 100000`, ~a day of continuous failure) is a pure backstop that retires only a **non-transient** publish failure (e.g. a server-side `ResponseError`/`WRONGTYPE`) that persists past it. Dead-lettering logs at ERROR with `row_id` / `event_type` / `reason`; `payload` + `last_error` are kept in-row for post-mortem. No API/schema/SDK surface change; the `.dlq` stream + replay story is deferred to Phase 3 (Replicator).

## v4.5.0 (2026-07-28)

[service] **Change-bus producer swapped onto the shared co-core bus layer; `info.changes` wire envelope reshaped** (archiver#106, Phase 2b of #72). Depends on **co-core / co-core-aio v0.5.2** (cannobserv#261 bus layer + cannobserv#263 redis-pin fix).

The outbox drain loop no longer hand-rolls the XADD. It now reconstructs each stored event into its typed co-core model and publishes via `co_core_aio.bus.AsyncBusPublisher.execute(BusPublish(...))`, building the wire fields with `co_core.pure.adapters.bus.envelope.to_wire`. The typed payloads (`SourceRevisionCapturedEvent` / `InfoItemPrimaryChangedEvent` / `InfoItemBinding`) moved to **co-core** (`co_core.pure.models.changes`, lifted in cannobserv#261); archiver's local `src/core/changes/payloads.py` and the ad-hoc `RedisLike` Protocol are deleted. Emit sites now build the strict `*Emit` subclasses (`extra="forbid"`).

- **Wire change (`info.changes` consumers).** The XADD field set changed from the ad-hoc `{key, payload}` to the canonical envelope — `key` / `payload` / `event_type` / `schema_version` / `occurred_at` / `content_type`. `payload` is unchanged (the full event JSON, self-describing). **Safe now — nothing consumes `info.changes` yet** (Replicator, the first consumer, arrives in Phase 3).
- **Idempotency-key fix.** The old publisher keyed *every* event on `source_revision_id`, so `info_item_primary_changed` shipped with an empty `key`. co-core's `idempotency_key` now derives the correct per-type key (the `{info_item_id}:{new_info_source_id}` composite for primary-changed).
- **Outbox unchanged** — still archiver-owned, still the producer-side delivery guarantee. Event payloads (schemas, `schema_version` values) are byte-for-byte identical; only the transport wrapper and the source-of-truth for the models changed.
- **Dependency:** `co-core-aio` pin gains the `[bus]` extra. Its extra briefly pinned `redis<7` — a spurious *client*-library ceiling (the Redis **server** ≥7.0 floor it was derived from can't be expressed as a client pin, and redis-py 7.x has no relevant break); fixed upstream in **cannobserv#263** (co-core/co-core-aio **v0.5.2** relaxes it to `redis<8`). Archiver locks co-core/co-core-aio **0.5.2** and stays on redis-py **7.4.1** — no net redis change.

Also resolves archiver#105 (transitive co/v1 wire bump, wp#568) for the archiver — the service has no direct co/v1 call sites, so being on co-core v0.5.1 is the whole remedy.

## v4.4.0 / SDK v5.0.0 (2026-07-21)

[both] **Retire the `info_item_source_revisions` pin table — `POST /info-items/{id}/source-revisions` removed, SDK v5.0.0** (archiver#101, 2026-07-21). **Breaking.**

The per-item revision *pin* table served two purposes that both dissolved across earlier refactors: an automatic content timeline (never wired — post-#185 the standalone Watcher writes `source_revisions`, not pins) and explicit revision pinning (zero automatic writers, zero downstream consumers). An InfoItem's content timeline is a query over its InfoSource bindings (active primary + previous primaries), not this table. No bus event, Replicator, or other reader depended on it.

Service changes:
- **Removed** `POST /api/v1/info-items/{info_item_id}/source-revisions` (the `bind_source_revision` endpoint) and its request/response models `InfoItemSourceRevisionCreate` / `InfoItemSourceRevisionOut`.
- **Migration** `4413805453dd` drops `information.info_item_source_revisions`. **Irreversible data drop** — the table had a public write path, so a production DB may hold operator-created pin rows; `downgrade` recreates the table but NOT its rows. The migration logs the pre-drop row count; confirm it is acceptable before `alembic upgrade head` on production. No data any *reader* consumed is lost.
- Core: removed the `bind_revision` tool and the `InfoItemSourceRevision` ORM model.
- The `source_revision_captured` and `info_item_primary_changed` bus events are unchanged — neither referenced pins.

SDK changes (v4.3.0 → **v5.0.0**):
- **Removed** `ArchiverClient.bind_revision(...)` and the `InfoItemSourceRevisionOut` export. Callers pinning revisions have no replacement — the operation no longer exists. The top-level `post_source_revision` / `patch_source_revision_cache` methods (the `/source-revisions` record + cache endpoints) are unaffected.

## v4.3.0 (2026-07-20)

[both] **RepSpec documents are editable while draft — `PATCH /rep-specs/{id}`, SDK v4.3.0** (archiver#83, 2026-07-20).

RepSpecs were POST/GET-only and immutable once written. They are now *tiered*-mutable. Design record: `docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md`.

| Tier | Condition | Mutable |
|---|---|---|
| 1 | always | `name` |
| 2 | **draft** — zero assignment rows, active *or* deactivated | `document` |
| 3 | any assignment row exists | nothing — clone + migrate (#95) |

The freeze is not conservatism for its own sake: `InfoItemRepSpec` is effective-dated, so an assignment row asserts which document produced the artefact at its `public_url`. Rewriting an assigned spec's document in place would make that unverifiable. The draft gate therefore counts **all** assignment rows, including deactivated ones — a deactivated assignment still means a replication run happened under that document.

`provider` is frozen in every tier, drafts included. Document updates are whole-document **replacement**, not merge patch (merge cannot express key removal, which would make `object_options` entries unremovable under the envelope's `additionalProperties: false`).

Service changes:
- New `PATCH /api/v1/rep-specs/{rep_spec_id}` accepting `{name?, document?}` (`extra: forbid`). **Omitting** a field leaves it unchanged; explicitly sending `null` is a 422 (both columns are `NOT NULL`, so `null` has no "clear" meaning — conflating it with omission would silently swallow a malformed request). Omitting both is a no-op. Errors: 404 `lookup`, 409 `conflict` with `data.assignment_count`, 422 `schema` (validation failure or attempted provider change).
- `RepSpecOut` gains `updated_at: datetime | None` (additive) — **required and nullable**, matching the other nullable projections (`InfoItemRepSpecOut.deactivated_at` etc.): the server always emits it, null meaning never edited. Deliberately not backfilled from `created_at`.
- All three write paths that create or gate assignments now take `SELECT … FOR UPDATE` on the RepSpec row: `update_rep_spec` (when a document edit is requested — a name-only edit consults no gate and needs no lock), `assign_rep_spec`, and the atomic `POST /info-items` path via the new `lock_rep_specs` helper, which inserts `InfoItemRepSpec` rows directly rather than going through `assign_rep_spec`. The draft gate is a read-then-write; without the lock, under READ COMMITTED a concurrent assignment could be inserted between the count and the commit, landing a rewritten document on an assigned spec. `lock_rep_specs` sorts IDs before locking so two concurrent creates naming the same specs in different order cannot deadlock.
- Migration `291c95e00110` adds the nullable `information.rep_specs.updated_at` column. No backfill.
- Dashboard: document editor on the RepSpec detail screen for drafts; read-only "frozen" notice with the assignment count otherwise. Mirrors the InfoSource source-specs editor (HTMX in-place swap, toast on success, inline `role="alert"` error preserving submitted text, non-HTMX 303/422 fallback).

SDK surface changes (4.2.0 → 4.3.0):
- New `update_rep_spec(rep_spec_id, *, name=None, document=None) -> RepSpecOut`. Omitted kwargs are not sent (omit-on-`None`, matching `upsert_domain`) — so the SDK never triggers the server's explicit-`null` rejection. Raises `NotFound`, `Conflict` (`data["assignment_count"]`), or `ValidationError`.
- `RepSpecOut.updated_at` available on responses (additive, required-and-nullable).

## v4.2.3 (2026-07-19)

[sdk] **SDK v4.2.0 — generated tree regenerated (gains `/domains`), typed Domain methods, drift-gated** (archiver#92, 2026-07-20).

The committed `generated/` tree was stale (pre-v4.1: no `api/domains` module, no `DomainOut`/`PageDomainOut`, untyped `/health`). Regenerated from the current 27-path dashboard-pruned spec; a committed `clients/python/archiver-openapi.json` snapshot is now the contract-of-record (mirrors the watcher pattern), `regen.sh` refreshes snapshot + tree in lockstep, and the CI `client-drift` job now also gates `archiver` via `scripts/check_client_drift.py`.

SDK surface changes (4.1.0 → 4.2.0):
- `list_domains` returns `PageDomainOut`; `get_domain`, `upsert_domain`, `archive_domain`, `restore_domain` return `DomainOut` (previously raw dicts). `delete_domain` still returns `None`. Call signatures unchanged; `upsert_domain` keeps omit-on-`None` PATCH semantics.
- `list_info_sources` gains a `domain_name=` filter kwarg (additive).
- `InfoSourceOut.source_specs` (and the other spec-list response fields) now hold typed item models instead of plain dicts — use `.to_dict()` to recover the dict form. Inputs still accept plain dicts.
- `archiver_client.__version__` fixed — it was left at `4.0.0` by the 4.1.0 bump (the existing `test_version.py` guard now passes).

`GET /api/v1/domains`, `/info-items`, `/info-sources`, and `/rep-specs` declared `offset` with `ge=0` but no ceiling, so a value beyond `2**63 - 1` reached SQL as `OFFSET $2::BIGINT` and asyncpg raised `DataError`, surfacing as a 500. All four routes now declare `le=2**63 - 1`, so FastAPI returns a 422 validation error. Offsets up to and including `2**63 - 1` remain accepted. Consistent with the existing convention: the API 422s on out-of-range pagination params where the dashboard clamps (see `docs/UI.md`).

[service] **`build_id` on `GET /health`; BUILD_ID stamp marks dirty trees** (archiver#89).

`GET /health` now returns `{"status": "ok", "build_id": ...}` — `build_id` is read from the `BUILD_ID` environment variable and is `null` when unset. Additive field; existing consumers checking `status` are unaffected. New response model `HealthOut` in `src/api/schemas/health.py`.

The systemd unit's BUILD_ID stamp (`deploy/archiver.service`) switches from `git rev-parse --short HEAD` to `git describe --always --dirty`, so a service started from an uncommitted working tree reports `<sha>-dirty` instead of a clean SHA. Deploy note: the unit-file change takes effect only after the operator reinstalls the unit (copy to /etc/systemd/system + `systemctl daemon-reload`).

## v4.2.2 (2026-07-19)

[service] **Restore `ix_info_sources_domain_name`** (archiver#82).

Migration `fa99ef9f1dbd` recreates the index on `information.info_sources.domain_name`. It was dropped in `fff827419c6c` together with `fk_info_sources_domain_name` as ORM/DB alignment cleanup after #48 removed both from the model — not because the index was unwanted. Three read paths filter or group by the column (domain detail listing, its heading COUNT, domain list GROUP BY) and the table is expected to grow. **The foreign key stays dropped** — that remains a deliberate model decision; only the index returns.

No API or SDK surface change. Deploy note: plain `CREATE INDEX`, which takes a brief write lock; negligible at current table size, but use `postgresql_concurrently` if applying to a large instance.

## v4.2.1 (2026-06-13)

[service] **Health badges: distinguish non-200 from network error** (archiver#59).

`GET /dashboard/health/watcher` now uses `badge--warning` ("degraded") for reachable-but-non-200 responses, with the status code in the tooltip (e.g. "Watcher returned 503"). Network/connect failures still use `badge--danger` ("error"). `GET /dashboard/health/redis` tooltip now prefixes the exception class name (e.g. "ConnectionError: …") to distinguish timeout from connection refused.

**Breaking change (internal only):** `WatcherClient.health_check()` now returns `int` (HTTP status code) instead of `bool`. Callers must compare `== 200` rather than a truthy check. Only `src/dashboard/routes/index.py` calls this method.

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

*Housekeeping (2026-07-19).* `clients/python/uv.lock` now pins `archiver-client` at 4.1.0, matching the version `clients/python/pyproject.toml` has declared since this release. The lock was left at 4.0.0 here and only caught later (archiver#90). No functional change.

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
