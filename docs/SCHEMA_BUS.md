# archiver — Schema: bus-state tables

Per-table contracts and invariants for the tables that record what archiver put on, or read
from, the change bus: the revocation record, the replicate and persist command ledgers, the
outbox, and the watch-status cache with its tail cursor. Split from [SCHEMA.md](SCHEMA.md), which
keeps the registry tables; identifiers are verbatim there and here.

## Entities

- **`RevokedInfoItem`** (`revoked_info_items`) — a deleted InfoItem's identity + final
  generation (archiver#141). Written in the deletion's transaction by `DELETE /info-items/{id}`;
  what the hourly snapshot's tombstone republish reads once the item row is gone, because
  absence-from-a-full-set is deliberately *not* the delete signal. No FK — the referent is gone by
  design. Rows are kept forever; the table grows only with deletions. Same shape and reason as
  Watcher's consumer-side table (watcher#254): every key keeps a left-hand side for
  apply-iff-greater whether or not it still has a row.
- **`ReplicationCommand`** (`replication_commands`) — one `content.replicate` occasion and what
  became of it (archiver#169). Written in the *same transaction* as the revision insert and the
  outbox row, which is what makes "revision recorded" and "replication requested" inseparable.
  - **`command_id` is Text, minted fresh per occasion** — never derived from `(rep_spec_id,
    info_item_id)` or anything else stable (MUST-1). A derived id breaks the second legitimate
    re-replication in a TTL-bounded, intermittent way. Text rather than a ULID column because it
    is a wire value Replicator echoes back verbatim; issuance mints ULIDs, but the column does not
    require one.
  - **`info_item_rep_spec_id` is the target**, not `(info_item_id, rep_spec_id)`: that pair is
    unique only among *active* rows, so it stops identifying a target once a spec is deactivated
    and later reassigned.
  - **States**: `requested` → `complete` | `failed` | `abandoned` (archiver#170 writes the last
    three), plus `skipped` — terminal on arrival, nothing went on the wire. Skip reasons are
    **local** (`blob_absent`, `blob_expired_locally`, `unrenderable`, `destination_collision`,
    `unsupported_command`) and deliberately distinct from Replicator's producer-owned failure
    tokens: these are conditions Archiver decided about before publishing.
  - A skip is a *row*, not a log line. Absent one, the dashboard renders a replication that
    silently did not happen as "not yet" forever (archiver#171).
- **`PersistCommand`** (`persist_commands`) — one `content.persist` occasion (archiver#276);
  `ReplicationCommand`'s shape. States `requested` → `persisted` | `failed` | `abandoned`. The
  only link from an outcome to the registry: persist facts carry no domain ids. A success stamps
  every revision with that digest, not just `source_revision_id`. Semantics:
  [BUS_CONSUMERS.md](BUS_CONSUMERS.md). **At most one `requested` command per
  `content_fingerprint`** is the issuer's rule (`persist_issuance`), enforced in code rather than
  by an index: `abandoned` rows accumulate per digest and count against the reaper's re-issue cap.
  - **`last_fact_at` is the ordering high-water mark** (archiver#170). `content.artifacts` is
    at-least-once and keyed `command_id:occurred_at` precisely because one command emits a
    *sequence* of facts, so a redelivered older fact can land after a newer one; without the mark
    a stale failure flips a completed replication to `failed` while its `public_url` still names a
    live artifact. Equal timestamps are the same emission and still apply — T4 has Replicator
    re-emit a success deliberately. Two consequences worth knowing: a `complete` command never
    moves to `failed`, and `terminal` never downgrades from `True`.
  - **`skipped` occasions are excluded from "newest occasion"**. A skip never reached the wire and
    produced no artifact, so it has no claim on the assignment's `public_url` slot — and skips are
    written for *every* active assignment whenever a revision arrives with no blob, so counting
    them would let one such revision silently suppress the URL of a replication still in flight.
- **`ChangesOutboxRow`** (`changes_outbox`) — pending change-bus event awaiting publication.
  - **Published rows are pruned** (archiver#189): the drain loop deletes rows whose `published_at`
    predates `ARCHIVER_OUTBOX_RETENTION_DAYS` (default 30). Once published, the outbox's delivery
    guarantee is discharged and the row is only forensic. Nothing in the service reads one - which
    is why `info_items.announced_at` exists rather than deriving the announce time from
    `published_at`.
  - **Live and dead-lettered rows are never pruned.** A live row is the drain's queue; a
    dead-lettered row is the archiver#107 post-mortem record. Nothing expires one: it leaves only
    through operator triage by row id (archiver#191) - discard deletes it, rearm returns an
    `info.changes` row to the drain. See [BUS.md](BUS.md).
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
