# archiver — Schema: the physical layer

Per-table contracts and invariants for the source side of the registry: the InfoSources an item
can be bound to, their content-addressed SourceRevisions, and the item↔source bindings. Split from
[SCHEMA.md](SCHEMA.md), which keeps the items, specs and assignments; identifiers are verbatim there
and here.

## Entities

- **`InfoSource`** (`info_sources`) — physical layer. `url TEXT NOT NULL` (non-unique — multiple
  InfoSources may share the same URL for different extraction strategies). `source_specs JSONB`
  (mutable array): first element is the primary extraction spec; subsequent elements are
  cross-check alternatives for selector-rot detection. Each spec: `{schema_version, extraction,
  fingerprint}` — no `target` section; URL is on the InfoSource directly. `extraction.algorithm`
  is `css | xpath | jsonpath | full_page`; one list keeps to one family, `full_page` pairing
  with any (#356; `families.py`, `v1.json`). Which media type honours which is co-core's
  extractor's call (#317). Optional
  `extraction.ignore_selectors` (#378, HTML only; contract in `v1.json`).
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
  - `blob_fingerprint` / `persisted_at` (archiver#276) — the **raw-bytes** digest (bare hex; never
    `content_fingerprint`), the permanent store's address, and the *minimum* `blob_persisted`
    `occurred_at` for it. NULL until watcher#329. See `PersistCommand`. **The digest moves with
    `content_cache_uri`** under the refresh rule below while `persisted_at` is NULL - a persist
    sends the two together, and Replicator refuses a digest that does not name the URI's bytes; a
    changed URI without a digest clears it, the same URI keeps it - and is **frozen** once
    persisted: the persisted bytes stand for the revision.
  `content_cache_uri` / `content_cache_expires_at` are a **cache, not durable storage** — on the bus
  path Replicator's temp-store blob (`gs://co-gcs-blobs` since 2026-08-20; rows from before the
  flip carry the VM-local `file://` form), on a TTL clock the registry does not own. A `NULL`
  expiry records that the horizon is unknown; it is never a guessed TTL. Durable bytes are what
  RepSpec replication is for.
  **Both describe the most recent observation of the pair, like the `spec_*` columns**
  (archiver#201). Replicator's TTL runs from the blob's *last reference*, so a full re-fetch of
  unchanged bytes re-announces a later horizon; a row that kept the first one would refuse
  (`blob_expired_locally`) a replication the consumer would serve — for a stable item, forever,
  since no later revision arrives to correct it. So a re-observation refreshes the two together
  under a forward-only horizon: an older or equal `blob_expires_at` is ignored, an absent
  reference never erases a stored one, and an unknown horizon never replaces a known one. No
  event is emitted — the identity is unchanged. The producer half is Watcher's (re-announcing an
  unchanged fingerprint whose horizon moved; linked from #201); until it lands this branch only
  sees at-least-once redeliveries.
- **`InfoItemSource`** (`info_item_sources`) — operator-declared item↔source binding. No `role`
  column — every binding is a primary binding. Two distinct states:
  - **Current primary** — the one active row (`deactivated_at IS NULL`). Enforced one-per-InfoItem
    by partial unique index `uq_info_item_sources_active`. Its InfoSource URL is what Watcher
    fetches each tick.
  - **Previous primary** — a deactivated row (`deactivated_at IS NOT NULL`). Preserved indefinitely
    as succession history. Watcher may continue watching previous primaries for unanticipated
    changes.
  - **One row per tenure** (archiver#392). The primary key is a ULID `id`, minted from
    `created_at` for pre-existing rows, so a pair bound, retired and bound again has two rows, each
    bounding one stint. A swap back to a previous primary inserts; nothing reactivates a row.
    `id`'s server default `information.gen_ulid()` serves the previous release, whose inserts name
    no `id` (expand-only).
  - **One writer, and every insert emits** (archiver#390). `bind_info_source` is the only code in
    `src/` that inserts a row, and it stages `info_item_primary_changed` in the same transaction;
    `tests/core/test_binding_guard.py` refuses any other writer, and any other emitter.
  - **Binds of one source serialize** (archiver#51): the tool locks the source row (`FOR NO KEY
    UPDATE`); `require_unbound_source` refuses a source an item holds. Why not `FOR UPDATE`: its docstring.
  - **Both directions are indexed.** `ix_info_item_sources_item (info_item_id)` serves an item's
    bindings, history included, and the `ON DELETE CASCADE` from `info_items`. A lookup by
    `info_source_id` alone needs its own index — Postgres has no skip scan. Partial index
    `ix_info_item_sources_active_source` covers that direction (archiver#176), matching the same
    `deactivated_at IS NULL` predicate its consumers filter by: reaching *items* from a *source*
    is by definition a question about current bindings.
