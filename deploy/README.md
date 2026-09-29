# deploy/

Systemd units for the Archiver VM.

| Unit / file | Type | Purpose |
|---|---|---|
| `archiver.service` | service | The live API on port 8000 (see CLAUDE.md -> Server Lifecycle). Its `ExecStartPre` mirrors the cannobserv wheelhouse (see below) and asserts the Redis >=7.0 floor when the bus is active. |
| `archiver-bus-health.service` | service (oneshot) | One WARN-only tick of the **outbox** probe: depth, oldest-unpublished age, dead-lettered count (#130, reduced by #193). Never blocks anything; see *Outbox health timer* below. |
| `archiver-bus-health.timer` | timer | Runs the probe every 10 min. Enable with `systemctl enable --now archiver-bus-health.timer`. |
| `needrestart.conf.d/archiver.conf` | needrestart drop-in | `$nrconf{restart} = 'l'`: apt's hook lists restarts and never performs them, so a security update cannot restart Postgres or archiver mid-apply (#278). Install with `sudo install -m 644 deploy/needrestart.conf.d/archiver.conf /etc/needrestart/conf.d/`. |
| `99-archiver-memory.conf` | sysctl drop-in | `vm.min_free_kbytes = 65536`: the atomic-allocation reserve no cgroup setting can provide (#237). `vm.swappiness = 10`: the 4 G swapfile is a last resort (#286). See *Host memory posture*. |
| `system.slice.d/10-memory-protection.conf`, `system-postgresql.slice.d/10-memory-protection.conf` | slice drop-ins | The `MemoryLow=` grants without which a unit's own floor is inert (#237). |
| `postgresql@16-main.service.d/10-memory.conf` | service drop-in | Postgres's `MemoryLow=` floor (#237). |
| `tailscaled.service.d/10-oom.conf` | service drop-in | `OOMScoreAdjust=-400`: after the sessions, before archiver (#285). See *Host memory posture*. |
| `postgresql/16/main/environment` | cluster environment file | `PG_OOM_ADJUST_VALUE = -500` for postgres's children, which `pg_ctlcluster` reads from here and nowhere else (#285). Installed to `/etc/postgresql/16/main/`, owner `postgres`. |

**The broker is not deployed from this repo.** The broker's tuning (now
`CannObserv/broker:deploy/redis.conf.broker`), its parity test, and the
broker-side half of the health probe moved to
[CannObserv/broker](https://github.com/CannObserv/broker) under archiver#193 D6,
when the broker stopped sharing a host with archiver. What lived here had begun
measuring archiver's disk and archiver's systemd. The cluster stream inventory
went with them, to `CannObserv/broker:docs/STREAMS.md`.

It left here as `redis-server.dropin.conf` and did not survive the move under
that name: on the dedicated node the tuning is appended to `redis.conf`
(broker#1 Phase 5, archiver#196), and the drop-in slot carries unit ordering
only.


## Host memory posture (archiver#237, archiver#286)

This VM is 7.7 GiB with a 4 G swapfile on a 30 GB disk (resized 2026-09-29,
archiver#286; 3.8 GiB and no swap before), and runs `archiver.service`, Postgres
and interactive agent sessions on one kernel. The RAM is headroom, not immunity:
broker was already 8 GiB when it lost its bus. Sessions read `oom_score_adj`
**0** (measured 2026-09-29, after `exe-init` 14fd603 replaced a build that
started them at -1000, archiver#285; unchanged across the #286 reboot), so a
killer *can* take one, and `OOMScoreAdjust=` below is what puts it ahead of the
production service. An atomic allocation cannot wait for swap, so past the
reserve the kernel fails one in an unrelated process instead - how
CannObserv/broker lost its bus for 57m 48s on 2026-09-16
(gregoryfoster/skills#295). Six parts, none a substitute for another:

| Part | Where | Why |
|---|---|---|
| Pin the SocratiCode server | `~/.socraticode/pin`, `SOCRATICODE_SPEC` | Removes the 1.2 G install-at-launch peak; see `docs/SOCRATICODE.md` |
| Reserve | `MemoryLow=` on `archiver.service` (256M) and postgres (320M), granted on `system.slice` (576M) and `system-postgresql.slice` (320M) | Keeps the working sets resident under reclaim. The slice grants are load-bearing: this cgroup2 mount has no `memory_recursiveprot` and `system.slice` ships 0 |
| Deprioritise | `OOMScoreAdjust=-500` on `archiver.service`; Debian's -900 on the postmaster (its children: *Order the tail*) | Behind everything killable, never -1000 |
| Kernel reserve | `vm.min_free_kbytes = 65536` (kernel default here: ~11 MB) | The only buffer for atomic allocations, which cannot wait for swap. The cohort's absolute figure, not a share of RAM (CannObserv/replicator#99) |
| Swap | 4 G `/swapfile`, `vm.swappiness = 10` | Gives reclaim a slow path for anonymous pages instead of a hard ceiling. Reclaim weighs anonymous pages against cache 10:190 (60:140 at the default), so cache goes long before anything swaps; replicator's figures (CannObserv/replicator#99) |
| Order the tail | `OOMScoreAdjust=-400` on `tailscaled`; `PG_OOM_ADJUST_VALUE = -500` for postgres's children | Both sat at 0, level with the sessions. The kernel takes sessions and small daemons (0, the largest first), then the tunnel, then production |

**earlyoom is declined, measured at 0 (#285).** With sessions at 0 the kernel
already takes a session first: on 2026-09-29 the kernel's order, earlyoom's
package defaults and a tuned `--prefer`/`--avoid` all named the same first
victim, a session `MainThread` (470 MiB). What earlyoom changed was timing - it
killed at 10-12% available (391-469 MiB, at 3.8 GiB), page cache the kernel
reclaims before it kills anything - and, tuned, a protected tail, which the
kernel honours from `OOMScoreAdjust=` directly. Memory PSI read 0 and no boot
since 09-04 logged an OOM or an allocation failure. The comparison is on #285;
it matches CannObserv/power-map#588. (#237 declined it at -1000 for a different
reason: it skips a -1000 process as the kernel does.) If it is ever
reconsidered, swap is now present, so it needs `-s 100,100`: the default `-s 10`
waits until swap is ~90% used (host-memory.md section 4).

**Postgres's children take their score from the cluster, not systemd.**
Debian's unit gives the postmaster -900 and sets `PG_OOM_ADJUST_FILE`, so each
child writes `PG_OOM_ADJUST_VALUE` after fork - default 0. `pg_ctlcluster`
starts the postmaster on `/etc/postgresql/16/main/environment` alone, so a
systemd `Environment=` never reaches it: set there, the children still read 0
after a restart. The file is read at start - restart `postgresql@16-main`
(about 2.5 s; the outbox publisher logs one error and recovers).

`tests/deploy/test_memory_reservation.py` pins the 0 reading live: if a session
reads -1000 again, the kernel can no longer take one - check
`/exe.dev/bin/exe-init --version` and reopen #285.

Install, or restore after a rebuild:

```bash
# Create once: mkswap on a live swapfile rewrites the header the kernel is using
[ -e /swapfile ] || { sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile; }
swapon --show=NAME --noheadings | grep -qx /swapfile || sudo swapon /swapfile
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo install -m 644 deploy/99-archiver-memory.conf /etc/sysctl.d/
sudo sysctl --system
for d in system.slice.d system-postgresql.slice.d postgresql@16-main.service.d tailscaled.service.d; do
  sudo install -D -m 644 "deploy/$d/"*.conf -t "/etc/systemd/system/$d/"
done
sudo cp deploy/archiver.service /etc/systemd/system/
sudo systemctl daemon-reload          # applies every MemoryLow=, restarts nothing
sudo systemctl restart archiver       # OOMScoreAdjust= applies at start
sudo choom -p "$(systemctl show tailscaled -p MainPID --value)" -n -400   # or restart tailscaled
sudo install -m 644 -o postgres -g postgres deploy/postgresql/16/main/environment /etc/postgresql/16/main/
sudo systemctl restart postgresql@16-main   # the postmaster reads it at start
```

**Verify the effective protection, never `systemctl show`.** A unit keeps at
most the smallest `memory.low` on its way up; the live tests in
`tests/deploy/test_memory_reservation.py` walk the real `ControlGroup` and read
the MainPID's `oom_score_adj`, and skip on any other host. Re-size a floor when
its unit's `memory.peak` outgrows it, and keep each slice's grant at exactly the
sum of its children's.

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
and triages the DLQs of the two streams it consumes - `content.revisions.dlq`
and `content.artifacts.dlq` (list, discard and reprocess since #238; runbook in
`docs/BUS_CONSUMERS.md`). It no longer *operates* the broker: archiver#193
D6 moved that role, its tuning, and the cluster stream inventory to
CannObserv/broker.

**Not every `*.dlq` on the broker (#162 is superseded).** broker#1 Phase 5
split that role, and the cluster-wide claim was a corollary of operating the
instance that lost its premise with the move: **broker** detects any
non-resting `*.dlq`, captures the entries durably on first sight, and names the
owner; **the stream's own consumer** triages and trims. `content.fetch.dlq` and
`content.replicate.dlq` are replicator's, not archiver's. Triage is a judgment
about payloads, so it belongs with whoever can read them - archiver#162's 110
entries were replicator's writes, of watcher's commands. The old role would
also need instance-wide `SCAN` plus a grant on every other service's queues
under D3's per-service ACL users, which is a hole through the one model whose
payoff is that archiver cannot name `content.blobs`.

`ARCHIVER_REDIS_URL` is the only switch - unset means bus-dormant, and the
connection string is all that changes to point at a different broker.

### The two retention knobs archiver owns

Both are producer-side, and both are the *source of truth* for a warning
threshold in the broker repo's probe (see `docs/BUS-HEALTH.md` there,
"Mirrored constants"): a change here that is not mirrored leaves that threshold
stale-low, so it warns early rather than going quiet.

- **`ARCHIVER_REDIS_STREAM_MAXLEN`** (default 100000) caps `info.changes`
  operator-side, via a periodic `XTRIM ... MAXLEN ~ N` on the drain loop.
  Operator-side rather than co-core's XADD-time trim is a **choice, not an
  absence**: `info.changes` is a fact stream nothing replays, so its cap is
  housekeeping and belongs on the operator's cadence. The drain loop trims an
  **explicit allowlist** - `trim_topics`, literally `{info.changes}`, set in
  `src/api/main.py` and pinned by a test (#239) - never "every topic
  published to". It is one decision with broker's ACL grant, `+xtrim` on
  `~info.changes` alone (CannObserv/broker#34, pinned by broker#55): widen one,
  widen the other. The two DLQs are outside it: the drainer (#238) disposes with
  `XDEL` under its own `+xdel` selector, broker cut their `+xtrim`
  (CannObserv/broker#59), and they never join `trim_topics`.
  `content.replicate` is absent from it by design - capping a command stream
  deletes commands the consumer group has not delivered and orphans the PEL
  entries naming them (#169) - and `info.registry` for the reason below.
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
`CannObserv/broker:deploy/redis.conf.broker`.

**The cap and that classification are one decision - do not change either
alone (archiver#193 R5).** No test spans the two repositories; each side names
the other in a comment, and that pair of pointers is the whole mechanism.

### Outbox health timer (#130, reduced by #193)

`archiver-bus-health.{service,timer}` - a periodic oneshot
(`OnUnitActiveSec=10min`), WARN-only to journald, running
`python -m src.core.bus_health`. Per tick it runs the #112 outbox stats query
from **outside** the publisher process: depth, oldest-unpublished age,
dead-lettered count. The dead-lettered WARN clears only when an operator
discards or rearms each row by id (#191; runbook in `docs/BUS.md`) - nothing
ages one out.

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
genuinely broken. Both probes are `INFO` (`server`, then `memory`), so archiver's
broker ACL needs `+info` and **not** `+config|get` - that grant cannot be narrowed
to one parameter on Redis 7.0 and also reads `requirepass` (archiver#257,
CannObserv/broker#50). The probes are `timeout`-bounded (`ARCHIVER_REDIS_FLOOR_TIMEOUT`, default 5s)
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
