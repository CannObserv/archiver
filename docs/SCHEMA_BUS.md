# archiver — Schema: bus-state tables

Per-table contracts and invariants for the tables that record what archiver put on, or read
from, the change bus: the revocation records, the replicate, persist, watch-check and capture command ledgers, the
outbox, the watch-status cache with its tail cursor, and the notification dispatches. Split from [SCHEMA.md](SCHEMA.md), which
keeps the registry tables; identifiers are verbatim there and here.

## Entities

- **`RevokedInfoItem`** (`revoked_info_items`) — a deleted InfoItem's identity + final
  generation (archiver#141). Written in the deletion's transaction by `DELETE /info-items/{id}`;
  what the hourly snapshot's tombstone republish reads once the item row is gone, because
  absence-from-a-full-set is deliberately *not* the delete signal. No FK — the referent is gone by
  design. Rows are kept forever; the table grows only with deletions. Same shape and reason as
  Watcher's consumer-side table (watcher#254): every key keeps a left-hand side for
  apply-iff-greater whether or not it still has a row.
- **`FetchPolicyTombstone`** (`fetch_policy_tombstones`) - a deleted host and the generation
  its `content.fetch-policy` tombstone carries (archiver#366). Written by `DELETE
  /domains/{name}` in the delete's transaction, at a value drawn from
  `fetch_policy_generation_seq`; every full set republishes it, so trimming never ages the
  tombstone out. `host` is the primary key, so a second delete moves the row up. A re-add
  removes the row in its own transaction, at both insert sites. Same as Watcher's
  `fetch_policy_tombstones`, plus `generation`. Bounded by the count of deleted hosts.
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
  every revision with that digest, not just `source_revision_id`, and every capture with it.
  **The occasion is a revision or a capture, exactly one** (archiver#380 slice B):
  `source_revision_id` (FK `RESTRICT`) or `capture_command_id` (FK `capture_commands`,
  `CASCADE`), held by `ck_persist_commands_one_occasion`. Semantics:
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
  The three C-c levels (archiver#370 D1): `last_full_fetch_at` (bytes arrived - a 200, never a
  304, stamped before extraction; check-now's completion reading), `health_reason` (an open
  token, verbatim) and `health_status_code` (for `http_status`). Levels: a frame without them
  writes `NULL`. Rows from before the migration fill on Watcher's next periodic republish.
- **`WatchCheckCommand`** (`watch_check_commands`) — one check-now click (archiver#370 D2):
  `command_id` (PK), `info_item_id` (FK `CASCADE`), `requested_at` (Archiver's clock, stamped at
  the outbox write), `requested_by` (`app_users.id`, `SET NULL`; an id, so the read role needs no
  column allowlist), `created_at`, and the only outcome stored, `rejected_reason` /
  `rejected_at` (the fact's `occurred_at`), first write wins. Success is not stored: it is read
  at render from `watch_status.last_full_fetch_at > requested_at`. Written with its
  `info.watch-check` outbox row in one transaction. Ladder: [INFO_ITEM_ACTIONS.md](INFO_ITEM_ACTIONS.md).
- **`CaptureCommand`** (`capture_commands`) — one `content.capture` command (archiver#380);
  `PersistCommand`'s shape. States `requested` → `stored` | `failed` | `abandoned`
  (`CHECK`, because the open index hard-codes `requested`). `info_source_id` FK `CASCADE`;
  `requested_by` → `app_users.id` `SET NULL`. **What was sent**, verbatim: `url`,
  `viewport_width`/`viewport_height`, `full_page`, `wait` (JSONB, the wire's `wait` as sent;
  `NULL` = after `load`). **Why it was sent** (slice C): `source_revision_id` (FK
  `source_revisions`, `SET NULL`) names the new revision that triggered it, `NULL` on demand -
  temporal, since a capture renders the live page; `reissue_of` (self FK, `SET NULL`) names the
  silent command a reaper re-issue repeats, and `attempt` (NOT NULL, default 1, `CHECK >= 1`)
  counts the chain, capped at `1 + capture.MAX_CAPTURE_REISSUES`.
  **What came back**, from the first `capture_stored` (C1): `content_fingerprint` (bare hex, an
  address only), `blob_uri`, `media_type`, `size_bytes`, `image_width`/`image_height` (the
  stored PNG, not the viewport), `final_url`, `captured_at`, `blob_expires_at` (the temp
  store's horizon; `NULL` = unknown). Failure: `reason` (opaque), `detail`, `status_code`,
  `terminal`. `last_fact_at` is the failure ordering high-water mark. `persisted_at` (slice B)
  is `source_revisions.persisted_at`'s rule: the minimum `blob_persisted` time for the digest,
  stamped by any persist of those bytes **in the same store**; set, `blob_expires_at` no
  longer binds. The store is the bucket `blob_uri` names: `co-gcs-captures` keeps a capture
  apart from revisions (#380 D4, `permanent_store.kept_capture_uri`); a capture stored before
  that split was kept with them. **At most one
  `requested` row per source** is the issuer's rule (`capture.request_capture`, under the
  source row lock), not an index. Outcome semantics: [BUS_CONSUMERS.md](BUS_CONSUMERS.md).
- **`BusTailCursor`** (`bus_tail_cursors`) — resume point per tailed stream (archiver#151). A
  groupless tail reader has no server-side delivery cursor; this row makes a restart a delta
  from the last-applied stream id instead of a full `0-0` replay. Advanced in the same
  transaction as the write it covers, so a crash between the two is impossible and redelivery
  re-applies an idempotent LWW upsert. One row per stream; today only `info.watch-status`.
- **`NotificationDispatch`** (`notification_dispatches`) — one composed notification
  (archiver#369 D1): a row per (`info.watch-events` fact, matching subscription), plus one per
  error reminder. **Both the shadow log and the dispatch outbox**; nothing goes on
  `changes_outbox`. Contract: [NOTIFICATIONS.md](NOTIFICATIONS.md#dispatch-on-events-archiver369).
  - **Unique on (`event_id`, `subscription_id`, `reminder`)**, so a redelivered fact is a no-op;
    `reminder` is 0 for the fact, *n* for the episode's *n*-th reminder, whose `event_id` is the
    edge's. `idempotency_key` (Notifier's) is unique too.
  - `mode` `shadow` ⇔ `status` `shadow` (a CHECK); a `send` row is `pending` → `sent` |
    `failed` | `skipped`. `occurred_at` is the fact's (F3's parity key); `reminded_at` is set iff
    `reminder > 0`. `fact` is the fact as received; a reminder rebuilds its event from it.
  - **`subscription_id` is `SET NULL`**: a delete keeps the history, and a pending row ends
    `skipped`. **`info_item_id` has no FK**: a revoked item keeps its rows, and its pending send
    still goes.
  - **Retention:** terminal rows past `ARCHIVER_NOTIFY_RETENTION_DAYS` (default 90) are pruned
    by the reminder timer; `pending` never is. No operator-authored document, so no
    `audit_stored_documents` kind.
