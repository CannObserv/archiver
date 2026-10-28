# archiver — Deployment & Configuration

Releases and `scripts/deploy.sh`, the drift check, the service user, reading
production, wheelhouse reproducibility, Dependabot and the timers. The environment
variable reference and the dev server's internals are [ENVIRONMENT.md](ENVIRONMENT.md).
The host's place on the tailnet - node identity, the ACL, why there is no
tailnet-only bind - is [reference/tailscale.md](reference/tailscale.md).

## Releases (archiver#330)

**Production runs a release, never a checkout.** Design and reasons:
[plans/2026-10-09-330-deploy-releases-design.md](plans/2026-10-09-330-deploy-releases-design.md)
(D1-D12), adopted from CannObserv/status's R1-R13.

```
/srv/archiver/                 root:root 0755
  releases/<build>/            git archive of one origin/main commit + its own .venv;
                               root's, read-only; REVISION (12-char SHA) written last
  live -> releases/<build>     archiver.service, archiver-bus-health, archiver-pm-org-refresh,
                               archiver-drift, archiver-temporal-boundary
```

- **Nothing done in `/home/exedev/archiver` reaches a unit**: branch switches, uncommitted
  edits, `uv sync`, hook commits. Units run the release venv's own entry points
  (`.venv/bin/uvicorn`, `.venv/bin/python -m`) from `/srv/archiver/live`, never `uv run`,
  read `/etc/archiver/.env` only, and stamp nothing: `/health`'s `build_id` is the
  release's `REVISION`. The drift check reads no env file at all (§ The drift check).
