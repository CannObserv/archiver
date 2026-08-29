# archiver - change-bus contracts

Everything Archiver puts on or takes off the Redis bus: the outbox producer and
the three streams it publishes - `info.changes`, `info.registry`,
`content.replicate` - and the three it consumes - `content.revisions`,
`content.artifacts`, `info.watch-status`. HTTP routes and their SDK wrappers
live in [API.md](API.md); this file is the wire side of the same surface.

## Producing - the outbox, the envelope, and the three published streams

**Change-bus producer (co-core bus, archiver#106):** Writes rows to
`information.changes_outbox` in the same transaction (the **outbox stays
archiver-owned** - it is the producer-side delivery guarantee); the publisher
background task (`src/core/changes/publisher.py`) drains the outbox and publishes
each row to the Redis Stream `info.changes` **through the shared co-core bus
driver** - `co_core_aio.bus.AsyncBusPublisher.execute(BusPublish(...))`, with the
wire envelope built by `co_core.pure.adapters.bus.envelope.to_wire`. Publisher
only starts when `ARCHIVER_REDIS_URL` is set. Two event types:

| Event type | Trigger | Payload type (co-core) |
|---|---|---|
| `source_revision_captured` | New `SourceRevision` insert - from `POST /source-revisions` **or** from a `content.revisions` observation, on the non-idempotent path either way | `co_core.pure.models.changes.SourceRevisionCapturedEvent` |
| `info_item_primary_changed` | New active `InfoItemSource` binding created (`POST /info-items/{id}/info-sources`) | `co_core.pure.models.changes.InfoItemPrimaryChangedEvent` |

The payload models live in **co-core** (`co_core.pure.models.changes`) - lifted
from archiver in cannobserv#261 so the whole cluster shares one contract. Emit
sites construct the **strict `*Emit` subclasses** (`SourceRevisionCapturedEmit` /
`InfoItemPrimaryChangedEmit`, `extra="forbid"`) for emit-time typo-catch; the
canonical classes are `extra="ignore"` (consumer-safe forward-compat). The
**wire envelope** is the XADD field map `key` / `payload` (full event JSON) /
`event_type` / `schema_version` / `occurred_at` / `content_type`; the idempotency
`key` is derived per type by co-core (`source_revision_id`; the
`{info_item_id}:{new_info_source_id}` composite).

**Producer-side observability (archiver#112)** - the Archiver half of the
archiver#109 monitoring split (consumer lag/DLQ is Replicator's, Phase 3).
`src/core/changes/outbox_stats.py` computes three indexed numbers on request:
`unpublished_count` and `oldest_unpublished_age_seconds` over the drain's live
predicate, and `dead_lettered_count` over the archiver#107 terminal rows.
Surfaced twice: the dashboard badge (`/dashboard/health/outbox`, PAGES.md) and
a periodic "Outbox stats" journald line from the drain loop every
`STATS_LOG_INTERVAL_SECONDS` (300s; first iteration immediately) - INFO when
healthy, WARNING while any dead-lettered row exists, so a retired poison row
stays visible past its one-time dead-letter ERROR. Deliberately **not** on
`/health`: that route is unauthenticated and DB-free (pure liveness), and these
numbers are neither.

**Published-row retention (archiver#189)** - `src/core/changes/outbox_prune.py`
deletes rows whose `published_at` is older than `ARCHIVER_OUTBOX_RETENTION_DAYS`
(default 30), in bounded batches, on the drain loop's own cadence
(`PRUNE_INTERVAL_SECONDS`, 3600s; first iteration immediately). Once a row is
published the outbox's delivery guarantee is discharged and the row is only
forensic - `bus_message_id` correlating it to a stream entry - and the window is
sized against that: `info.changes` is itself capped, so a much longer retention
correlates to entries that have been trimmed away.

Two states are never pruned. **Live** rows are the drain's own queue, where an
ancient row is the backlog the #112 stats exist to surface, not garbage.
**Dead-lettered** rows are the archiver#107 post-mortem record and the #112
danger signal; they are also, by that exemption, the one set on this table with
no retention at all. `ix_changes_outbox_published` (partial, `published_at IS
NOT NULL`) backs the pass - both other partial indexes exclude published rows.

It rides the drain loop rather than a systemd timer deliberately: a timer would
need `ARCHIVER_ALLOW_PRODUCTION_DB`, and a third sanctioned holder of a
write-capable production-DB opt-in is too high a price for deleting delivered
rows. There is no coverage hole - a published row can only exist if the drain
ran. One INFO line ("Outbox pruned") per pass that actually deleted something;
silence is the healthy steady state.

**Broker-side observability (archiver#130)** - the `archiver-bus-health`
systemd timer runs `src/core/bus_health.py` every 10 minutes: memory headroom,
per-stream `XLEN` and last-entry age, two-tick `XPENDING` on the
archiver-owned groups, `*.dlq` depths, disk, and the #112 outbox query
re-run from outside the publisher process (the drain-loop stats line above
stops exactly when the publisher does). WARN-only journald lines from logger
`src.core.bus_health`; full check list and thresholds in `deploy/README.md`.
`bus_health` is also the shared probe module the archiver#147 dashboard panel
renders from: `collect_group_lag()` is the per-request half, narrowed to the
archiver-owned groups' `XPENDING` and `*.dlq` depths so a page load costs four
commands rather than the timer's full inventory sweep. Two contracts differ
there, both because the caller is a request handler: a broker error propagates
(the panel must badge "could not measure" apart from "measured zero"), and the
two-tick pending rule is absent (it debounces a periodic alarm; a dashboard
shows one instant and the operator can refresh).

**`info.registry` - the registry announcement channel (archiver#141).** A second
producer surface, *config/state* kind rather than fact: per-InfoItem LWW state,
keyed by the `info_item_id` payload field and ordered by a monotonic
`generation` (`info_items.announcement_generation`, bumped atomically in the
mutation's transaction; **never `0` on the wire** - archiver#161, so the return
leg's `applied_generation = 0` unambiguously means "nothing applied yet").
Payload: `co_core.pure.models.changes.RegistryAnnouncementState`
(emit sites use `RegistryAnnouncementEmit`). Consumer: Watcher's reconcile loop
(watcher#254), replaying grouplessly from `0-0`.

- **Deltas** ride the same outbox: every registry mutation route calls
  `src/core/services/registry_announcement.py` inside its transaction - a rolled
  back mutation leaves no orphaned announcement. Emit rule: an item with an
  active primary binding and non-empty `source_specs` announces **live**;
  previously-announced without one announces **revoked**; never-announced
  sourceless items emit nothing. One InfoSource mutation fans out to every item
  it actively backs. Swaps announce exactly once, with the final state.
- **Snapshots** bypass the outbox (`src/core/changes/registry_snapshot.py`): a
  full-set republish direct to the stream at startup and every
  `ARCHIVER_REGISTRY_SNAPSHOT_INTERVAL` (default 3600s), reading generations
  without bumping them, tombstones included (`revoked_info_items`). **No
  retry** - the next period is the repair. Operator republish-now:
  `POST /tools/republish-registry-announcements`.
- **Retention rides the publish** (`BusPublish.maxlen`,
  `ARCHIVER_REGISTRY_STREAM_MAXLEN`, default 50k): consumers replay from `0-0`,
  so the floor is one full set plus the deltas since. The topic is excluded
  from the fact stream's periodic `XTRIM`.

**`content.replicate` - the replication command channel (archiver#169).** A third
producer surface, *command* kind: exactly one consumer group
(`replicator.replicate`, competing consumers), `content.fetch`'s posture. Payload:
`co_core.pure.models.changes.ContentReplicateCommandEmit`; idempotency key is the
bare `command_id`. Archiver is the **sole issuer** - the normative contract is
Replicator's `docs/contracts/content-replicate-issuer-contract.md`, where MUST-1,
MUST-2, MUST-4 and MUST-6 of the `content.fetch` issuer contract apply verbatim
and MUST-7 *inverts* into a scheduling obligation on this side.

- **One command per active assignment**, never one carrying a list: a
  `command_id` identifies an *occasion*, and N provider writes fail, retry and
  complete independently, so a list-shaped command would leave a partial outcome
  with no correlator.
- **Issued on the revision insert, in its transaction** - `record_revision`
  calls `src/core/services/replication_issuance.py`, which writes the
  `replication_commands` row (MUST-2's durable mapping) and the outbox row
  together. The idempotent no-op issues nothing: a redelivery is the same
  occasion.
- **`command_id` is minted fresh per occasion** and never derived from
  `(rep_spec_id, info_item_id)` or anything else stable. A derived id breaks the
  second legitimate re-replication in a TTL-bounded, intermittent way.
- **Archiver renders `destination`** (the contract's T3/R1) - the RepSpec's
  `path_template` never travels. See `docs/SCHEMA.md` for the template contract
  and `src/core/replication/` for the one parser that both validates and renders.
- **`media_type` echoes `source_revisions.source_media_type`**, falling back to
  `application/octet-stream`: Replicator's blob store discards the media type it
  was handed, so an omitted value lands in a *permanent* store as
  `application/octet-stream` forever.
- **Skips are rows, not silence.** An assignment that cannot be issued gets a
  `replication_commands` row with `state="skipped"` and a local reason -
  `blob_absent`, `blob_expired_locally`, `unrenderable`,
  `destination_collision`, `unsupported_command`. These are Archiver's own
  vocabulary for what it decided *before* publishing, deliberately distinct from
  Replicator's producer-owned failure tokens. Only the colliding assignments are
  skipped on a `destination_collision`; the rest of the fan-out still ships.
- **Never `XTRIM`med by Archiver.** Capping a command stream deletes commands the
  consumer group has not delivered and orphans the PEL entries naming them, so
  the topic is carved out of the drain loop's trim set.
- **Outcomes are not yet consumed.** `content.artifacts` carries
  `replication_complete` / `replication_failed`; nothing reads it until
  archiver#170, so `public_url` still has no automated writer and no reaper
  exists for a command that closes without a fact.

`source_revision_captured` schema_version is now **2** - `bindings[*].role` field removed. Consumers must branch on `schema_version` before destructuring. `info_item_primary_changed` carries `old_info_source_id` (null on first assignment, non-null on succession) and `new_info_source_id`. Subscribers use it to discover URL succession.

**Bus event versioning convention.** Every bus event payload carries
`schema_version: int` (start at `1`, monotonic). Bump only on *incompatible*
reshapes - field removal, type change, semantic redefinition. Additive
fields are not a bump; consumers must tolerate them. Apply the same
convention to any future event type added to `info.changes`.

Consumer rule: parsers must accept extra fields. With a Pydantic model,
use `ConfigDict(extra="ignore")` (or `model_construct`) on the
consumer-side mirror so additive producer fields do not raise
`ValidationError`. Branch on `schema_version` before destructuring when
the version is one the consumer recognises differently.

## Change-bus consumer - `content.revisions` (archiver#139)

Archiver's first consumer role, and one of exactly two - the other is the
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

Watcher observes; the registry decides. Per message:

1. `info_source_id` is resolved against the registry. Unknown → **ack and drop**
   with a WARNING. The registry is the authority on what exists, and redelivery
   cannot make a missing InfoSource appear.
2. The row is written through
   `src.core.services.source_revision.record_revision` - the same call
   `POST /source-revisions` makes. The existing `INSERT … ON CONFLICT …` on
   `(info_source_id, content_fingerprint)` makes at-least-once redelivery a
   no-op.
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
| `blob_uri` | `content_cache_uri` | **a cache, not durable storage** - a VM-local `file://` on Replicator's host. Durable bytes are RepSpec replication's job |
| `blob_expires_at` | `content_cache_expires_at` | `None` records *absence*; never substitute a TTL guessed from Replicator's policy |
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
