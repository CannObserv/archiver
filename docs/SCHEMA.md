# archiver — Schema & Domain Entities

Per-table contracts and invariants for the registry. Identifiers are verbatim —
see the never-rename rule in `AGENTS.md`.

## Entities

- **`InfoItem`** (`info_items`) — semantic anchor; carries domain meaning + `rep_fields` JSONB bag.
  `watcher_item_id VARCHAR(50)` — nullable; stores the Watcher-allocated WatchedItem ID from the
  provisioning era. **Vestigial since archiver#142** — nothing writes it (provisioning was the only
  writer) and nothing reads it for behaviour; announcements key on Archiver's own `info_item_id`,
  which Watcher reconciles against. "Watched" is no longer this column: it is membership of the
  announced set — an active binding whose source carries non-empty `source_specs`. The column is
  dropped once the last legacy row is confirmed uninteresting.
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
  - Real values arrived via a one-time import from Watcher (archiver#150); since the
    control-plane cutover (archiver#158) the dashboard writes them directly and they are
    authoritative. The import script and the SDK it read through are gone (archiver#142).
  - **Boundary:** a WatchSpec is *per-item cadence*. `content.fetch-policy` (cannobserv#285) is
    *per-host spacing* — different key, stream, owner, and consumer. They are not the same knob.

  `announcement_generation BIGINT NOT NULL DEFAULT 0` (archiver#141) — the LWW ordering token
  for `info.registry`. Bumped **only** via the atomic `UPDATE … SET announcement_generation =
  announcement_generation + 1 RETURNING` in `src/core/services/registry_announcement.py` — never
  read-modify-write (two concurrent mutations would both write N+1 and every consumer would
  discard the second announcement as a duplicate). Snapshots read it and never bump it. `0` means
  never announced; the default is `0` and not a sentinel because co-core rejects negatives —
  apply-iff-greater would never fire for a key sorting below every legitimate value.

  **An *announced* generation is never `0`** (archiver#161). The floor is 1 on the wire: the
  bump precedes the payload, so the delta path cannot emit 0, and migration `e3a71c40b9d2`
  lifted the rows that could reach a snapshot at 0 — those predating the column, plus rows the
  #150 import classed `unchanged` and therefore never announced. It lifts only the
  **announceable** ones (active binding, non-empty `source_specs`), because those are the only
  rows a snapshot publishes at all at 0; an unbound or spec-less row is already filtered out of
  both revoked lists by their own `> 0` guards, and lifting it would start a tombstone for a key
  no consumer has ever held. Those stay at `0` and heal on their first real mutation. The reason is the return
  leg: `info.watch-status` spells "never reconciled" as `applied_generation = 0`, so a
  generation-0 *announcement* would make the wire value ambiguous and the #151 drift detector
  read an unapplied item as clean. Reserved `0` in the DB (never announced) and a floor of 1 on
  the wire are the two halves of that. A live snapshot entry at 0 is now logged as an anomaly —
  it would mean an announceable item reached the snapshot without passing any announce site.

  `announced_at TIMESTAMPTZ NULL` (archiver#151) — when the generation last bumped, stamped in
  the same atomic UPDATE. The drift detector's clock: "applied lags announced by 40m" needs to
  know when the announced generation went out, and `changes_outbox.published_at` is prunable
  under the #141 retention split, so the fact lives here. `NULL` until the first bump (including
  rows that predate the column); the panel then shows drift without an age.

  **Deletion — use `DELETE /info-items/{id}`, never psql** (archiver#141). An InfoItem's exit
  from the registry is announced as a `revoked: true` tombstone, and that tombstone must be
  written to `changes_outbox` in the deletion's own transaction. Raw SQL cannot do that, so a
  psql `DELETE` silently skips the announcement and every consumer keeps the key **forever** —
  the periodic full republish does not repair it, because `revoked` is an explicit tombstone
  precisely so that absence-from-a-full-set is *not* the delete signal. The route cascades the
  item's bindings and rep-spec assignments (both FKs are `ON DELETE CASCADE`); the InfoSource
  and its SourceRevisions survive, since the physical layer is shared and `source_revisions`
  keys on `info_source_id`. **Until watcher#254 consumes tombstones, nothing tells Watcher** —
  remove the orphaned WatchedItem there by hand. The route logs a WARNING naming both IDs when the
  deleted item had a `watcher_item_id`, so the pending cleanup shows up in journald.

- **`InfoSource`** (`info_sources`) — physical layer. `url TEXT NOT NULL` (non-unique — multiple
  InfoSources may share the same URL for different extraction strategies). `source_specs JSONB`
  (mutable array): first element is the primary extraction spec; subsequent elements are
  cross-check alternatives for selector-rot detection. Each spec: `{schema_version, extraction,
  fingerprint}` — no `target` section; URL is on the InfoSource directly.
  `last_observed_at TIMESTAMPTZ NULL` (archiver#151) — when Watcher last **successfully
  extracted** this source, changed or unchanged: "verified current as of T". A provenance fact,
  materially stronger than "no record of a change", which conflates *verified same* with *never
  looked* — a change-only pipeline (`content.revisions`) structurally cannot assert it. Three
  properties every reader must hold:
  - **Reported, not locally verified.** Watcher's claim on `info.watch-status` is the only
    source; there is no cross-check. If Watcher stamps it wrongly, the registry records it wrongly.
  - **A lower bound, not exact freshness.** The producer coalesces publishes, so the column
    under-reports by up to the republish period. Safe direction — it never claims content is
    fresher than it is — but a downstream treating it as exact will be subtly wrong.
  - **Written only by the watch-status consumer**, monotonically (never backwards), onto the
    item's *active* binding, and only when the observation postdates that binding — an
    observation older than the binding was of some earlier source and says nothing about this one.
  - **Deliberately internal for now.** No HTTP route or SDK model exposes it — the dashboard is
    the only reader. That is a conscious hold, not an oversight: the column's two caveats above
    (reported, and a lower bound) are easy to state on a page an operator is already reading and
    easy to lose across a wire, and no consumer has asked for it yet. Surfacing it on
    `InfoSourceResponse` is a deliberate future call carrying an SDK regen and a `CHANGELOG`
    entry; until someone needs it, the narrower surface is the cheaper one to be right about.
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
- **`RevokedInfoItem`** (`revoked_info_items`) — a deleted InfoItem's identity + final
  generation (archiver#141). Written in the deletion's transaction by `DELETE /info-items/{id}`;
  what the hourly snapshot's tombstone republish reads once the item row is gone, because
  absence-from-a-full-set is deliberately *not* the delete signal. No FK — the referent is gone by
  design. Rows are kept forever; the table grows only with deletions. Same shape and reason as
  Watcher's consumer-side table (watcher#254): every key keeps a left-hand side for
  apply-iff-greater whether or not it still has a row.
- **`ChangesOutboxRow`** (`changes_outbox`) — pending change-bus event awaiting publication.
- **`WatchStatus`** (`watch_status`) — local LWW cache of `info.watch-status`, one row per
  InfoItem (archiver#151). What the watched-item panel renders from, with zero SDK calls. Every
  value is **reported by Watcher, not locally verified**, and coalesced (timestamps under-report
  by up to the republish period). `health` is an open vocabulary — `"ok"` is the only value that
  means healthy; consumers test `health == "ok"`, never `health != "error"`. `applied_active =
  false` is a legitimate state (deliberately paused), not absence. `applied_interval NULL` means
  *Watcher's own default is in force* — a reportable state; next-due derives from it where
  present, announced `watch_spec.interval` as fallback. A `revoked` message **deletes** the row
  (idempotent; a republished tombstone is a no-op; a later live message legitimately recreates
  it) — "no row" is the panel's "no status yet" state, distinct from paused and from healthy.
  FK `ON DELETE CASCADE`; a status for an item the registry does not hold is dropped unrecorded.
  **A stale or absent row degrades the panel and must never fail a mutation, route, or publish.**
- **`BusTailCursor`** (`bus_tail_cursors`) — resume point per tailed stream (archiver#151). A
  groupless tail reader has no server-side delivery cursor; this row makes a restart a delta
  from the last-applied stream id instead of a full `0-0` replay. Advanced in the same
  transaction as the write it covers, so a crash between the two is impossible and redelivery
  re-applies an idempotent LWW upsert. One row per stream; today only `info.watch-status`.

The Phase 1–3a `InfoSpec` model has been retired. Avoid any new references to `info_spec*` outside historical alembic migration files. The "Archiver" rename was service-name-only; `info_*` table prefix and `information` schema preserved per design decision.