- **Root owns the root, `releases/` and each finished release** (status#14): changing what a
  unit runs takes `sudo`, which journals the command.
- **The units run as `archiver`, not `exedev`** (#339): reading their secrets, or signalling
  or tracing their processes, takes `sudo` too (§ The service user).
- **The venv is copied** (`--link-mode copy`), not hardlinked to `~/.cache/uv`, on
  `/usr/bin/python3.12`; the private wheels are fetched into the release and removed once
  the venv is built (D10).

### `scripts/deploy.sh`

Run as `exedev`, from the checkout, after the PR merges. It reads `/etc/archiver/.env`
through `sudo` (root's alone, #339), `dev.env` and `deploy.env` without. It fetches `origin` itself, then
**refuses unless it is itself byte-identical to `origin/main:scripts/deploy.sh`** (CR 10): the
deploy logic is reviewed code like what it deploys, so a branch or an uncommitted edit to the
script cannot decide how production deploys. `git switch main && git pull --ff-only` first.

```bash
scripts/deploy.sh                       # origin/main, once its CI passed
scripts/deploy.sh <build>               # an earlier build since the cutover, green CI: a rollback
scripts/deploy.sh --skip-ci [<build>]   # without asking CI: an emergency, logged
journalctl -t archiver-deploy -n 20     # "CI passed for <build>", "live -> <build> (was ...)"
```

**A commit from before releases is refused**, before CI is asked (CR 14): one whose
`deploy/*.service` runs anywhere but `/srv/archiver/live`, or that has no `src/core/build.py`.
Its units would put production on the checkout, and its `/health` cannot name a release, so
verification would always fail after the checkout had served. So no rollback reaches past the
cutover: for older code, revert it on `main` and deploy that.

**So is a commit whose units name a `User=` or `Group=` this host lacks** (#339), read from
the commit itself, also before CI is asked or anything is built, a reused release too. The
refusal prints the `useradd` it needs.

In order, each step refusing before anything switches:

1. **CI gate** (D6): the newest `push` run of `ci.yml` on `main` for exactly that commit,
   every job `success`, `lint test client-drift changelog` among them. Pending waits up to
   10 min; a commit with no run (not the tip of its push) is refused. Unauthenticated: the
   repo is public.
2. **Build** `releases/<build>`, or reuse a finished one whose venv imports: `git archive`;
   the release's `scripts/sync_wheelhouse.py` with `GOOGLE_APPLICATION_CREDENTIALS` from
   `/etc/archiver/deploy.env`; `uv sync --locked --no-dev`; one Alembic head; **every unit's
   `ExecStart` module imports** (D11, the 2026-10-08 failure); read-only; root's; `REVISION`.
   The release `live` runs is never rebuilt in place.
3. **Rehearse** (D2): `python -m src.core.schema_state`, then `alembic upgrade head`, against
   `ARCHIVER_DEV_DATABASE_URL` from `/etc/archiver/dev.env`. `ahead` there is expected in a
   rollback (the newer build's rehearsal migrated it). Otherwise it is a branch migration from
   a worktree's `dev_server.sh` that never merged: downgrade it, or the rehearsal rehearses
   nothing. **A rehearsal that cannot read `archiver_dev` at all (unreachable,
   refused by `db_safety`, crashed) refuses the production deploy**, exit 1, nothing switched:
   bring `archiver_dev` back or fix `dev.env`. A production fix does not wait on it through
   a flag, by design: the rehearsal is what proves the migration first.
4. **Migrate** `archiver` the same way, with `ARCHIVER_ALLOW_PRODUCTION_DB=1`; skipped when
   the schema is `ahead` (a rollback). Migrations are **expand-only** (D3): the old release
   runs on the new schema between this step and the switch, and after any rollback. A
   migration waits at most 5 s for any lock (`lock_timeout`, #348), then fails and nothing
   switches: an open reader stalls the API's queries (queued behind the waiting migration)
   for at most 5 s, not until the reader finishes. After each database's
   migration, rehearsal and live, `python -m src.core.reader_grants` re-applies the read
   role's grants ([§ Reading production](#reading-production-archiver348)); a failure
   there switches nothing either. A rollback leaves the newer build's grants in place: the
   older set would reopen anything a later build withheld.
5. **Switch** `live` (rename(2)), then **install the units that differ** from the release,
   one `daemon-reload`, `try-restart` for a changed timer. A new unit is installed, never
   enabled: the deploy prints `enable --now` for a unit with `[Install]`; a timer's
   service is named with its timer instead (#345).
6. **Restart** `archiver`, wait out a running `archiver-bus-health` pass, force one, and
   **verify**: `/health` `build_id` is `<build>` and `schema_state` can serve, within
   `ARCHIVER_DEPLOY_VERIFY_SECONDS` (120). `archiver-pm-org-refresh` is never forced (D4).
7. **On failure**, switch back - link and units - `reset-failed`, restart, prove the old
   build. Exit 1 when it answers, 4 when it does not. The migration stays.

Then host configs under `deploy/` are compared with their installed copies (a difference is a
note, never an install), and releases beyond the 5 newest are pruned, never the linked one.

| Variable | Default | What |
|---|---|---|
| `ARCHIVER_DEPLOY_ROOT` | `/srv/archiver` | releases and the `live` link |
| `ARCHIVER_DEPLOY_ENV_DIR` | `/etc/archiver` | `.env` (units), `dev.env` (rehearsal), `deploy.env` (wheel fetch) |
| `ARCHIVER_DEPLOY_ETC` | `/etc` | units in `systemd/system/`; host configs compared there |
| `ARCHIVER_DEPLOY_KEEP` | `5` | the newest releases kept (by last deploy); the linked one is never pruned |
| `ARCHIVER_DEPLOY_VERIFY_SECONDS` | `120` | `/health` and the schema must answer within it |
| `ARCHIVER_DEPLOY_PROBE_WAIT_SECONDS` | `90` | how long to wait out a running bus-health pass |
| `ARCHIVER_DEPLOY_CI_WAIT_SECONDS` / `_POLL_SECONDS` | `600` / `30` | the CI gate's wait |
| `ARCHIVER_DEPLOY_PYTHON` | `/usr/bin/python3.12` | the interpreter each venv is built on |

**Hand-run alembic against production is refused** unless `ARCHIVER_ALLOW_PRODUCTION_DB=1`
(D9); against dev, unset `ARCHIVER_DATABASE_URL` and set `DATABASE_URL` to the dev URL.
**A hand edit of an installed unit lasts until the next deploy**, which replaces it and says
so; put the fix in `deploy/`. `tests/deploy/` compares installed units with the live release.

### First deploy (the cutover, once per VM)

Operator-present. The first deploy has no release to switch back to: on a failed verify it
puts back the checkout-backed units it replaced, removes `live` and restarts on them (exit 1
when archiver answers, 4 when not).

```bash
sudo install -d -m 755 -o root -g root /srv/archiver
# 0640 before anything is written: tee keeps an existing file's mode, and a file
# it creates would hold the dev password world-readable until a later chmod (CR 3).
for f in dev.env deploy.env; do sudo install -m 640 -o root -g exedev /dev/null "/etc/archiver/$f"; done
# The rehearsal URL, copied from the repo .env: never typed, so never in history.
grep '^ARCHIVER_DEV_DATABASE_URL=' /home/exedev/archiver/.env | sudo tee /etc/archiver/dev.env >/dev/null
printf 'GOOGLE_APPLICATION_CREDENTIALS=/etc/archiver/co-pypi-reader.json\n' \
    | sudo tee /etc/archiver/deploy.env >/dev/null
cd /home/exedev/archiver && git switch main && git pull --ff-only
scripts/deploy.sh
curl -s http://127.0.0.1:8000/health; readlink /srv/archiver/live
```

Then prove the point: `git switch` the checkout to any branch, `sudo systemctl restart
archiver` and start both timers' services; `build_id` is unchanged. Done on this VM
2026-10-09 (`e68f1389771b`). `.skills/worktree_venv` stays `none`: the checkout's `.venv` is
no longer production's, but it holds editable installs bound to the checkout's path, which a
linked worktree would re-point (the `using-git-worktrees` override, CR 20).

**`GOOGLE_APPLICATION_CREDENTIALS` belongs in `/etc/archiver/deploy.env` alone** (#341). No
unit needs it: `deploy.sh` reads it from there, and so do the checkout's wheelhouse recipes
(CLAUDE.md § Environment & Tooling, the `using-git-worktrees` override). Until #341 it was in
`/etc/archiver/.env` too, which put it in every unit's environment. On a VM that still has it
there, delete the line, then restart: `sudo sed -i '/^GOOGLE_APPLICATION_CREDENTIALS=/d'
/etc/archiver/.env`, then `scripts/deploy.sh` or `sudo systemctl restart archiver`.

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

## The nightly backup (archiver#233)

`archiver-backup.timer` dumps `archiver` at 03:17 UTC to `gs://co-gcs-archiver-backup`,
create-only, as its own `pg_read_all_data` user `archiver_backup`, and checks in to
co-status's `co-archiver-backup`. Provisioning, first run, the create-only probe, the
restore runbook and the alert remedies: [BACKUP.md](BACKUP.md).

## The service user (archiver#339)

**The units run as `archiver`**, a system user with no login, no home and no `sudo`, not
as `exedev`, the account agents and humans use. Processor's shape (processor#2). Nothing in
a release is `archiver`'s: `deploy.sh` still builds as `exedev` and hands each release to
root. What `exedev` can no longer do without `sudo`:

| What | How it is closed |
|---|---|
| Read the production secrets | `/etc/archiver/.env` is `root:root 0600`. systemd reads an `EnvironmentFile=` before it drops to `User=`, so not even `archiver` can read the file; `deploy.sh` reads it through `sudo` |
| Reach the production database | role `archiver` connects only to `archiver`, with a password only that file holds. Agents get `archiver_agent`, which owns `archiver_dev` and `archiver_test` and has no `CONNECT` on `archiver`; they read production as role `exedev` ([§ Reading production](#reading-production-archiver348)) |
| Signal or trace the service | another uid |

The units can't read `~exedev` either (`ProtectHome=yes`; the repo `.env` holds the PATs).
`exedev` keeps `dev.env`, `deploy.env` and `co-pypi-reader.json` (`root:exedev 0640`): the
deploy's rehearsal and wheel fetch run as `exedev`. `status-checkin.key` was already
`root:root 0600`. `exedev` still has passwordless `sudo`, so this is a boundary that
journals, not one that cannot be crossed.

**The guards stop depending on the production URL.** An agent shell no longer holds
`ARCHIVER_DATABASE_URL` or `ARCHIVER_REDIS_URL`, so comparing against them would always
pass. The rules that still hold are positive, as `src/core/db_safety.py`'s always was:
`tests/conftest.py` refuses a `TEST_DATABASE_URL` whose name doesn't end in `_test`, and
`scripts/dev_server.sh` refuses an `ARCHIVER_DEV_REDIS_URL` that isn't loopback or a socket.
The recipes source `/etc/archiver/.env` only when it is readable (`[ -r … ]`).

**No `uv` at run time.** `uv run`, even `--no-sync`, wants a writable cache under `$HOME`,
and `archiver` has none, so every unit runs the release venv's own `uvicorn` or `python`.
Checked 2026-10-10 as a transient `DynamicUser=` with the units' sandbox: every entry
module imports, and `/home/exedev` is out of sight.

### Cutover (once per VM)

Seven operator-present steps after the PR merges, each one undone before the next:
[plans/2026-10-10-339-service-user-cutover.md](plans/2026-10-10-339-service-user-cutover.md).
The user, a deploy, the file closed, a rollback proved, the agents' role, production
closed to everyone but its owner, then `archiver`'s password rotated.

## Reading production (archiver#348)

Agents read production with `psql -d archiver`: role `exedev`, peer-authenticated over the
Unix socket, no password anywhere. #339 closed write access and took read access with it;
this restores the reads only. Decision record and the once-per-VM runbook:
[plans/2026-10-11-348-prod-read-access.md](plans/2026-10-11-348-prod-read-access.md).

| Property | How it holds |
|---|---|
| Read-only | privileges: `SELECT` on `information` and nothing else. `default_transaction_read_only` is only a default |
| No secret | no password, so TCP (`scram-sha-256`) is closed; the socket's `peer` line admits OS user `exedev` |
| Personal data out | `app_users` and `api_keys` read by column allowlist: no `email`, `external_id` or `key_hash` (`src/core/reader_grants.py`). A column added there starts withheld |
| New tables readable | default privileges, plus `deploy.sh` re-applying the grants after every migration |
| Every query on record | `log_statement = 'all'` for the role, in `/var/log/postgresql/postgresql-16-main.log` (readable by `adm`), not journald |
| Bounded | `CONNECTION LIMIT 3`; `statement_timeout` 30 s and `idle_in_transaction_session_timeout` 60 s, which a session *can* override, so don't |
| Revocable | `ALTER ROLE exedev NOLOGIN` |

**Don't hold a transaction open.** A `SELECT` holds `AccessShareLock` until its transaction
ends. A deploy's migration waits at most 5 s for it, then fails (§ `scripts/deploy.sh` step
4), so a forgotten `BEGIN` in a `psql` session blocks deploys. Use autocommit, the default.

**Python never gets a production URL.** `db_safety` refuses `archiver` without
`ARCHIVER_ALLOW_PRODUCTION_DB`, and that flag is never set in a shell. To run code over
production rows, export them with `psql -At` and process the file. The plan has a worked
example.

`tests/deploy/test_prod_reader.py` checks all of this over the socket and skips on a host
without the role.

## cannobserv substrate

**cannobserv substrate (archiver#72/#75).** `co-core` + `co-core-aio` (the shared
Cannabis Observer core library — pure models/utils + async drivers) are declared
as plain floors and resolved from a local **wheelhouse**
(`./.wheelhouse`, gitignored) via `[tool.uv] find-links`, mirrored from the private
GCS index `gs://co-gcs-pypi` by `scripts/sync_wheelhouse.py`. This is Phase 0 of the
cluster-integration strategy — the precedent Watcher/Replicator follow. Populate the
wheelhouse before `uv sync`/`uv run`:

## Wheelhouse reproducibility

Reproducibility is `uv.lock` (pinned version + wheelhouse artifact), not the
wheelhouse contents. Upgrade: re-sync, then `uv lock --upgrade-package co-core
--upgrade-package co-core-aio`, together: co-core-aio pins co-core to its own minor, so a
minor move bumps both floors (#397). CI resolves the wheelhouse keyless via Workload
Identity Federation; `scripts/deploy.sh` fetches it into each release (§ Releases). No git sources and
no `cannobserv`/`co-core-sync` (heavy google/trello deps). Archiver depends on
**`co-core[extract]`** + `co-core-aio` — the authoring tools use `co_core_aio.fetch`
(fetch) and `co_core.pure.extract` (extract + fingerprint); see "Content-acquisition
via co-core".

## TLS trust (archiver#418)

httpx and requests verify against **certifi in the release's venv**, not `/etc/ssl`, so
an OS CA fix reaches none of the units; a deploy does. certifi is transitive: a `[tool.uv]
constraint-dependencies` floor holds it, and every `uv run --no-project` wheelhouse fetch
(which that floor doesn't reach) repeats it. `tests/test_certifi_floor.py` checks the constraint,
the fetches, every tracked `uv.lock` (the SDK's too, #420) and the installed version. For the
next distrust: raise the floor in each place and `FLOOR`, `uv lock --upgrade-package certifi`
at the root and in `clients/python/`, deploy, then the advisory's test host must
fail verification from `/srv/archiver/live/.venv/bin/python -I` with httpx and requests.
A rollback to a pre-floor release trusts the root again.

## Dependabot (archiver#192)

`.github/dependabot.yml` bumps the workflows' SHA-pinned actions weekly; `uv` is out (no
wheelhouse for the updater; § Lock audit covers the locks), the generated
`context-cadence.yml` excluded. A bot PR lands
like any other, merge commit on green CI, with **no CHANGELOG entry and no deploy**: it
touches only `.github/`. Red at WIF auth: suspect the bot run's credentials, not the bump.
Read release notes for silent default flips (setup-uv v9 `prune-cache`,
`tests/ci/test_workflow_pins.py`).

## Lock audit (archiver#420)

`.github/workflows/audit.yml` runs `scripts/audit_lock.sh` (push, PR, Mondays): `uv audit
--frozen` on `uv.lock` and `clients/python/uv.lock`, runtime and dev under separate warning
titles. **Report-only** and outside `deploy.sh`'s gate: read the annotations. `<lock> runtime
advisories` → `uv lock --upgrade-package <name>` in that lock's directory (root: wheelhouse
synced; deploy after). `audit did not run` is never clean. Dev titles stand until a dev
re-lock. By hand: any checkout, no wheelhouse.

## Power Map SDK (git tag)

`power-map-client` (archiver#304) is **not** a wheelhouse package: it resolves as a uv git
source, `https://github.com/CannObserv/power-map.git`, `subdirectory = "clients/python"`, pinned
to a release tag (`[tool.uv.sources]` in `pyproject.toml`). The repo is public, so no credential;
`uv.lock` pins the tag's commit. **The CI and deploy hosts need outbound github.com** for
`uv sync`. Client and server share one version; live Power Map reports it as `build` on `/health`.
Only `src/core/power_map/client.py` imports it (a guard test enforces that).

Upgrade: bump `tag` to the new release, read that release's diff of `clients/python/openapi.json`
in Power Map for changed status codes or fields the adapter maps, `uv sync`, run the adapter tests
(`tests/core/power_map/`).

## Environment variables

The env-var reference, adding an outbound env var, the dev-server knobs and why
`scripts/dev_server.sh` exists: [ENVIRONMENT.md](ENVIRONMENT.md).

## Timers

Periodic oneshots under `deploy/`. Those touching the database hold their own
`ARCHIVER_ALLOW_PRODUCTION_DB=1`; the drift check touches none. Install, behaviour and
logs: [deploy/README.md](../deploy/README.md).

| Timer | Cadence | Runs | Writes | Dormant when |
|---|---|---|---|---|
| `archiver-bus-health` | 10 min | `python -m src.core.bus_health` | nothing (WARN-only outbox and schema probe, #130, #330) | never |
| `archiver-pm-org-refresh` | 1 h | `python -m src.core.tools.refresh_orgs` | `pm_organizations`; `info_items.pm_org_id` on a merge (#305) | `ARCHIVER_POWER_MAP_API_KEY` unset: exits 0, no database |
| `archiver-temporal-boundary` | 00:05 UTC, `Persistent=true` | `python -m src.core.tools.temporal_boundary` | `temporal_profiles`; an item's `watch_active`/`archived_at`/`watch_spec` on a post-action; `changes_outbox` (#365) | never; 0 profiles: logs the counts, emits nothing |
| `archiver-drift` | 1 h | `python -m src.core.drift` | nothing local; one check-in to co-status (#338) | never; no key or monitor id: logs it, exits 1 |
| `archiver-backup` | 03:17 UTC | `python -m src.core.backup` as `archiver_backup` | one object in `gs://co-gcs-archiver-backup`; one check-in to co-status (#233) | never; no monitor id: logs it, exits on the backup's own result |

## Sourcing env files — why not `export $(cat … | xargs)`

> Use `set -a; . <file>; set +a` (POSIX-portable source via `.`) rather than `export $(cat <file> | xargs)`. The xargs form silently breaks for values containing spaces, quotes, newlines, or embedded `=` — and produces hard-to-diagnose failures later when those env vars are read.
