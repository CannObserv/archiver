# archiver - change-bus consumers

**The streams Archiver takes off the bus - `content.revisions`,
`content.artifacts`, `info.watch-status` - and the naming contract its group
consumers follow.** Split out of [BUS.md](BUS.md), which keeps the producing
half: the outbox, the published streams, and the shared client every consumer
loop here connects through.

## Change-bus consumer - `content.revisions` (archiver#139)

Archiver's first consumer role - the others are the `content.artifacts` group and the
`info.watch-status` tail below. **No `content.blobs` consumer exists**, and the
epic's role boundary stays unqualified: no read-only exception carved into it.
It reads `source_revision_observed` facts
(`co_core.pure.models.changes.SourceRevisionObservedEvent`, cannobserv#301) from
`content.revisions` under the group **`archiver.revisions`**, one group per
consuming service as the fact-stream posture requires, as the single consumer
**`archiver-revisions-1`**.
`src/core/changes/consumer.py` holds the loop; it runs under the FastAPI
lifespan and is dormant unless **both** `ARCHIVER_REDIS_URL` and
`ARCHIVER_BUS_CONSUMER=1` are set.

**Both group names are derived, not spelled.** `CONSUMER_GROUP` in
`consumer.py` and `artifacts_consumer.py` is
`group_name(<topic>, "archiver")`, from
`co_core.pure.adapters.bus.streams` (the helper arrived in co-core 0.13.1;
`pyproject.toml` now floors at 0.15 for archiver#210's shared extension table).
The cluster convention is `<service>.<stream-suffix>[-<purpose>]`; it went 0/5
across the cluster while it existed only as a docstring beside a free-string
`group` parameter, which is what cannobserv#384 fixed by making it an importable
helper. Deriving evaluates to the same `archiver.revisions` /
`archiver.artifacts` already on the broker - a runtime no-op - but makes a
non-conforming literal impossible rather than merely discouraged. `OwnedGroup` in `src/core/bus_health.py` enforces the other
half of the same taxonomy: `stream_kind` refuses a config/state stream, where a
group would accumulate a PEL nothing drains. Stronger than the `StreamCheck`
guard it replaced in #193 - that one carried an optional `pending_group` and so
ran only on the rows that had one; every `OwnedGroup` names a group by
construction.

Watcher observes; the registry decides. Per message:

1. `info_source_id` is resolved against the registry. Unknown → **ack and drop**
   with a WARNING. The registry is the authority on what exists, and redelivery
   cannot make a missing InfoSource appear.
2. The row is written through
   `src.core.services.source_revision.record_revision` - the same call
   `POST /source-revisions` makes. The existing `INSERT … ON CONFLICT …` on
   `(info_source_id, content_fingerprint)` makes at-least-once redelivery a
   no-op for the revision's identity; the `spec_*` verdict and the blob
   reference are still refreshed from the newer observation (the field table
   below).
3. On a genuinely new row, the `changes_outbox` row is written **in the same
   transaction**, so `source_revision_captured` reaches `info.changes` with
   semantics unchanged for existing subscribers. The event is Archiver's own
   fact, keyed as it always was on `source_revision_id`.
4. The message is acked **after** the commit. A crash in between redelivers and
   the retry is idempotent; the other order would lose a revision.

Field mapping, and the two traps in it:

| Wire field | Column | Note |
|---|---|---|
| `extracted_fingerprint` | `content_fingerprint` | **Never** cross-match with `BlobAvailableEvent.content_fingerprint` - that is Replicator's sha256 of the *raw bytes*, this is sha256 of the text extracted under `source_specs`. Different inputs, different services; a cross-match fails silently as "no revision for this blob" |
| `content_size_bytes` / `content_media_type` | same | measure the **extracted** content |
| `source_media_type` | `source_media_type` | what the **origin** served; inherits `BlobAvailableEvent.media_type`'s normalization |
| `blob_uri` | `content_cache_uri` | **a cache, not durable storage** - Replicator's temp store (`gs://co-gcs-blobs` since 2026-08-20; earlier rows carry a VM-local `file://`). Durable bytes are RepSpec replication's job. Refreshed on a re-observation together with the horizon below (archiver#201) |
| `blob_expires_at` | `content_cache_expires_at` | `None` records *absence*; never substitute a TTL guessed from Replicator's policy. **Forward-only on re-observation** (archiver#201): Replicator's TTL runs from last reference, so an unchanged fingerprint legitimately re-arrives with a later horizon and the row takes it; an older, equal or unknown one leaves the stored pair alone |
| `spec_fingerprint` | `spec_fingerprint` | recorded **and compared** - see below |
| `command_id` | `command_id` | correlation back to the fetch |
| *(absent)* | `source_revision_id` | **Archiver allocates.** A service that does not own the registry does not mint registry ids |

**The `spec_fingerprint` comparison.** At ingest the value is looked up in an index of the
InfoSource's own specs, built with co-core's shared derivation
(`co_core.pure.extract.spec_fingerprint_index`, cannobserv#309, since co-core 0.8.1 - the
current floor is `pyproject.toml`'s, not this line). The outcome lands
in `spec_match` / `spec_position` (see [docs/SCHEMA.md](SCHEMA.md) - they track the *most recent*
observation, refreshed on re-observation) and is **never** a rejection -
archiver#140 makes spec delivery eventually consistent, so a producer one announcement behind is
expected, and its observation is real. Two rules come from the contract rather than from registry
policy: an **absent** fingerprint is not a mismatch (the field is optional, and a producer that has
not adopted it yet would otherwise flag on every revision), and an **unrecognised derivation tag**
is incomparable - flagging against a derivation you cannot reproduce is the false positive the tag
exists to prevent.

Failure routing: a well-formed observation the registry cannot use - a
fingerprint outside `sha256:<64 hex>`, an `info_source_id` that is not a ULID -
is quarantined to `content.revisions.dlq`, because redelivery reproduces it
exactly. A frame that does not decode at all is quarantined too, via a raw pass
over the group's pending list (`from_wire` raises before any message id reaches
the caller, so there is nothing to `dead_letter` with - see
`quarantine_undecodable`). Anything transient - the database down - leaves the
message **pending**, and it is redelivered or reclaimed by `XAUTOCLAIM`.

The HTTP write path (`POST` / `PATCH /source-revisions`) stays for authoring and
backfill; retiring it is a separate call from retiring Watcher's *use* of it
(CannObserv/watcher#253).

## Change-bus consumer - `content.artifacts` (archiver#170)

The return leg of `content.replicate`, and what finally gives
`info_item_rep_specs.public_url` an automated writer. Group
**`archiver.artifacts`**, consumer **`archiver-artifacts-1`**, same
`ARCHIVER_BUS_CONSUMER` gate as `content.revisions` - joining a group removes
messages from it, so a stray process must not. Both outcomes share the stream by design: an issuer wants one
group seeing success and failure, because "did this command close?" is one
question.

The MUST-, T- and R- numbers below are clauses of Replicator's issuer contract,
which [BUS.md](BUS.md) § **`content.replicate`** introduces.

`replication_complete` → `public_url` onto the assignment row and the command
closed. `replication_failed` → `reason` / `terminal` / `attempts` / `detail`
recorded; the command closes **only** when `terminal` is true.

- **A repeat is expected traffic** (MUST-4 / T4). A redelivery that finds
  matching bytes at the destination no-ops and re-emits the same `public_url`,
  so the writeback is idempotent by construction.
- **An unknown `command_id` is ack-and-drop.** The registry is the authority on
  what it issued; a fact about anything else is not something redelivery fixes -
  the posture `content.revisions` takes for an unknown `info_source_id`.
- **Newest occasion wins** (R3), counting only occasions that reached the wire -
  a `skipped` row produced no artifact and does not claim the slot. An older
  occasion's late fact records itself on its own `replication_commands` row
  without overwriting the assignment's newer URL.
- **Out-of-order facts are expected traffic.** `replication_commands.last_fact_at`
  is the high-water mark: a fact older than one already applied is ignored, a
  `complete` command never moves to `failed`, and `terminal` never downgrades.
  Equal timestamps are the same emission and still apply.
- **`reason` is opaque.** The vocabulary is producer-owned - Replicator's
  contract lists six tokens where co-core's docstring registers five
  (cannobserv#330) - so branching on it here would make every new token a code
  change.
- **Undecodable frames** are quarantined to `content.artifacts.dlq` by the shared
  loop before any handler sees them; a database failure raises instead, leaving
  the entry pending for redelivery.

**The reaper** (`src/core/changes/replication_reaper.py`) closes the silent case
MUST-6 names: Replicator does not guarantee that every command either succeeds or
is closed, and a provider 5xx retries unbounded while publishing nothing. A timer
(`ARCHIVER_REPLICATION_REAP_INTERVAL`, default 900s) marks commands open past
`ARCHIVER_REPLICATION_REAP_HORIZON` (default 6h) as `abandoned`. It runs on a
clock rather than off an arrival because it detects an *absence*, and it **never
re-issues** - a second artifact in a permanent store has no way back.

## Consumer names are a monitoring contract (archiver#156)

Both group consumers name themselves from their group -
`resolve_consumer_name("archiver.revisions")` -> **`archiver-revisions-1`**,
`archiver.artifacts` -> **`archiver-artifacts-1`**. The name is broker-visible in
`XINFO CONSUMERS`, so it is as fixed as the group name and derived in one place
(`src/core/changes/group_consumer.py`) rather than written out per stream.

It is **stable across restarts on purpose**. The previous `{hostname}:{pid}`
spelling minted a new registration on every restart and nothing ever called
`XGROUP DELCONSUMER`, so orphans accumulated without bound - seven on the
production broker by 2026-08-27, six dead. A stable name makes a restart *reuse*
its registration, which is why there is no shutdown cleanup hook (a `SIGKILL`
would skip one) and no startup reaper (with the name stable, the orphan set is
permanently empty; the one-time cleanup of the pre-fix orphans is a runbook step
in `deploy/README.md`).

Two facts that make this stream of registrations confusing to inspect, both
measured rather than assumed:

- **Registration happens on delivery, not on read.** An `XREADGROUP` returning
  zero entries does not register the consumer, and neither does an `XAUTOCLAIM`
  that claims nothing. So a healthy consumer on a quiet stream is **absent** from
  `XINFO CONSUMERS` - `archiver.artifacts` correctly reported 0 consumers for
  over a week on an empty stream. Absence is not evidence of a wedged consumer;
  the journal's `Bus consumer starting` line is.
- **`systemctl show archiver -p MainPID` is the `uv` wrapper**, not the uvicorn
  child that joins the group. Matching a registration against `MainPID` looked
  like a miss while the consumer was healthy. The stable name removes the
  question; the `-1` slot is not a pid.

The `-1` is a slot. `deploy/archiver.service` runs uvicorn with no `--workers`,
so there is exactly one member per group. Adding members assigns `-2` upward and
**must first raise `quarantine_undecodable`'s `min_idle_time`** above the
expected per-message processing time - see that docstring.

## Change-bus tail - `info.watch-status` (archiver#151)

The return leg of the announcement channel: Watcher broadcasts the generation it
has *applied* plus scheduler state and observation freshness
(`co_core.pure.models.changes.WatchStatusState`, cannobserv#321; producer
CannObserv/watcher#264); Archiver tails it into the persisted `watch_status`
cache and renders the watched-item panel from local state with **zero SDK
calls**. `src/core/changes/watch_status_consumer.py` holds the loop;
`src/core/services/watch_status.py` the apply. It runs under the FastAPI
lifespan, dormant unless `ARCHIVER_REDIS_URL` is set - deliberately **not**
gated on `ARCHIVER_BUS_CONSUMER`: that gate exists because a group consumer
removes messages from production's PEL, and a groupless tail removes nothing.

Shape is the config/state-stream posture, not the fact-stream one: groupless
`AsyncBusTailReader`, LWW per `info_item_id` in stream order, replay from `0-0`
on cold start, **no DLQ**. Restart resumes from the `bus_tail_cursors` row,
advanced in the same transaction as each apply.

**Three dispositions, because "retry forever" is a stall on this stream.** With
no DLQ and a cursor that only advances on success, a message that can never
succeed would spin indefinitely - silently, once log throttling kicks in. So:
a frame that will not *decode* is logged and skipped; a decoded message the
registry can never *write* (`DataError`, `IntegrityError`, `ProgrammingError`,
`NotSupportedError` - redelivery reproduces them exactly) is logged at ERROR
and skipped; anything else (the database down, a bug of ours) rewinds the
reader and retries. Skipping is safe here only because this is last-write-wins
state - the producer's periodic republish restores whatever a skip dropped -
and the classification is an allow-list on purpose: an unclassified failure
keeps retrying loudly rather than silently eating the stream.

Per message: unknown or malformed `info_item_id` → drop (the registry is the
authority on what exists); `revoked` → delete the cache row (idempotent);
otherwise upsert, and when `last_observed_at` is present, write it through to
`info_sources.last_observed_at` under the monotonic and binding-age guards
([docs/SCHEMA.md](SCHEMA.md)). Consumer rules the panel enforces: `health ==
"ok"` is the only healthy value (open vocabulary; unknown tokens render
verbatim as non-healthy); next-due derives from `last_attempt_at` +
`applied_interval`, announced `watch_spec.interval` as fallback; announced
(`info_items.announcement_generation`) vs applied generation is the drift
detector, aged from `info_items.announced_at` with a 15-minute alert threshold
(`src/dashboard/watch_panel.py`).

**Nothing here may block a registry write** - this is observability and drift
detection; a stale or absent status row degrades the panel only.
