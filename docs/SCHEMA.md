# archiver — Conventions Reference

The reasoning and worked examples behind the rules stated in `AGENTS.md`.

## Changelog trigger — what the path regex means

M1
cat "$S/D1_changelog.md"
cat <<'M2'

## Logging — plain-text `ExecStartPre` lines in journald

M2
cat "$S/D2_journald.md"
cat <<'M3'

## Error envelope — worked examples and the `kind` vocabulary

M3
cat "$S/D3_errors.md"
} > docs/CONVENTIONS.md

# --- docs/SCHEMA.md ---
{
cat <<'HDR'
# archiver — Schema & Domain Entities

Per-table contracts and invariants for the registry. Identifiers are verbatim —
see the never-rename rule in `AGENTS.md`.

## Entities

- **`InfoItem`** (`info_items`) — semantic anchor; carries domain meaning + `rep_fields` JSONB bag.
  `watcher_item_id VARCHAR(50)` — nullable; stores the Watcher-allocated WatchedItem ID once
  provisioned. `NULL` means not yet watched (use "Begin watching" in the dashboard or wait for
  the next `create_info_item` call with Watcher configured).
  `watch_spec JSONB NOT NULL` + `watch_active BOOLEAN NULL` (archiver#150) — **scheduling
  policy, split across two columns on purpose.**
  - **`watch_spec`** is *cadence only*, validated against `src/core/watch_spec_schema/v1.json`
    and written via `PUT /info-items/{id}/watch-spec` (whole-document replace). A *document*,
    not an entity: there is no `watch_specs` table, and the announcement carries it resolved so
    a future reusable-policy table stays an Archiver-internal change.
    - `schema_version` (required, const 1); `interval` (optional) — a Watcher interval string.
      **Absent means "the consumer applies its own default"**, which may be a per-domain
      `default_schedule_config` rather than a global constant, so absence is a real state and
      never a value to fill in. The schema validates the grammar `^[0-9]+[smhd]$`; the narrower
      set the dashboard offers lives in `src/dashboard/cadence.py`.
    - Server default `{"schema_version": 1}` — deliberately no interval, so the migration cannot
      fabricate a cadence for rows that never had one. Three of the four production WatchedItems
      carry no per-item cadence at all.
  - **`watch_active`** is per-item pause state, written via `PUT /info-items/{id}/watch-active`.
    `true` schedules, `false` is registered-but-paused (keep the item, stop scheduling), and
    **`NULL` means the registry has no opinion yet** — not yet imported from Watcher. Defaulting
    it `true` would announce every paused item as unpaused the moment the producer lands.
  - **Why not one column?** A policy document shared across items by the future reusable-policy
    table could not carry per-item pause state — pausing one item would pause all of them. And
    co-core's `RegistryAnnouncementState` types `active` on the announcement envelope beside
    `revoked`, giving the three-state distinction (revoked / paused / scheduled) a contract-level
    schema guarantee; nested in an untyped dict it had none. A nested `active` still *validates*
    on the wire while the envelope reports "no opinion" — `v1.json` rejecting the key is the only
    thing that catches it, which is why it is closed with `additionalProperties: false`.
  - Real values arrive from `scripts/import_watch_specs.py`, which reads Watcher over the SDK and
    is re-run immediately before the announcement producer's first publish.
  - **Boundary:** a WatchSpec is *per-item cadence*. `content.fetch-policy` (cannobserv#285) is
    *per-host spacing* — different key, stream, owner, and consumer. They are not the same knob.

- **`InfoSource`** (`info_sources`) — physical layer. `url TEXT NOT NULL` (non-unique — multiple
  InfoSources may share the same URL for different extraction strategies). `source_specs JSONB`
  (mutable array): first element is the primary extraction spec; subsequent elements are
  cross-check alternatives for selector-rot detection. Each spec: `{schema_version, extraction,
  fingerprint}` — no `target` section; URL is on the InfoSource directly.
- **`SourceRevision`** (`source_revisions`) — content-addressed snapshot. Identity is
  `(info_source_id, content_fingerprint)`; fingerprint is always `sha256:<hex>`, enforced on both
  write paths (`src/core/fingerprints.py`) because a differently-spelled fingerprint for identical
  content is a silent duplicate row rather than a failed write.
  **Two writers** since archiver#139: `POST /source-revisions` (authoring/backfill) and the
  `content.revisions` bus consumer. Both go through `src/core/services/source_revision.py`, so both
  emit the identical `source_revision_captured` event.
  Three columns are **observation provenance** — populated only by the bus path, `NULL` on
  everything the API wrote:
  - `source_media_type` — what the *origin* served. Not a duplicate of `content_media_type`, which
    describes the text extracted under `source_specs`; an HTML page is served `text/html` and the
    text extracted from it is not. Inherits `BlobAvailableEvent.media_type`'s normalization, so it
    cannot express "the origin sent no `Content-Type` at all".
  - `spec_fingerprint` — which `source_specs` the producer extracted under, e.g.
    `spec1:sha256:<hex>`. **Recorded and compared, never enforced**: a value disagreeing with the
    InfoSource's current specs does *not* invalidate the revision and does not fail the write.
    archiver#140 makes spec delivery eventually consistent, so extraction under a superseded spec
    is an expected transient state. Without the column, *the origin changed*, *our spec changed*,
    and *the producer was behind on announcements* are one indistinguishable new fingerprint.
  - `spec_match` / `spec_position` — the comparison against the InfoSource's authoritative specs,
    using co-core's shared derivation (`co_core.pure.extract`, cannobserv#309
    — both sides run one function rather than two readings of an algorithm). `spec_match` is
    `current` (matched; `spec_position` says *which* spec), `superseded` (**the flag** — well
    formed, matches none we hold), or `incomparable`; `NULL` means no fingerprint was reported.
    **Every uncertain branch resolves to `incomparable`, never `superseded`** — an unrecognised
    derivation tag, a malformed value, or specs of our own that have no canonical form. A false
    mismatch is indistinguishable from the real condition the field exists to detect, so "cannot
    compare" and "compared, and it differs" must never collapse. `spec_position > 0` is its own
    signal: the primary spec stopped matching and the producer fell through to a cross-check
    alternative — selector rot in progress. Both are logged at WARNING as well as stored.
    **All three `spec_*` columns describe the most recent observation of the pair, not the one
    that created the row.** A re-observation is an idempotent no-op for the revision itself, but
    it refreshes these three together (and emits no event — the identity is unchanged). Without
    that, a registry that moved to a new spec would leave already-recorded content asserting
    `current` for a spec it no longer holds, and the producer stuck on the old spec — the case
    the flag exists for — would never raise one. The WARNING fires on a change of verdict, not on
    every at-least-once redelivery.
  - `command_id` — correlation back to the `content.fetch` command behind the bytes.
  `content_cache_uri` / `content_cache_expires_at` are a **cache, not durable storage** — on the bus
  path a VM-local `file://` blob on Replicator's host, on a TTL clock the registry does not own. A
  `NULL` expiry records that the horizon is unknown; it is never a guessed TTL. Durable bytes are
  what RepSpec replication is for.
- **`InfoItemSource`** (`info_item_sources`) — operator-declared item↔source binding. No `role`
  column — every binding is a primary binding. Two distinct states:
  - **Current primary** — the one active row (`deactivated_at IS NULL`). Enforced one-per-InfoItem
    by partial unique index `uq_info_item_sources_active`. Its InfoSource URL is what Watcher
    fetches each tick.
  - **Previous primary** — a deactivated row (`deactivated_at IS NOT NULL`). Preserved indefinitely
    as succession history. Watcher may continue watching previous primaries for unanticipated
    changes.

- **`RepSpec`** (`rep_specs`) — replication specification. JSONB `document` carries provider config, `credentials_alias`, `path_template`, `required_fields`. Per-provider sub-schemas under `src/core/rep_spec_schema/providers/`.
  **Tiered mutability** (#83): `name` always editable; `document` editable only while the RepSpec is a
  *draft* — zero `info_item_rep_specs` rows, active **or** deactivated; `provider` frozen always.
  `updated_at` is nullable and never backfilled (NULL = never edited). An assigned spec is frozen
  because its assignment rows assert which document produced the artefacts at their `public_url`;
  clone + migrate is #95. See `docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md`.
- **`InfoItemRepSpec`** (`info_item_rep_specs`) — effective-dated assignment + `public_url` writeback target.
- **`ChangesOutboxRow`** (`changes_outbox`) — pending change-bus event awaiting publication.

The Phase 1–3a `InfoSpec` model has been retired. Avoid any new references to `info_spec*` outside historical alembic migration files. The "Archiver" rename was service-name-only; `info_*` table prefix and `information` schema preserved per design decision.
