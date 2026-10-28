# archiver — Monitoring: the drift check and liveness

The two co-status checks that watch production from this repo: the drift check (is live
behind `main` in code that runs?) and the service's liveness heartbeat. Split from
[DEPLOYMENT.md](DEPLOYMENT.md), which keeps releases, the service user and the timer roster; the
units are [deploy/README.md](../deploy/README.md), and the nightly backup's check-in is
[BACKUP.md](BACKUP.md).

## The drift check (archiver#338)

`archiver-drift.timer` alerts co-status when live lags `main` in code that runs for over
8 h (#338); never run it with the real key or monitor id outside its unit, bar the
`--test-alert` in § Turning it on (once) below.

**A merge is not a deploy.** Since releases, nothing that runs changes until
`scripts/deploy.sh`, and nothing else reports a merge that was never deployed.
`archiver-drift.timer` runs `python -m src.core.drift` hourly: it asks GitHub how far
live's `REVISION` is behind `main`, and checks in to Status's **`co-archiver-drift`**
monitor (`01M4KMDDN3XWJR0GCECTAYMVTV`, tenant `co-archiver`, CannObserv/status#32).
Ported from processor#35, itself from status#12; the rules are in `src/core/drift.py`.

| Verdict | When | Status sees |
|---|---|---|
| `ok` | live is `main`; or behind only in paths that never run; or behind in code for 8 h or less | `ok` |
| `lag` | behind in code for more than 8 h since the push that brought it | `alert`, naming `main`'s CI result and the remedy |
| `off_main` | live is not an ancestor of `main` (or GitHub doesn't know it) | `alert` at once |
| `unstamped` | the release has no `REVISION` | `alert` at once |
| `test` | `--test-alert`, by hand | `alert` |
| silent | GitHub can't answer (rate limit, 5xx, timeout) | **nothing**: never a false `ok`; two silent runs go `missing` |

**What runs** is an allowlist, `RUNTIME_DIRS`/`RUNTIME_FILES` in `src/core/drift.py`:
`src/`, `alembic/`, `alembic.ini`, `deploy/`, `scripts/deploy.sh`,
`scripts/check_redis_floor.sh`, `pyproject.toml`, `uv.lock`. A docs, tests, skills or
SDK lag is `ok` however old. `tests/core/test_drift.py` holds every path and module a unit
executes to that list, so a new `ExecStart` cannot slip out of it.

**Each alert carries `metadata.fault`** = its kind (status#28): a run of `lag` alerts is
one fault, reported when it opens, reminded daily (`renotify_seconds` 86400) and *cleared*
by the next `ok`; a change of kind reports at once. The monitor is 3600 s / grace 5400 s:
one missed run is absorbed, two alarm. Unauthenticated GitHub, 60 requests an hour shared
with `deploy.sh`'s CI gate; a run costs 1-2, at most 10.

**The unit** has no `EnvironmentFile=` (`/etc/archiver/.env` holds credentials it has no
use for), no database, no production opt-in, and is sandboxed (`ProtectSystem=strict`,
`ProtectHome=yes`, hence `.venv/bin/python`, not `uv run`, which wants `$HOME`). The key is
`/etc/archiver/status-checkin.key` (`root:root 0600`), handed over as the
`status-checkin-key` credential; installed 2026-10-10. The tailnet path
`tag:archiver → tag:status:9000` is in.

**Never run it with the real key or monitor id outside the unit.** A disabled monitor
still reports every alert to both channels, and a stray `ok` resets the dead-man clock, so
it can hide real silence (status#32). Tests stub GitHub and Status (respx);
`tests/conftest.py` scrubs `ARCHIVER_STATUS_URL` and `CO_ARCHIVER_DRIFT_MONITOR_ID`.

### Turning it on (once)

`scripts/deploy.sh` installs both units and never enables a new one (D12). After the
deploy that ships #338:

```bash
sudo systemctl enable --now archiver-drift.timer   # first run fires at once
journalctl -u archiver-drift -n 5 -o cat            # "drift check", kind ok, checkin 202
```

Then **whoever ran the deploy** posts that first `ok` (`kind`, `live`, `main`) on
status#32, and status-agent enables the monitor (it was created disabled) once it sees the
check-in on its side. Then prove the channels with one test alert, as a
transient unit holding the same credential (checked 2026-10-10: systemd hands it to any
`User=`), and have the operator confirm email and Slack:

```bash
sudo systemd-run --quiet --pipe --wait \
  -p LoadCredential=status-checkin-key:/etc/archiver/status-checkin.key \
  -p Environment=CO_ARCHIVER_DRIFT_MONITOR_ID=01M4KMDDN3XWJR0GCECTAYMVTV \
  -p WorkingDirectory=/srv/archiver/live -p User=archiver \
  /srv/archiver/live/.venv/bin/python -m src.core.drift --test-alert
sudo systemctl start archiver-drift.service   # its ok clears the test fault: "has cleared"
```

### When it alerts

| Kind | Remedy |
|---|---|
| `lag` | `scripts/deploy.sh` from an up-to-date `main`. If the body says CI isn't `success`, fix `main` first: the gate refuses it |
| `off_main` | live runs a commit `main` doesn't contain: a branch, or history rewritten since. Deploy `main` |
| `unstamped` | the release is broken; redeploy |
| `missing` | the check isn't reporting: `systemctl status archiver-drift.timer`, `journalctl -u archiver-drift`; the tailnet path (`curl http://status:9000/health`), the key file, or GitHub silent two runs running |

**After a rollback past #338** the timer keeps running a release with no
`src.core.drift`, fails, and the monitor goes `missing`. `deploy.sh` names any installed
`archiver*` unit the release lacks; it never removes one. Stop it with `sudo systemctl
disable --now archiver-drift.timer` if that is the intent.

## Liveness (archiver#297)

`archiver.service` checks in `ok` to Status's **`co-archiver-live`** monitor
(`01M52WN2A5SVMK2B4ZZ4RD2TDD`, tenant `co-archiver`, CannObserv/status#47; 300 s, grace 900 s, renotify daily) every 5 min,
**only while its bus loops are making progress**. It never sends `alert`: silence is the
page. Ported from processor#39. The rules are in `src/core/liveness.py`.

**The gate.** Every expected continuous loop stamped progress within 120 s and has not
exited. Every expected periodic task is still running. A loop whose init failed, or that
has not finished one iteration yet, counts as silence. The first tick comes one interval
(5 min) after start, never at once. That way a crash loop too slow for `StartLimitBurst`
still goes silent instead of sending `ok` on every start.

| Loop | Expected when | Stamps |
|---|---|---|
| outbox publisher | always, while liveness is on | each publish attempt, and each drain that **returns**. Never while the database is down: `/health` is DB-free, so this is how a Postgres outage pages |
| `content.revisions` + `content.artifacts` consumers | `ARCHIVER_BUS_CONSUMER` | every iteration, broker backoff included, and per reclaimed message |
| `info.watch-status` tail | `ARCHIVER_REDIS_URL` | every iteration, backoff included |
| registry snapshot | `ARCHIVER_REDIS_URL` | nothing: alive while not `done()` |
| replication reaper | `ARCHIVER_BUS_CONSUMER` | nothing: alive while not `done()` |

So a broker outage still counts as alive (broker has its own monitoring), and so does an
idle stream. What goes silent, and pages:
- a dead process;
- a crash loop. `StartLimitIntervalSec=300` and `StartLimitBurst=5` in `[Unit]` take it to `failed` in about 30 s. systemd's default, 5 starts in 10 s, can never be spent at `RestartSec=5`, so before this it restarted forever;
- a wedged event loop;
- a stalled or exited bus loop;
- a database outage.

**No `OnFailure=`.** `deploy.sh` runs `reset-failed` before every restart, so a spent
burst never blocks a deploy or a switch-back. A planned stop ends `inactive`, not
`failed`: uvicorn dies by the SIGTERM it re-raises, which systemd counts as clean.
`tests/deploy/test_planned_stop.py` pins this. The 2026-09-30 `failed` came from `uv run`,
which turned that same SIGTERM into exit code 143.

**The unit** carries `Environment=CO_ARCHIVER_LIVE_MONITOR_ID=…`. That line is never in an
env file: a hand-run server would check in for production. The key is the tenant's,
shared with drift and backup, handed over as the `status-checkin-key` credential, with
the empty `SetCredential=` fallback. Each check-in runs in a daemon thread, bounded at
15 s, one attempt per tick, so a hung Status never delays a publish or an ack. A stop never
joins a check-in in flight (#406): its reading predates the stop, and a join could hold
the stop 15 s.
Startup says which state it is in:

| Journal | Meaning |
|---|---|
| `liveness: on <id>` | checking in. The first `liveness check-in` (`checkin` 202) comes 5 min after start, then one after each failure |
| `liveness: off` | no monitor id: a dev server, a test, a hand run |
| `liveness: off: CO_ARCHIVER_LIVE_MONITOR_ID is not a ULID` (ERROR) | the unit's id is wrong (a placeholder or a bad paste). The service runs **unmonitored**. Fix the `Environment=` line in `deploy/archiver.service`, then merge and deploy |
| `liveness: off: missing the status-checkin-key credential` (ERROR) | the key file is gone or empty. The service runs **unmonitored**. Reinstall `/etc/archiver/status-checkin.key` (root 0600) and restart |
| `bus loops not progressing; not checking in` (WARNING, each tick) | the gate is shut. `reasons` names each loop (`not started`, `exited`, `no progress yet` before its first iteration finishes, `stale N s`) |
| `liveness check-in failed` (WARNING) | Status refused or timed out. The grace absorbs one |

### When it goes `missing`

Read `journalctl -u archiver -o cat | grep liveness` first:
- **Repeated `liveness: on` with no `liveness check-in` between them:** it is crash-looping, or dying within 5 min of each start. Every start logs `on`, and the first check-in waits one interval. Run `systemctl show archiver -p NRestarts -p Result` and read the traceback before each `on`.
- **No `liveness` lines at all since the last stop:** the process is down. Usually that means `failed` after `StartLimitBurst` (`systemctl status archiver`). After fixing the cause, `sudo systemctl reset-failed archiver && sudo systemctl start archiver`.
- **`bus loops not progressing`:** its `reasons` name the loop. `stale` on the publisher alone is most likely the database (`systemctl status postgresql`). `exited` or `not started` means a bus task died: look for `Bus task exited` and `Failed to initialise` just before it. The remedy is a restart once the cause is fixed.
- **`check-in failed` every tick:** Status is unreachable (`curl http://status:9000/health`, the tailnet path) or refuses the key.

**Planned stops.** A stop longer than interval plus grace, about 20 min, pages. **Pause the
monitor first.** Ask Status's operator to `PATCH` `co-archiver-live` to `enabled: false`;
check-ins still land while it is paused. Re-enable it after the restart. A deploy never
needs this. Its worst silence is about 900 s: up to 300 s since the last `ok`, a stop of 90 s
or less, the 120 s verify, a switch-back restart, and then the 300 s first tick. The
monitor allows 1200 s (interval plus grace).
