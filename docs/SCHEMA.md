# archiver — Schema & Domain Entities

Per-table contracts and invariants for the registry. Identifiers are verbatim —
see the never-rename rule in `AGENTS.md`.

**Migrations are expand-only** (archiver#330 D3). `scripts/deploy.sh` migrates
before it switches releases, and a rollback never downgrades, so the previous
release must run on the new schema. Add tables and columns nullable or with a
default; a drop, a rename or a new `NOT NULL` without a default ships as two
deploys: stop using it, then remove it.

**Stored documents satisfy the current schema** (archiver#164). The four authored
documents - `source_specs`, `watch_spec`, `rep_fields`, RepSpec `document` - are
validated on write only, so a schema tightening ships with a data migration or with
the sweep's "0 affected" in its PR; for an assigned (frozen) RepSpec, a recorded #83
exception or #95. The rule and its RepSpec carve-out: [CONVENTIONS.md](CONVENTIONS.md)
§ Schema tightenings. `src/core/tools/audit_stored_documents.py` re-judges every stored
document; the dashboard's Registry badge reports the count
([HEALTH_ROW.md](HEALTH_ROW.md)).

## Entities

- **`InfoItem`** (`info_items`) — semantic anchor; carries domain meaning + `rep_fields` JSONB bag.
  The bag holds **raw** values (`{"org": {"title": "…", "acronym": "…"}, "info_item": {"name": "…"}}`);
  every string field's `<key>_slug` companion, plus `acronym_or_title(_slug)` when both are
  present, is derived with co-core's `normalize_string` — the same function the storage
  framework's `*Vars` use, so a segment archiver renders matches the sibling directories the CLI
  writes (archiver#206). **Derivation has one point: `effective_rep_fields(bag, org)`**
  (archiver#303) — the stored bag over the linked org's `name`/`acronym` as
  `org.title`/`org.acronym`, then derived; a guard test refuses any other `resolve_rep_fields`
  caller. A stored key wins, and a stored `_slug` key is an explicit override that is never
  replaced. Derivation never rewrites the stored bag.
  **One writer after create: `set_rep_fields`** (archiver#302), behind `PUT …/rep-fields` and the
  dashboard save. A written bag is v1-shaped and serves every active assignment, per the gate
  `src/core/tools/rep_fields_gate.py` that assign and create share; writers serialize on the
  InfoItem row. Enforced on write only, no backfill (prod clean 2026-10-02). Codes and the
  destination-move 409: [API.md](API.md).
  `pm_org_id TEXT NULL` (archiver#304) — FK → `pm_organizations` (`RESTRICT`, indexed). **While
  set, the stored bag holds no `org.title`/`org.acronym`**: link drops them, writers refuse them,
  unlink writes the org's values back. Written by `link_org` under the InfoItem row lock.
  `watcher_item_id` — **dropped** (archiver#142). It held *Watcher's* primary key on an *Archiver*
  row, which is the coupling artifact the decoupling epic set out to remove. Announcements key on
  Archiver's own `info_item_id` and Watcher reconciles against that, so nothing allocates a
  WatchedItem id to store. "Watched" is no longer a column at all: it is membership of the
  **announced set** — an active binding whose source carries non-empty `source_specs`, the same
  predicate `_collect_full_set` publishes by and the watched-item panel selects its state with.
  `watch_spec JSONB NOT NULL` + `watch_active BOOLEAN NULL` (archiver#150) — **scheduling
  policy, split across two columns on purpose.**
  - **`watch_spec`** is *cadence only*, validated against `src/core/watch_spec_schema/v1.json`
    and written via `PUT /info-items/{id}/watch-spec` (whole-document replace). A *document*,
    not an entity: there is no `watch_specs` table, and the announcement carries it resolved so
    a future reusable-policy table stays an Archiver-internal change.
    - `schema_version` (required, const 1); `interval` (optional) — a Watcher interval string.
      **Absent means "inherit"** the host's default, else Watcher's (archiver#364): a real state,
      never a value to fill in. The column is intent; the announcement carries the resolved one. The schema validates the grammar `^[0-9]+[smhd]$`; the narrower
      set the dashboard offers lives in `src/dashboard/cadence.py`.
    - Server default `{"schema_version": 1}` — deliberately no interval, so the migration cannot
      fabricate a cadence for rows that never had one.
  - **`watch_active`** is per-item pause state, written via `PUT /info-items/{id}/watch-active`.
    `true` schedules, `false` is registered-but-paused (keep the item, stop scheduling), and
    **`NULL` means the registry has no opinion yet** — not yet imported from Watcher. Defaulting
    it `true` would announce every paused item as unpaused the moment the producer lands.
  - **`archived_at`** (#361): watch archive, orthogonal to `watch_active`; announces
    `active=false`. Contract: `src/core/services/info_item_lifecycle.py`.
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
  no consumer has ever held. Those stay at `0` until first announceable; the delta path has not
  bumped an unannounceable row off `0` since archiver#167 (pre-#167 never-live rows at `1` stay,
  already tombstoned there). The reason is the return leg: `info.watch-status` spells "never
  reconciled" as `applied_generation = 0`, so a generation-0 *announcement* would make the wire
  value ambiguous and the #151 drift detector read an unapplied item as clean. Reserved `0` in
  the DB (never announced) and a floor of 1 on the wire are the two halves of that. A live
  snapshot entry at 0 is now logged as an anomaly — it would mean an announceable item reached
  the snapshot without passing any announce site.

  `announced_at TIMESTAMPTZ NULL` (archiver#151) — when the generation last bumped, stamped in
  the same atomic UPDATE. The drift detector's clock: "applied lags announced by 40m" needs to
  know when the announced generation went out, and `changes_outbox.published_at` is pruned on a
  retention window (archiver#189), so the fact lives here. `NULL` until the first bump (including
  rows that predate the column); the panel then shows drift without an age.

  `announced_revoked BOOLEAN NOT NULL DEFAULT false` (archiver#293) — whether the last delta
  announcement was a tombstone, set in the same UPDATE as the bump, so it always describes the
  current generation. The binding path skips an unannounceable item whose flag is already `true`:
  the key is revoked and nothing changed, so a second tombstone would only burn a generation.
  Migration `d3f9a6b8e015` backfilled `true` on exactly the rows the snapshot tombstones
  (`> 0`, no active binding to a source with non-empty `source_specs`). Meaningless at `0`. A
  stray `true` on a live key is the unsafe direction: it suppresses an owed tombstone that the
  snapshot cannot repair, since it republishes at the generation the consumer already holds.

  **Deletion — use `DELETE /info-items/{id}`, never psql** (archiver#141). An InfoItem's exit
  from the registry is announced as a `revoked: true` tombstone, and that tombstone must be
  written to `changes_outbox` in the deletion's own transaction. Raw SQL cannot do that, so a
  psql `DELETE` silently skips the announcement and every consumer keeps the key **forever** —
  the periodic full republish does not repair it, because `revoked` is an explicit tombstone
  precisely so that absence-from-a-full-set is *not* the delete signal. The route cascades the
  item's bindings and rep-spec assignments (both FKs are `ON DELETE CASCADE`); the InfoSource
  and its SourceRevisions survive, since the physical layer is shared and `source_revisions`
  keys on `info_source_id`. The deletion **is** announced as a tombstone on `info.registry`, but
  watcher#254 does not document tombstone handling, so an orphaned WatchedItem may still need
  removing there by hand. The route logs a WARNING naming the InfoItem when the
  deleted item had a `watch_status` row, so the pending cleanup shows up in journald.

- **`PmOrganization`** (`pm_organizations`, archiver#304) — snapshot of one linked Power Map org,
  PK Power Map's id; columns documented on the model. Written only by `apply_org_snapshot`, which
  never moves a row backwards in `pm_updated_at`. **Rendering reads this row, never Power Map.**
  The hourly follower (archiver#305, `src/core/tools/refresh_orgs.py`) re-checks every row an
  item links with the stored `etag`:
  - **304** → `checked_at` only. **200** → `apply_org_snapshot`; a `name`/`acronym` change sets
    `renamed_from`/`renamed_at` and moves every linked item's paths from its next occasion with
    no confirmation (logged per assignment, before → after; an assignment the new name cannot
    render is warned about, and its next occasion is skipped).
  - **Merged** (410 + `merged_into`, already the chain's live end) → the winner is upserted, the
    loser's items are re-pointed at it (FK is `RESTRICT`, so items move first), and the loser
    row is **kept** with `merged_into` set. No item links a loser, so it is never re-checked.
  - **Gone** (404, or 410 without `merged_into`) → `missing_since = coalesce(missing_since,
    now)`; the last snapshot keeps rendering. Any later answer clears `missing_since`.
  - **No answer** → nothing changes. `succeeded_by`, `archived_at` and `active` are mirrored,
    never followed: re-linking to a successor is a human decision.
- **`Domain`** (`domains`) — per-host policy (#360): [DOMAINS.md](DOMAINS.md).
- **`TemporalProfile`** (`temporal_profiles`, archiver#365) — an item's date-driven cadence, one
  per item (PK `info_item_id`). Intent: `profile_type`, its dates, `rules`, `post_action`,
  `is_active`. Result: `resolved_interval` for the UTC day `evaluated_on`, the cadence's top tier,
  computed only by a profile write and the daily boundary; `fired_at` makes the post-action
  one-shot. Contract: `src/core/services/temporal_profiles.py`.
- **`InfoSource`**, **`SourceRevision`**, **`InfoItemSource`** — the physical layer: sources,
  their revisions and the item↔source bindings: [SCHEMA_SOURCES.md](SCHEMA_SOURCES.md).

- **`RepSpec`** (`rep_specs`) — replication specification. JSONB `document` carries provider config, `credentials_alias`, `path_template`, `required_fields`. Per-provider sub-schemas under `src/core/rep_spec_schema/providers/`.
  **`credentials_alias` rule** (archiver#276, replicator#114): `<provider>-<role>` per co-core's
  `co_core.pure.util.aliases` (e.g. `gcs-publication`), and the prefix must equal `provider`.
  Checked on save only, so a frozen assigned document is never re-judged. The pre-rule name
  `primary` is refused. Migration `70f32f641751` moved production's one RepSpec to
  `gcs-publication`, the one recorded exception to #83's freeze: both names bind the same
  bucket, so no destination changed.
  **Re-judged only at new assignment** (archiver#334): a *new* assignment is where a draft
  document freezes, so `assign_rep_spec` and `POST /info-items` run the whole of
  `validate_rep_spec` (envelope, provider sub-schema, `path_template` contract, this rule) and
  refuse with 422 `rep_spec_invalid`. Existing assignments and issuance are never re-judged, so a
  rule added later cannot break a frozen document's replication; it only stops that document
  gaining new assignments. That is still a stranded document, so #164's rule applies to it: the
  tightening's PR shows 0 assigned specs affected, or carries a recorded #83 exception, and the
  Registry sweep reports any it missed as "clone it".
  **`path_template` contract** (archiver#168) — three rules the envelope schema cannot express,
  checked by `src/core/replication/template.py` from the *same parser* the renderer uses, so a
  document that validates is one that renders:
  - Placeholders are `{namespace.key}`. A bag placeholder must appear in `required_fields` —
    the list is hand-maintained, not derived, so the two are checked against each other before
    the document can freeze.
  - `source_revision.*` is the **occasion** namespace: supplied per replication by
    `src.core.replication.destination.RenderOccasion`, and therefore **rejected** in
    `required_fields` — no `rep_fields` bag can hold it. Eight keys: `id` (the revision ULID),
    `fingerprint` (sha256 hex, prefix dropped), `date` (`YYYY-MM-DD`), `captured_at`
    (`YYYYMMDDTHHMMSSZ`), and — added in archiver#205 so a template copied from the storage
    framework's `defaults.toml` renders byte-identically — `year` (`%Y`), `date_segment`
    (`%Y_%m_%d`), `datetime_time_segment` (`%Y_%m_%d-%H_%M_%S`), all in UTC, and `ext`, derived
    from `source_revisions.source_media_type` with parameters stripped (`html`, `pdf`, …; `bin`
    when unknown or `application/octet-stream`). The canonical layout is the framework's
    `infoitem_revision` location (cannobserv#406, epic #207):
    `organizations/{org.title_slug}/infoitems/{info_item.name_slug}/{source_revision.year}/{source_revision.datetime_time_segment}-{info_item.name_slug}-{source_revision.id}.{source_revision.ext}`.
  - The template must carry `{source_revision.id}` or `{source_revision.fingerprint}` (the
    issuer contract's R2). `date` is not a discriminator: two revisions captured the same day
    would render one destination, which returns as `destination_conflict` — a conflict token
    for what is really a path-design error.

  Rendering refuses rather than rewrites: a bag value outside `[A-Za-z0-9._-]` is an error
  naming the field, because the rendered path becomes a citable `public_url` and two values
  that sanitize alike would collide. The rendered string is then checked against the consumer's
  own guards (absolute, traversal, backslash, drive qualifier, control characters, untrimmed or
  empty segments — before *and* after percent-decoding), so a path Archiver can refuse is never
  published.

  **Tiered mutability** (#83): `name` always editable; `document` editable only while the RepSpec is a
  *draft* — zero `info_item_rep_specs` rows, active **or** deactivated; `provider` frozen always.
  `updated_at` is nullable and never backfilled (NULL = never edited). An assigned spec is frozen
  because its assignment rows assert which document produced the artefacts at their `public_url`;
  clone + migrate is #95. See `docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md`.
- **`InfoItemRepSpec`** (`info_item_rep_specs`) — effective-dated assignment + `public_url` writeback target.
  - **At most one active row per `(info_item_id, rep_spec_id)`** (archiver#301): partial unique
    index `uq_iirs_item_spec_active` `WHERE deactivated_at IS NULL`. Two active rows render one
    destination, and issuance skips **both** as `destination_collision` on every occasion.
    `assign_rep_spec` refuses first (`DuplicateAssignmentError` → 409) under the RepSpec row lock;
    the index is the backstop for any other writer. Deactivated rows are history and may repeat, so
    reassigning after a deactivate is allowed. It is also the item-only active lookups' index (#311).
- **Bus-state tables** — `revoked_info_items`, `fetch_policy_tombstones`, `replication_commands`, `persist_commands`,
  `changes_outbox`, `watch_status`, `bus_tail_cursors`: [SCHEMA_BUS.md](SCHEMA_BUS.md).

The Phase 1–3a `InfoSpec` model has been retired. Avoid any new references to `info_spec*` outside historical alembic migration files. The "Archiver" rename was service-name-only; `info_*` table prefix and `information` schema preserved per design decision.
