# archiver - change-bus contracts

Everything Archiver puts on the Redis bus: the outbox producer and
the three streams it publishes - `info.changes`, `info.registry`,
`content.replicate`. What it takes off - `content.revisions`,
`content.artifacts`, `info.watch-status` - and the naming contract its group
consumers follow are [BUS_CONSUMERS.md](BUS_CONSUMERS.md); the shared client
below serves both. HTTP routes and their SDK wrappers live in [API.md](API.md);
these two files are the wire side of the same surface.

## The shared client's connection policy (archiver#193)

All six bus loops share one client from `src/core/changes/bus_client.py`, never a
bare `from_url` - safe only on loopback. That module holds the reasoning; three
facts that surprise:

- **`socket_timeout` has a floor.** redis-py does not extend it for a blocking
  command, so a value at or below a loop's `BLOCK` raises on every *idle* read.
  It derives from `read_windows.LONGEST_READ_BLOCK_MS` - a leaf module, so the
  client stays upstream of the loops - whose claim a test audits by discovery.
- **`socket_connect_timeout` bounds one attempt, not the call**:
  `(retries + 1) x socket_connect_timeout`. Both clients take **zero** retries -
  a redis-py retry re-sends the command, so one on `XADD` publishes a duplicate
  the outbox cannot see. The loops own retry; the client has no opinion.
- **`from_url` is lazy**, so an unreachable broker raises nothing at startup.
  `probe_bus_reachable` PINGs once and logs at ERROR, detached, password
  redacted - a down broker must not read as an idle one.

**Why any of this is needed:** the broker stopped being `localhost` at #193 and
is now a tailnet peer, so a partition is a thing that will actually happen
rather than a thing the code merely tolerates. It still degrades rather than
loses - the outbox is the durable buffer. The URL, the measured path, and the
`default:` username that is load-bearing for `redis-cli` (archiver#195):
[reference/tailscale.md](reference/tailscale.md).

Consumer loops need no transient/poison classification of their own; what they do
on a dropped connection is pinned by `tests/core/changes/test_bus_reconnect.py`.

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
Surfaced twice: the dashboard badge (`/dashboard/health/outbox`, [HEALTH_ROW.md](HEALTH_ROW.md)) and
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
rows. A deployment that has never had `ARCHIVER_REDIS_URL` set accrues nothing to
prune, since a published row can only exist if the drain has run - but retention
still needs the drain running **now**. Unsetting `ARCHIVER_REDIS_URL` on an
instance that has been live freezes the table with whatever published backlog it
holds: it stops growing and stops shrinking, and nothing reports that. Narrow
(bus-dormant is a local-dev mode), and stated because "no coverage hole" would
be the stronger claim than the siting earns.

One INFO line ("Outbox pruned": `deleted`, `retention_days`, `capped`) per pass
that actually deleted something; silence is the healthy steady state. A failed
pass logs WARNING with the rows it had already committed - batches commit as
they go, so a mid-pass failure still deleted something real.

**Outbox observability (archiver#130, reduced by #193)** - the
`archiver-bus-health` systemd timer runs `src/core/bus_health.py` every 10
minutes and re-runs the #112 outbox query from outside the publisher process.
That is the whole tick: the drain-loop stats line above stops exactly when the
publisher does, which is the state most worth reporting, and a journald line
fires whether or not an operator is looking at the dashboard. WARN-only lines
from logger `src.core.bus_health`.

**Broker-side observability moved out of this repo (archiver#193 D6).** Memory
headroom, per-stream `XLEN` and last-entry age, the two-tick `XPENDING` rule,
the `*.dlq` sweep and disk are `broker-bus-health.timer` in
[CannObserv/broker](https://github.com/CannObserv/broker), running on the
broker's own node. Every one of them measures the broker's host; run from here
they had begun reporting archiver's disk. Check list, thresholds and the
cluster stream inventory live in that repo's `docs/STREAMS.md`.

`bus_health` still backs the archiver#147 dashboard panel: `collect_group_lag()`
reads the archiver-owned groups' `XPENDING` and `*.dlq` depths, four commands
per page load. Two contracts differ from the broker's timer, both because the
caller is a request handler: a broker error propagates (the panel must badge
"could not measure" apart from "measured zero"), and the two-tick pending rule
is absent (it debounces a periodic alarm; a dashboard shows one instant and the
operator can refresh).

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
- **Outcomes come back on `content.artifacts`** (archiver#170, landed):
  `replication_complete` / `replication_failed` are consumed by the
  `archiver.artifacts` group, which is what writes `public_url`. The silent
  case - a command that closes without either fact - is the reaper's, on its
  own timer. Both are documented in [BUS_CONSUMERS.md](BUS_CONSUMERS.md).

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
