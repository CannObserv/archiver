# deploy/

Systemd units for the Archiver VM.

| Unit / file | Type | Purpose |
|---|---|---|
| `archiver.service` | service | The live API on port 8020 (see CLAUDE.md → Server Lifecycle). Its `ExecStartPre` mirrors the cannobserv wheelhouse (see below) and asserts the Redis ≥7.0 floor when the bus is active. |
| `redis-server.dropin.conf` | service drop-in | Archiver-owned tuning for the shared Redis change-bus broker (#109). Layers on the stock `redis-server.service`; see below. |
| `archiver-bus-health.service` | service (oneshot) | One WARN-only bus-health tick: broker memory/streams/groups/DLQs, outbox stats, disk (#130). Never blocks anything; see *Bus-health timer* below. |
| `archiver-bus-health.timer` | timer | Runs the probe every 10 min. Enable with `systemctl enable --now archiver-bus-health.timer`. |

## cannobserv wheelhouse (archiver#72/#75)

`co-core` / `co-core-aio` resolve from `./.wheelhouse` (gitignored), mirrored
from the private GCS index `gs://co-gcs-pypi` by `scripts/sync_wheelhouse.py`.
The service's `ExecStartPre` runs that sync before `uv run`, so a restart always
resolves against a current wheelhouse.

Requirements on the VM:

- A read-only credential at `GOOGLE_APPLICATION_CREDENTIALS` (the
  `co-pypi-reader@co-gcs` service-account key, referenced from
  `/etc/archiver/.env`). Needs only `roles/storage.objectViewer` on the bucket.
- `uv` (already required) - the sync runs via `uv run --no-project --with
  'google-cloud-storage>=2,<4'`, so no system Cloud SDK is needed.

**Deploy step for the co-core adoption (one-time).** The unit gained an
`ExecStartPre`; reinstall it before the next restart or the parity test
(`tests/deploy/test_installed_unit_matches_repo.py`) flags drift:

```bash
sudo cp deploy/archiver.service /etc/systemd/system/ && sudo systemctl daemon-reload
# then, when safe: sudo systemctl restart archiver
```

(CI is keyless instead - the `lint`/`test` jobs authenticate via Workload
Identity Federation; see `.github/workflows/ci.yml`.)

## Redis change bus (archiver#109)

Archiver **operates** the local `redis-server` as the `info.changes` change-bus
producer + cluster control-plane. Ownership was previously un-assigned (stock
distro unit, nobody's app); #109 closes that gap before Phase 3 (Replicator)
makes the bus load-bearing. Design of record:
`docs/plans/2026-07-29-redis-bus-ownership-design.md`.

The connection string (`ARCHIVER_REDIS_URL`) is the only switch - local now,
`rediss://` managed later with no code change. Only the artifacts below are
local-broker-specific; a managed migration deletes them and swaps the env var.

**`redis-server.dropin.conf`** - tracked drop-in that tunes the stock broker
(AOF `everysec`, `maxmemory-policy noeviction`) without replacing the package
unit or editing `/etc/redis/redis.conf`. Install (one-time, needs sudo):

```bash
sudo mkdir -p /etc/systemd/system/redis-server.service.d
sudo cp deploy/redis-server.dropin.conf \
    /etc/systemd/system/redis-server.service.d/archiver.conf
sudo systemctl daemon-reload && sudo systemctl restart redis-server
# verify:
redis-cli CONFIG GET appendonly        # -> yes
redis-cli CONFIG GET maxmemory-policy  # -> noeviction
redis-cli CONFIG GET maxmemory         # -> must NOT be 0 (see below)
```

To change the cap later, prefer applying it live - no restart, no dropped client
connections - and let the unit supply it from the next restart onward:

```bash
# edit ExecStart in deploy/redis-server.dropin.conf, then:
sudo cp deploy/redis-server.dropin.conf \
    /etc/systemd/system/redis-server.service.d/archiver.conf
sudo systemctl daemon-reload
redis-cli CONFIG SET maxmemory <value from ExecStart>   # applies now, no restart
```

Pass the value **exactly as `ExecStart` spells it** - `CONFIG SET` accepts the
same unit suffixes, so there is no byte conversion to get wrong and no second
copy of the number to drift.

`CONFIG SET` is not persisted (no `CONFIG REWRITE`), which is what keeps the unit
authoritative. The flip side is that it can drift the *running* broker from the
tracked file in either direction, and the file-parity test cannot see that - so
`scripts/check_redis_floor.sh` reads the live value at every `archiver.service`
start and warns when it is `0`.

**`maxmemory` is load-bearing, not decoration (archiver#128).** `noeviction`
with the default `maxmemory 0` is *inert*: there is no ceiling to refuse writes
at, so an untrimmed stream never produces the retryable write errors the
"a stream broker must never evict" reasoning assumes - it grows until the kernel
OOM-killer takes `redis-server`, costing the whole broker plus an AOF-replay
restart. The explicit cap converts that into bounded, instance-wide `OOM command
not allowed` errors. Those are classified **transient** by the outbox publisher
(`_TRANSIENT_PUBLISH_ERRORS` in `src/core/changes/publisher.py`), so a memory
incident caused by *any* stream on this shared broker stalls `info.changes`
publishing without dead-lettering valid events. **The cap and that classification
are one decision - do not change either alone.** Sizing rationale is in the
drop-in's header comment.

**The cap changes the failure mode for every producer on this broker, not just
ours.** Once the cap is reached, `XADD` is refused instance-wide - Watcher's
`content.fetch` and Replicator's `content.blobs` included. Archiver rides that
out because the outbox retries indefinitely on a transient error; **whether the
other producers have an equivalent durable retry is their own property, and
Archiver does not assert it.** A producer that publishes straight from a request
handler with no outbox will *drop* on OOM. Raised on CannObserv/watcher#245 and
CannObserv/replicator#19 so each producer's durability under OOM is a stated
assumption rather than an assumed one. The `Producer durability under OOM` column
below records the current answer.

AOF needs no separate cap: `auto-aof-rewrite-percentage 100` /
`auto-aof-rewrite-min-size 64mb` self-bound the file at roughly 2× the dataset,
so bounded retention bounds the AOF. The independent exposure is fork/COW at
rewrite time, which `maxmemory` also caps.

### Streams on this broker

Archiver **operates** the broker and, since archiver#139, consumes one of the
streams on it. Inventory, so a future lag dashboard is built against what is
actually here. Cells marked *(target)* describe the post-cutover arrangement, not
what is running today. The `DLQ` column names who **writes** each one; who
**drains** it is a separate question, answered under *Who drains a DLQ* below:

| Stream | Producer → consumer | Kind | Consumer group | Health primitive | DLQ | Producer durability under OOM |
|---|---|---|---|---|---|---|
| `info.changes` | Archiver → Replicator *(target)* | event | none *yet* - Replicator adds one | producer-side outbox stats (depth / oldest-unpublished age / dead-lettered count, archiver#112): dashboard badge + the drain loop's periodic journald line, plus the bus-health timer (#130) re-running the same query from outside the publisher process - the surface that keeps reporting when the publisher is down. Group lag once consumed | `info.changes.dlq` *(target)* | **retries indefinitely** - transactional outbox, OOM classified transient |
| `content.fetch` | Watcher → Replicator | command | `replicator.fetch` (exactly one - competing consumers) | `XPENDING` / group lag | `content.fetch.dlq` | **unasserted** - CannObserv/watcher#245 |
| `content.blobs` | Replicator → Watcher | fact | one per consuming service | group lag per group | `content.blobs.dlq` | **unasserted** - CannObserv/replicator#19 |
| `content.revisions` | Watcher → **Archiver** *(producer target: CannObserv/watcher#253)* | fact | `archiver.revisions` (one per consuming service) | `XPENDING` / group lag - **the first group Archiver owns**; probed by the bus-health timer (#130): non-zero pending across two consecutive ticks WARNs (healthy steady state is 0 - a state to name, not a number to guess) | `content.revisions.dlq` - written by the ingest consumer's quarantine path | **unasserted** - CannObserv/watcher#253 |
| `content.artifacts` | Replicator → **Archiver** *(consumer live - archiver#170)* | fact, broadcast (both replicate outcomes share it, so an issuer sees success and failure in one group) | `archiver.artifacts` (one per consuming service) | `XPENDING` / group lag; issuer-side, `information.replication_commands` rows still `state='requested'` past the reap horizon - the reaper logs each abandonment at WARNING | `content.artifacts.dlq` - written by this consumer's quarantine path | **n/a (consumer)** - producer durability is CannObserv/replicator#34's |
| `content.fetch-policy` | Watcher → Replicator workers *(producer live - full set republished on `*/5 * * * *`, capped by producer-side `BusPublish.maxlen` 50k, CannObserv/watcher#265)* | config/state, broadcast, last-write-wins per host key | **none, permanently - by design** | **last-entry age via `XINFO STREAM`** - probed by the bus-health timer (#130), WARN over 15 min (3× the republish period) | **none applies** | **self-correcting** - full set is republished on a timer |
| `info.registry` | **Archiver** → Watcher *(consumer live - watcher#254)* | config/state, broadcast, last-write-wins per `info_item_id`, `generation`-ordered | **none, permanently - by design** (every consumer needs every message; a group accumulates a PEL nothing drains) | **last-entry age via `XINFO STREAM`** - on a non-empty corpus the snapshot guarantees ≥1 entry/hour, so an age over ~2× the snapshot interval means the producer is down; an empty or never-announced registry publishes nothing, so the alarm needs a corpus-size guard. See #147 | **none applies** - a state message has nothing to close; quarantine is terminal and the next full set supersedes | **split by path**: deltas ride the transactional outbox and retry indefinitely (OOM transient); snapshots have **no retry** - one lost to an outage is corrected by the next period, not a re-attempt |
| `content.replicate` | **Archiver** → Replicator *(producer live - archiver#169; consumer shipped for `gcs`, CannObserv/replicator#34)* | command | `replicator.replicate` (exactly one - competing consumers, `content.fetch`'s posture) | `XPENDING` / group lag, plus the issuer-side view `information.replication_commands` gives: rows still `state='requested'` past the reaper horizon, which the reaper (archiver#170) closes as `abandoned` and logs at WARNING | `content.replicate.dlq` - Replicator's to write; Archiver provisions nothing here | **retries indefinitely** - transactional outbox, OOM classified transient. **Never XTRIMmed by Archiver**: capping a command stream deletes commands the consumer group has not delivered and orphans the PEL entries naming them, so the topic is carved out of the drain loop's trim set (`no_trim_topics`) |
| `info.watch-status` | Watcher → **Archiver** *(consumer live - archiver#151; producer live - CannObserv/watcher#264, republish `*/5 * * * *`, producer-side `maxlen` 50k)* | config/state, broadcast, last-write-wins per `info_item_id` | **none, permanently - by design** - Archiver tails groupless (`AsyncBusTailReader`), resuming from its own `bus_tail_cursors` row rather than a full `0-0` replay | consumer-side: staleness of the `watch_status` cache vs the producer's republish period; broker-side last-entry age probed by the bus-health timer (#130), WARN over 15 min | **none, matching `content.fetch-policy`** - **two** skip paths, both durable (the skip advances the persisted cursor) and both logged at ERROR: a frame that will not *decode*, and a decoded message the registry can never *write* (a value outside a column's domain, a constraint violation). With no DLQ and a cursor that only advances on success, retrying either forever would stall the stream silently; the periodic republish is what supersedes a skip. Everything else (broker or DB down) rewinds and retries rather than skipping | **self-correcting** - coalesced level signals, full republish on a timer (watcher#264) |

⚠️ **`content.replicate` is the one stream where a test message is not free.**
Every other topic here carries a fact or a piece of state - the worst a stray
one costs is a confusing dashboard. A replicate command asks another service to
write bytes into a **permanent** store, and one of the providers (archive.org)
cannot be deleted at all. Two rules follow, and neither is enforceable by the
broker:

- **Never point a dev or test process at the production broker.**
  `ARCHIVER_DEV_REDIS_URL` is unset by default and prod's `ARCHIVER_REDIS_URL`
  is never inherited (the Redis analogue of the DB `_test` guard); #157 is what
  the DB half of that lesson cost, and #162 is what a DLQ full of test residue
  costs to clean up.
- **The "Replicate now" button (archiver#171) writes for real.** It is an
  operator action on the live dashboard - port 8020 - and it enqueues a genuine
  command against the item's latest revision. It is `hx-confirm`-guarded for
  that reason. There is no dry-run.

**`content.revisions` is Archiver's first consumer role** - every other row is a
stream it operates for someone else. Two operational consequences: the
`archiver.revisions` group is the first thing on this broker whose *lag* is
Archiver's own problem (a stalled consumer means revisions stop being recorded,
silently, while the stream keeps growing), and `content.revisions.dlq` is the
first DLQ this service writes rather than merely provisions. Group membership is
gated on `ARCHIVER_BUS_CONSUMER=1`, set only in `deploy/archiver.service` - a
second process in the group silently takes half the revisions.

#### Who drains a DLQ (archiver#162)

Three roles, and no two of them are reliably the same service:

- **Writer** - whichever service's consumer calls `AsyncBusConsumer.dead_letter()`
  on that topic; the `DLQ` column above names it per stream. Archiver writes
  `content.revisions.dlq` and `content.artifacts.dlq`, Replicator writes
  `content.fetch.dlq` and `content.replicate.dlq`, and the groupless config/state
  streams can write none at all.
- **Drainer - Archiver, for every DLQ on this broker.** Same claim as the broker
  itself (#109): operating the instance includes emptying the queues on it,
  including the ones another service writes. A DLQ with nobody named against it
  is a DLQ nobody empties, which is exactly how `content.fetch.dlq` reached 110.
- **Polluter** - whoever put junk in it, which is automatically neither of the
  above. The 110 were Replicator's writes, of Watcher's commands, caused by
  Archiver's test suite (#157).

**Resting state is depth 0 on every `*.dlq` key.** That is the invariant worth
holding: a non-zero depth then means a real dead-letter awaiting triage, rather
than a number an operator has to know the backstory of before ignoring it. The
bus-health timer (#130) scans every `*.dlq` key each tick and WARNs on any
non-zero depth; a dashboard rendering of the same probe is archiver#147's,
alongside the other streams that cannot use group lag.

Draining is never in-band cleanup. Audit, back up, trim, verify - in that order,
because reversing it destroys the evidence you needed to justify the trim:

```bash
redis-cli XLEN content.fetch.dlq                    # what you are about to delete
redis-cli --no-raw XRANGE content.fetch.dlq - + > /var/tmp/fetch-dlq-$(date +%F).txt
# read it: every payload residue, or is a real permanent failure hiding in there?
redis-cli XINFO STREAM content.fetch.dlq | grep -A1 last-generated-id
redis-cli XTRIM content.fetch.dlq MINID <last-generated-id, +1ms>
redis-cli XLEN content.fetch.dlq                    # -> 0
```

`XTRIM MINID`, not `DEL`: the boundary confines the deletion to the entries you
actually audited - anything dead-lettered while you were reading carries a higher
id and survives - and the key plus any consumer groups stay in place.

Worked example, the #162 drain (2026-08-19): 110 entries, every one a
`content_fetch` command against `example.com`, all inside one 18-minute window on
2026-08-13, zero non-residue payloads, zero consumer groups on the key.
`XTRIM content.fetch.dlq MINID 1786635782730-0` removed exactly those 110 and
left the key at depth 0.

### Orphaned consumer registrations, one time only (archiver#156)

Archiver's group consumers used to name themselves `{hostname}:{pid}`, so every
restart that received a message left a registration behind and nothing reaped it.
Seven had accumulated on `archiver.revisions` by 2026-08-27, six of them dead.
The consumers are now named for their group (`archiver-revisions-1`,
`archiver-artifacts-1`), stable across restarts, so **this cannot recur** - which
is why the cleanup is a one-time procedure here rather than a startup reaper.

Order matters: **deploy, restart, then reap.** Reaping before the restart leaves
the running process's own registration behind.

⚠️ **`XGROUP DELCONSUMER` destroys that consumer's pending entries.** Never reap
a consumer with a non-zero PEL - that is a stranded message needing `XAUTOCLAIM`,
not an orphan. The loop below therefore re-reads `pending` per consumer and skips
any that is non-zero, rather than trusting a check the operator ran beforehand;
`XGROUP DELCONSUMER` returns how many entries it destroyed, and by the time you
can read that number they are already gone.

It also skips the **current** consumer by name rather than matching the old
`{hostname}:{pid}` shape. A `watcher:` filter would be specific to this VM's
hostname and would silently match nothing anywhere else, which reads identical to
"already clean".

```bash
reap_orphans() {   # stream group live-consumer-name
  redis-cli XINFO CONSUMERS "$1" "$2" \
    | awk '/^name$/{getline n} /^pending$/{getline p; print n, p}' \
    | while read -r name pending; do
        if   [ "$name" = "$3" ];  then echo "keep $name (current consumer)"
        elif [ "$pending" != 0 ]; then echo "SKIP $name - pending=$pending, stranded not orphan"
        else redis-cli XGROUP DELCONSUMER "$1" "$2" "$name" >/dev/null && echo "reaped $name"
        fi
      done
}

reap_orphans content.revisions archiver.revisions archiver-revisions-1
reap_orphans content.artifacts archiver.artifacts archiver-artifacts-1
```

`archiver.artifacts` carried 0 registrations as of 2026-08-27 - its stream has
never delivered an entry, and registration happens on delivery - so that second
call is expected to print nothing. It is in the procedure anyway because the
group used the same pre-fix naming and would have leaked identically once
replication traffic started.

**Do not verify by looking for `archiver-revisions-1`.** Registration happens on
*delivery*: an `XREADGROUP` that returns zero entries does not register the
consumer, so on a quiet stream the new name is correctly absent and appears when
traffic next arrives. Verify from the journal instead:

```bash
sudo journalctl -u archiver -n 200 | grep 'Bus consumer starting'
```

The `info.changes` health row spent a while naming a primitive that did not
exist; archiver#112 (badge + journald line) and the bus-health timer below
closed that gap. Left as a reminder of the failure class: a health column an
operator would assume is wired up must either be real or carry a ⚠️.

**`content.fetch-policy` is monitoring-blind to consumer-group lag, and always
will be (archiver#128 / cannobserv#285).** Every worker needs every message, so
the consumer reads groupless (`co_core_aio.bus.AsyncBusTailReader`, in-memory
cursor, replayed from `0-0` at boot) - a group here would accumulate a PEL
nothing drains. Consequence: **`XPENDING` reports nothing for this stream whether
or not a single consumer is alive.** Any dashboard or alert that reads "no
pending entries" as healthy will read this stream as healthy while it is dead.
Use last-entry age instead - it at least catches a producer that stopped
republishing.

Note the *permanently* in that row. `info.changes` is groupless today too, but
only because its consumer isn't built; it gains a group and becomes
lag-monitorable, exactly as `content.revisions` just did.
`content.fetch-policy` does not.

For the same reason it has **no DLQ**. `dead_letter()` is a method on
`AsyncBusConsumer` - it copies the frame to `dlq_name(topic)` and acks the
original. A groupless tail reader has no ack and no delivery accounting, so
nothing can write `content.fetch-policy.dlq` and nothing would trigger one.

**Retention is the producer's, not ours, for this stream.** A stream whose
producer republishes its full set on a timer grows without bound unless trimmed;
`BusPublish.maxlen` (co-core ≥0.7.7) rides the trim on each publish, and the knob
sits with Watcher (CannObserv/watcher#265: `maxlen` 50k on both LWW streams)
because the consumer's replay-from-`0-0` boot depends on the retention policy -
it is a contract property, not broker tuning. Our exposure is the shared-instance
blast radius, which `maxmemory` above bounds and the bus-health timer watches.

**Bus-health timer (archiver#130).** `archiver-bus-health.{service,timer}` - a
periodic oneshot (`OnUnitActiveSec=10min`), WARN-only to journald, running
`python -m src.core.bus_health`. It is deliberately a standalone unit rather
than a check inside the publisher loop or `check_redis_floor.sh`: an
`ExecStartPre` fires once at process start and unbounded growth is an
after-start condition, and anything riding the publisher loop stops reporting
exactly when the publisher is down. Per tick it probes:

- `used_memory` vs `maxmemory` (WARN at 75% - before the `noeviction` cap
  starts refusing `XADD` instance-wide), and `maxmemory 0` (inert ceiling);
- `XLEN` per stream, each threshold derived as **that stream's own retention
  cap + 10%** - so a breach means the retention mechanism broke, not that
  traffic grew. Three caps apply and they are not interchangeable: 110k for
  fact streams on the operator-side `XTRIM` (`ARCHIVER_REDIS_STREAM_MAXLEN`),
  55k for `info.registry` (capped on publish instead, `ARCHIVER_REGISTRY_STREAM_MAXLEN`),
  55k for the two LWW streams (Watcher's producer-side `maxlen`). The
  thresholds are computed from those constants, not copied. `content.replicate`
  is the exception: never trimmed by design, so its breach message says
  "volume milestone", not "broken cap";
- last-entry age for the groupless streams (15 min for the two `*/5` LWW
  streams; 2h for `info.registry`'s hourly snapshot, skipped while the stream
  is empty - the corpus-size guard);
- `XPENDING` on the archiver-owned groups (`archiver.revisions`,
  `archiver.artifacts`) - WARN on non-zero across two consecutive ticks, with
  the count carried in `StateDirectory=archiver-bus-health`;
- every `*.dlq` key via `SCAN` - WARN on any non-zero depth;
- the #112 outbox stats query, from outside the publisher process;
- `/` disk headroom (WARN at 90% used or under 2 GiB free).

`content.blobs` is deliberately absent - that role boundary has no read-only
exception (CLAUDE.md); its DLQ is still scanned, because the drainer role
covers every `*.dlq` on this broker. The service unit holds the second
sanctioned `Environment=ARCHIVER_ALLOW_PRODUCTION_DB=1` (read-only outbox
query; the guard's rule - units, never env files - is unchanged) and must
never set `ARCHIVER_BUS_CONSUMER`. `tests/deploy/test_bus_health_units.py`
pins both, plus installed-copy parity.

**`archiver.service` ordering + floor.** The unit declares
`Wants=redis-server.service` + `After=redis-server.service` (soft ordering - the
outbox tolerates broker downtime, so no `Requires=`/`BindsTo=`) and an
`ExecStartPre` that runs `scripts/check_redis_floor.sh` to assert the server is
≥7.0 (the consumer path's `XAUTOCLAIM` requirement) when `ARCHIVER_REDIS_URL` is
set. That script also reads the **live** `maxmemory` and warns when it is `0` -
the only check that sees the running value rather than the tracked file. It warns
rather than blocks: an uncapped broker doesn't break the producer, and refusing
to start the API over a broker tuning value would turn tuning drift into an
outage. Blocking is reserved for the version floor, where the consumer path is
genuinely broken. The probes are `timeout`-bounded (`ARCHIVER_REDIS_FLOOR_TIMEOUT`, default 5s)
so it can never hang startup, and warns when `redis-cli` lacks TLS support for a
`rediss://` URL; it soft-skips (never blocks) on a dormant or unreachable broker
and blocks only a genuinely-<7.0 reachable one. Reinstall the unit after any edit
(see the parity note under the wheelhouse section) -
`tests/deploy/test_installed_unit_matches_repo.py` flags drift.

**`info.registry` retention is different in kind** (archiver#141): consumers
boot by replaying from `0-0`, so the floor is "at least one full snapshot plus
the deltas since" - a consumer contract, not operator housekeeping. It is
therefore **excluded from the periodic `XTRIM` loop** and capped on every
publish via `BusPublish.maxlen` instead (`ARCHIVER_REGISTRY_STREAM_MAXLEN`,
default 50k, sized from key count × sets retained - never from the
`info.changes` number). Snapshot period: `ARCHIVER_REGISTRY_SNAPSHOT_INTERVAL`,
default 3600s; operator republish-now: `POST
/api/v1/tools/republish-registry-announcements`.

**Retention.** With no consumer yet, entries accumulate on `info.changes`. The
Archiver outbox publisher caps the stream operator-side via a periodic
`XTRIM ... MAXLEN ~ N` (co-core exposes no XADD trim arg); `N` is
`ARCHIVER_REDIS_STREAM_MAXLEN` (default 100000).

**Activation.** Set `ARCHIVER_REDIS_URL=redis://localhost:6379/0` in
`/etc/archiver/.env` and restart `archiver`; the outbox publisher starts and
drains to `info.changes`. Roll back by unsetting it and restarting.

## Stopping a fetch - the operator runbook (archiver#142)

With the Watcher SDK gone, the item-level control plane is Archiver's alone.
Recorded here because it is an operational fact that no longer has a second
route, and because the coarser fallback is not obvious from the dashboard.

- **Item-level pause is Archiver's dashboard, and only Archiver's dashboard.**
  Pause/resume writes `info_items.watch_active` and announces it; Watcher applies
  `active` unconditionally on reconcile. A Watcher-local pause is therefore
  **not sticky** - it is reverted on the next announcement. That is the design
  working as intended (one control plane, level-triggered), not a bug, and
  CannObserv/watcher#254 removes or 409s the affordance on that side so the
  question stops being askable by pressing a button.

- **Host-level break-glass is `domain_suspended`,** set in Watcher. Reconciliation
  does not touch it because it is *mechanism* rather than *policy* - the same
  reason an archived WatchedItem is Watcher's business and not the registry's.
  Use it when a whole host must stop being fetched, or when Archiver is
  unreachable and an item cannot be paused the normal way.

- **Archiver is now a single point of operational dependency for stopping one
  item.** This is the accepted price of a single control plane. `domain_suspended`
  is the coarser fallback; there is no finer one, so an Archiver outage means
  item-level pause is unavailable until it returns.

The divergence between what was announced and what Watcher is actually running
stays visible either way: `applied_active` and `applied_interval` come back on
`info.watch-status` and render on the InfoItem detail panel, next to the
announced-vs-applied generation drift.
