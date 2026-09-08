# deploy/

Systemd units for the Archiver VM.

| Unit / file | Type | Purpose |
|---|---|---|
| `archiver.service` | service | The live API on port 8000 (see CLAUDE.md -> Server Lifecycle). Its `ExecStartPre` mirrors the cannobserv wheelhouse (see below) and asserts the Redis >=7.0 floor when the bus is active. |
| `archiver-bus-health.service` | service (oneshot) | One WARN-only tick of the **outbox** probe: depth, oldest-unpublished age, dead-lettered count (#130, reduced by #193). Never blocks anything; see *Outbox health timer* below. |
| `archiver-bus-health.timer` | timer | Runs the probe every 10 min. Enable with `systemctl enable --now archiver-bus-health.timer`. |

**The broker is not deployed from this repo.** `redis-server.dropin.conf`, the
drop-in parity test, and the broker-side half of the health probe moved to
[CannObserv/broker](https://github.com/CannObserv/broker) under archiver#193 D6,
when the broker stopped sharing a host with archiver. What lived here had begun
measuring archiver's disk and archiver's systemd. The cluster stream inventory
went with them, to `CannObserv/broker:docs/STREAMS.md`.

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

## Redis change bus - archiver's side

Archiver **publishes** `info.changes`, `info.registry` and `content.replicate`,
**consumes** `content.revisions`, `content.artifacts` and `info.watch-status`,
and drains every `*.dlq` on the broker (#162). It no longer *operates* the
broker: archiver#193 D6 moved that role, its tuning, and the cluster stream
inventory to CannObserv/broker.

`ARCHIVER_REDIS_URL` is the only switch - unset means bus-dormant, and the
connection string is all that changes to point at a different broker.

### The two retention knobs archiver owns

Both are producer-side, and both are the *source of truth* for a warning
threshold in the broker repo's probe (see `docs/STREAMS.md` there, "Mirrored
constants"): a change here that is not mirrored leaves that threshold
stale-low, so it warns early rather than going quiet.

- **`ARCHIVER_REDIS_STREAM_MAXLEN`** (default 100000) caps `info.changes`
  operator-side, via a periodic `XTRIM ... MAXLEN ~ N` on the drain loop.
  Operator-side rather than co-core's XADD-time trim is a **choice, not an
  absence**: `info.changes` is a fact stream nothing replays, so its cap is
  housekeeping and belongs on the operator's cadence. `content.replicate` is
  carved out of that trim set entirely - capping a command stream deletes
  commands the consumer group has not delivered and orphans the PEL entries
  naming them (#169).
- **`ARCHIVER_REGISTRY_STREAM_MAXLEN`** (default 50000) caps `info.registry`
  on **every publish** instead (#141), because consumers boot by replaying from
  `0-0` and the floor is "at least one full snapshot plus the deltas since" - a
  consumer contract, not operator housekeeping. Sized from key count x sets
  retained, never from the `info.changes` number. Snapshot period:
  `ARCHIVER_REGISTRY_SNAPSHOT_INTERVAL` (default 3600s); operator
  republish-now: `POST /api/v1/tools/republish-registry-announcements`.

### The `OOM` lockstep, which now spans two repositories

`OutOfMemoryError` is classified **transient** in `_TRANSIENT_PUBLISH_ERRORS`
(`src/core/changes/publisher.py`), so a memory incident caused by *any* stream
on the shared broker stalls publishing without dead-lettering valid events.
That is only correct because the broker runs `noeviction` with an explicit
`maxmemory` cap, which lives in
`CannObserv/broker:deploy/redis-server.dropin.conf`.

**The cap and that classification are one decision - do not change either
alone (archiver#193 R5).** No test spans the two repositories; each side names
the other in a comment, and that pair of pointers is the whole mechanism.

### Outbox health timer (#130, reduced by #193)

`archiver-bus-health.{service,timer}` - a periodic oneshot
(`OnUnitActiveSec=10min`), WARN-only to journald, running
`python -m src.core.bus_health`. Per tick it runs the #112 outbox stats query
from **outside** the publisher process: depth, oldest-unpublished age,
dead-lettered count.

That last point is why it survived the split rather than being retired in
favour of the #147 dashboard panel. The publisher's own "Outbox stats" line
rides the drain loop and therefore vanishes exactly when the publisher is
down - the state an operator most needs told about - and a journald line fires
whether or not anyone is looking at a page.

Everything else it used to do is now `broker-bus-health.timer` in
CannObserv/broker, running on the broker's own node: memory headroom,
per-stream `XLEN`, last-entry age, the two-tick `XPENDING` rule, the DLQ
sweep, and disk. The state file that carried the two-tick rule between oneshot
runs went with it, so this unit is stateless and takes no arguments.

The service unit holds the second sanctioned
`Environment=ARCHIVER_ALLOW_PRODUCTION_DB=1` (read-only outbox query; the
guard's rule - units, never env files - is unchanged) and must never set
`ARCHIVER_BUS_CONSUMER`. Since the reduction it opens no Redis connection at
all. `tests/deploy/test_bus_health_units.py` pins all of that, plus
installed-copy parity.

### `archiver.service`'s Redis floor check

The unit declares **no** `redis-server` ordering. It once did - soft
`Wants=`/`After=`, since the outbox tolerates broker downtime - and that was
removed rather than loosened when the broker left the host (CannObserv/broker#1
Phase 3): there is no local unit to order against, and a `Wants=` on one pulls a
retired broker back up.

What remains is an `ExecStartPre` that runs `scripts/check_redis_floor.sh` to
assert the server is >=7.0 (the consumer path's `XAUTOCLAIM` requirement) when
`ARCHIVER_REDIS_URL` is set. That script also reads the **live** `maxmemory` and warns when it is `0` -
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



### Outbox retention, table side (archiver#189)

The same drain loop deletes
**published** `changes_outbox` rows older than `ARCHIVER_OUTBOX_RETENTION_DAYS`
(default 30; `<=0` disables) every hour, and once immediately on start, in
bounded batches - the publisher is a process issuing DELETEs against the
production table, so it is stated here and not only in the env reference. Never
pruned at any setting: **live** rows (the drain's own queue, where an old row is
the backlog `unpublished_count` / `oldest_unpublished_age_seconds` exist to
surface) and **dead-lettered** rows (the archiver#107 post-mortem record, and
therefore the one set on this table with no retention at all). Watch it with
`journalctl -u archiver | grep 'Outbox prune'` - an "Outbox pruned" INFO line per
pass that deleted something, a WARNING carrying the partial count if a pass
failed partway.

### Activation

Set `ARCHIVER_REDIS_URL=redis://default:<password>@broker:6379/0` in
`/etc/archiver/.env` and restart `archiver`; the outbox publisher starts and
drains to `info.changes`. Roll back by unsetting it and restarting.

The `default:` username is load-bearing. The empty-username form
`redis://:<password>@...` authenticates for redis-py and **fails** for
`redis-cli`, which sends a two-argument `AUTH "" <password>`: the service comes
up green while `check_redis_floor.sh` - this unit's own `ExecStartPre` - goes
silently blind on the >=7.0 floor (archiver#195).


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
