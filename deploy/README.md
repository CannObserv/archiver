# deploy/

Systemd units for the Archiver VM.

| Unit / file | Type | Purpose |
|---|---|---|
| `archiver.service` | service | The live API on port 8020 (see CLAUDE.md → Server Lifecycle). Its `ExecStartPre` mirrors the cannobserv wheelhouse (see below) and asserts the Redis ≥7.0 floor when the bus is active. |
| `watcher-live-drift.service` | oneshot | Layer C (#70): detect `watcher_client` snapshot drift vs **live** Watcher and open a regen PR. |
| `watcher-live-drift.timer` | timer | Fires the oneshot daily. |
| `redis-server.dropin.conf` | service drop-in | Archiver-owned tuning for the shared Redis change-bus broker (#109). Layers on the stock `redis-server.service`; see below. |

## cannobserv wheelhouse (archiver#72/#75)

`co-core` / `co-core-aio` resolve from `./.wheelhouse` (gitignored), mirrored
from the private GCS index `gs://co-gcs-pypi` by `scripts/sync_wheelhouse.py`.
The service's `ExecStartPre` runs that sync before `uv run`, so a restart always
resolves against a current wheelhouse.

Requirements on the VM:

- A read-only credential at `GOOGLE_APPLICATION_CREDENTIALS` (the
  `co-pypi-reader@co-gcs` service-account key, referenced from
  `/etc/archiver/.env`). Needs only `roles/storage.objectViewer` on the bucket.
- `uv` (already required) — the sync runs via `uv run --no-project --with
  'google-cloud-storage>=2,<4'`, so no system Cloud SDK is needed.

**Deploy step for the co-core adoption (one-time).** The unit gained an
`ExecStartPre`; reinstall it before the next restart or the parity test
(`tests/deploy/test_installed_unit_matches_repo.py`) flags drift:

```bash
sudo cp deploy/archiver.service /etc/systemd/system/ && sudo systemctl daemon-reload
# then, when safe: sudo systemctl restart archiver
```

(CI is keyless instead — the `lint`/`test` jobs authenticate via Workload
Identity Federation; see `.github/workflows/ci.yml`.)

## Redis change bus (archiver#109)

Archiver **operates** the local `redis-server` as the `info.changes` change-bus
producer + cluster control-plane. Ownership was previously un-assigned (stock
distro unit, nobody's app); #109 closes that gap before Phase 3 (Replicator)
makes the bus load-bearing. Design of record:
`docs/plans/2026-07-29-redis-bus-ownership-design.md`.

The connection string (`ARCHIVER_REDIS_URL`) is the only switch — local now,
`rediss://` managed later with no code change. Only the artifacts below are
local-broker-specific; a managed migration deletes them and swaps the env var.

**`redis-server.dropin.conf`** — tracked drop-in that tunes the stock broker
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

To change the cap later, prefer applying it live — no restart, no dropped client
connections — and let the unit supply it from the next restart onward:

```bash
# edit ExecStart in deploy/redis-server.dropin.conf, then:
sudo cp deploy/redis-server.dropin.conf \
    /etc/systemd/system/redis-server.service.d/archiver.conf
sudo systemctl daemon-reload
redis-cli CONFIG SET maxmemory <value from ExecStart>   # applies now, no restart
```

Pass the value **exactly as `ExecStart` spells it** — `CONFIG SET` accepts the
same unit suffixes, so there is no byte conversion to get wrong and no second
copy of the number to drift.

`CONFIG SET` is not persisted (no `CONFIG REWRITE`), which is what keeps the unit
authoritative. The flip side is that it can drift the *running* broker from the
tracked file in either direction, and the file-parity test cannot see that — so
`scripts/check_redis_floor.sh` reads the live value at every `archiver.service`
start and warns when it is `0`.

**`maxmemory` is load-bearing, not decoration (archiver#128).** `noeviction`
with the default `maxmemory 0` is *inert*: there is no ceiling to refuse writes
at, so an untrimmed stream never produces the retryable write errors the
"a stream broker must never evict" reasoning assumes — it grows until the kernel
OOM-killer takes `redis-server`, costing the whole broker plus an AOF-replay
restart. The explicit cap converts that into bounded, instance-wide `OOM command
not allowed` errors. Those are classified **transient** by the outbox publisher
(`_TRANSIENT_PUBLISH_ERRORS` in `src/core/changes/publisher.py`), so a memory
incident caused by *any* stream on this shared broker stalls `info.changes`
publishing without dead-lettering valid events. **The cap and that classification
are one decision — do not change either alone.** Sizing rationale is in the
drop-in's header comment.

**The cap changes the failure mode for every producer on this broker, not just
ours.** Once the cap is reached, `XADD` is refused instance-wide — Watcher's
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
what is running today:

| Stream | Producer → consumer | Kind | Consumer group | Health primitive | DLQ | Producer durability under OOM |
|---|---|---|---|---|---|---|
| `info.changes` | Archiver → Replicator *(target)* | event | none *yet* — Replicator adds one | ⚠️ **none implemented.** Outbox depth is the intended signal but has no surface — manual SQL against `information.changes_outbox` only. Group lag once consumed. See #130 | `info.changes.dlq` *(target)* | **retries indefinitely** — transactional outbox, OOM classified transient |
| `content.fetch` | Watcher → Replicator | command | `replicator.fetch` (exactly one — competing consumers) | `XPENDING` / group lag | `content.fetch.dlq` | **unasserted** — CannObserv/watcher#245 |
| `content.blobs` | Replicator → Watcher | fact | one per consuming service | group lag per group | `content.blobs.dlq` | **unasserted** — CannObserv/replicator#19 |
| `content.revisions` | Watcher → **Archiver** *(producer target: CannObserv/watcher#253)* | fact | `archiver.revisions` (one per consuming service) | `XPENDING` / group lag — **the first group Archiver owns**; threshold still to be set, see #130 | `content.revisions.dlq` — written by the ingest consumer's quarantine path | **unasserted** — CannObserv/watcher#253 |
| `content.fetch-policy` | Watcher → Replicator workers *(target; no producer or consumer exists yet)* | config/state, broadcast, last-write-wins per host key | **none, permanently — by design** | **last-entry age via `XINFO STREAM`** | **none applies** | **self-correcting** — full set is republished on a timer |
| `info.registry` | **Archiver** → Watcher *(consumer live — watcher#254)* | config/state, broadcast, last-write-wins per `info_item_id`, `generation`-ordered | **none, permanently — by design** (every consumer needs every message; a group accumulates a PEL nothing drains) | **last-entry age via `XINFO STREAM`** — on a non-empty corpus the snapshot guarantees ≥1 entry/hour, so an age over ~2× the snapshot interval means the producer is down; an empty or never-announced registry publishes nothing, so the alarm needs a corpus-size guard. See #147 | **none applies** — a state message has nothing to close; quarantine is terminal and the next full set supersedes | **split by path**: deltas ride the transactional outbox and retry indefinitely (OOM transient); snapshots have **no retry** — one lost to an outage is corrected by the next period, not a re-attempt |
| `info.watch-status` | Watcher → **Archiver** *(consumer live — archiver#151; producer target: CannObserv/watcher#264)* | config/state, broadcast, last-write-wins per `info_item_id` | **none, permanently — by design** — Archiver tails groupless (`AsyncBusTailReader`), resuming from its own `bus_tail_cursors` row rather than a full `0-0` replay | consumer-side: staleness of the `watch_status` cache vs the producer's republish period; broker-side last-entry age once #264 publishes | **none, matching `content.fetch-policy`** — **two** skip paths, both durable (the skip advances the persisted cursor) and both logged at ERROR: a frame that will not *decode*, and a decoded message the registry can never *write* (a value outside a column's domain, a constraint violation). With no DLQ and a cursor that only advances on success, retrying either forever would stall the stream silently; the periodic republish is what supersedes a skip. Everything else (broker or DB down) rewinds and retries rather than skipping | **self-correcting** — coalesced level signals, full republish on a timer (watcher#264) |

**`content.revisions` is Archiver's first consumer role** — every other row is a
stream it operates for someone else. Two operational consequences: the
`archiver.revisions` group is the first thing on this broker whose *lag* is
Archiver's own problem (a stalled consumer means revisions stop being recorded,
silently, while the stream keeps growing), and `content.revisions.dlq` is the
first DLQ this service writes rather than merely provisions. Group membership is
gated on `ARCHIVER_BUS_CONSUMER=1`, set only in `deploy/archiver.service` — a
second process in the group silently takes half the revisions.

⚠️ The `info.changes` health row is the one to fix first. It names a primitive
that does not exist: nothing exposes outbox depth — no route, no dashboard panel,
no metric — so an operator reading this table would conclude the stream is
covered when the only way to observe it is a hand-written query. Recorded here
rather than quietly omitted, for the same reason the `content.fetch-policy` row
exists at all.

**`content.fetch-policy` is monitoring-blind to consumer-group lag, and always
will be (archiver#128 / cannobserv#285).** Every worker needs every message, so
the consumer reads groupless (`co_core_aio.bus.AsyncBusTailReader`, in-memory
cursor, replayed from `0-0` at boot) — a group here would accumulate a PEL
nothing drains. Consequence: **`XPENDING` reports nothing for this stream whether
or not a single consumer is alive.** Any dashboard or alert that reads "no
pending entries" as healthy will read this stream as healthy while it is dead.
Use last-entry age instead — it at least catches a producer that stopped
republishing.

Note the *permanently* in that row. `info.changes` is groupless today too, but
only because its consumer isn't built; it gains a group and becomes
lag-monitorable, exactly as `content.revisions` just did.
`content.fetch-policy` does not.

For the same reason it has **no DLQ**. `dead_letter()` is a method on
`AsyncBusConsumer` — it copies the frame to `dlq_name(topic)` and acks the
original. A groupless tail reader has no ack and no delivery accounting, so
nothing can write `content.fetch-policy.dlq` and nothing would trigger one.

**Retention is the producer's, not ours, for this stream.** A stream whose
producer republishes its full set on a timer grows without bound unless trimmed;
`BusPublish.maxlen` (co-core ≥0.7.7) rides the trim on each publish, and the knob
sits with Watcher (CannObserv/watcher#245) because the consumer's
replay-from-`0-0` boot depends on the retention policy — it is a contract
property, not broker tuning. Our exposure is the shared-instance blast radius,
which `maxmemory` above bounds. A broker-side `XLEN` guard is deferred until
Watcher's republish interval and the real host count exist; it belongs in a
periodic timer (following `watcher-live-drift`), not in `check_redis_floor.sh` —
an `ExecStartPre` fires once at process start, and unbounded growth is by
definition an after-start condition.

**`archiver.service` ordering + floor.** The unit declares
`Wants=redis-server.service` + `After=redis-server.service` (soft ordering — the
outbox tolerates broker downtime, so no `Requires=`/`BindsTo=`) and an
`ExecStartPre` that runs `scripts/check_redis_floor.sh` to assert the server is
≥7.0 (the consumer path's `XAUTOCLAIM` requirement) when `ARCHIVER_REDIS_URL` is
set. That script also reads the **live** `maxmemory` and warns when it is `0` —
the only check that sees the running value rather than the tracked file. It warns
rather than blocks: an uncapped broker doesn't break the producer, and refusing
to start the API over a broker tuning value would turn tuning drift into an
outage. Blocking is reserved for the version floor, where the consumer path is
genuinely broken. The probes are `timeout`-bounded (`ARCHIVER_REDIS_FLOOR_TIMEOUT`, default 5s)
so it can never hang startup, and warns when `redis-cli` lacks TLS support for a
`rediss://` URL; it soft-skips (never blocks) on a dormant or unreachable broker
and blocks only a genuinely-<7.0 reachable one. Reinstall the unit after any edit
(see the parity note under the wheelhouse section) —
`tests/deploy/test_installed_unit_matches_repo.py` flags drift.

**`info.registry` retention is different in kind** (archiver#141): consumers
boot by replaying from `0-0`, so the floor is "at least one full snapshot plus
the deltas since" — a consumer contract, not operator housekeeping. It is
therefore **excluded from the periodic `XTRIM` loop** and capped on every
publish via `BusPublish.maxlen` instead (`ARCHIVER_REGISTRY_STREAM_MAXLEN`,
default 50k, sized from key count × sets retained — never from the
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

## watcher-live-drift (Layer C, archiver#70)

The committed `clients/watcher-python/watcher-openapi.json` snapshot can go stale
relative to the live Watcher service — the #66 failure mode the hermetic CI
`client-drift` gate cannot see. This timer runs **on the VM** (so it reaches
Watcher at `http://localhost:8000` — no public URL, no hairpin-NAT, no
runner↔Watcher uptime coupling) and turns real upstream drift into a reviewable
PR instead of a prod incident.

- `scripts/check_watcher_live_drift.py` — pure detector (stdlib): fetch live
  `/openapi.json`, canonicalize as `regen.sh` does, byte-compare to the snapshot.
  Exit `0` no drift · `1` drift · `2` internal error (e.g. missing snapshot) ·
  `3` unreachable (skip).
- `scripts/watcher_live_drift_pr.sh` — remediation: on drift, regen snapshot +
  tree via `regen.sh` in an isolated worktree off `origin/main`, then open a PR.
  Branch is keyed on the live spec SHA, so re-runs while a PR is open are no-ops.
- `scripts/ff_deploy_clone.sh` — run by the service's `ExecStartPre` (not the
  wrapper, so the long-running wrapper never mutates the clone it executes from).
  Best-effort **fast-forwards the deploy clone** to `origin/main` so the detector
  compares against `origin/main`'s snapshot, not a stale tree. It only
  fast-forwards a **clean checkout of `main`**; a dirty, detached, or
  locally-ahead/diverged clone is left untouched and just logged (the wrapper's
  no-op guard still backstops a stale tree). The running `archiver.service` is
  unaffected until its next restart.
  - **Currency caveat:** the fast-forward only refreshes the tree when `main`
    can fast-forward to `origin/main`. If the clone's `main` has *diverged*
    (local commits origin lacks **and** origin commits the clone lacks), the
    fast-forward is skipped and the detector reads a tree missing origin's
    latest snapshot — harmless (no bad PR; the regen-off-`origin/main` no-op
    guard catches it) but stale until the clone reconverges. (A clone merely
    *ahead* of `origin/main` is not stale — it already contains origin's
    snapshot — so that case is a safe no-op, not a currency loss.)

### Install (one-time, needs sudo)

```bash
sudo cp deploy/watcher-live-drift.service deploy/watcher-live-drift.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now watcher-live-drift.timer
```

### Operate

```bash
systemctl list-timers watcher-live-drift.timer     # next fire time
sudo systemctl start watcher-live-drift.service     # run once now
journalctl -u watcher-live-drift.service -f         # logs
bash scripts/watcher_live_drift_pr.sh --dry-run     # detect + prepare commit, no push/PR
```

### Requirements

- Live Watcher reachable at `http://localhost:8000` (the detector and `regen.sh`
  both fetch it). A down Watcher just makes the run a no-op (exit 0).
- `GH_TOKEN` in `/etc/archiver/.env` (for `gh pr create`).
- **Non-interactive `origin` auth (fetch + push).** Both the `git fetch`
  (`ExecStartPre` fast-forward and the wrapper) and the remediation `git push`
  run under systemd as `User=exedev` in a non-login shell, so they cannot prompt.
  The SSH deploy key must be usable without a passphrase/agent, and `HOME`
  (`/home/exedev`) plus `~/.ssh/config` must resolve the `origin` remote's host
  (e.g. the `github-archiver` alias). Verify once after install with
  `sudo systemctl start watcher-live-drift.service` and check the journal — a
  silent push failure here is the one path the `--dry-run` smoke test can't cover.
- `/openapi.json` is public, so no `WATCHER_API_KEY` is needed for the fetch.
