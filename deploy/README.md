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
```

**`archiver.service` ordering + floor.** The unit declares
`Wants=redis-server.service` + `After=redis-server.service` (soft ordering — the
outbox tolerates broker downtime, so no `Requires=`/`BindsTo=`) and an
`ExecStartPre` that runs `scripts/check_redis_floor.sh` to assert the server is
≥7.0 (the consumer path's `XAUTOCLAIM` requirement) when `ARCHIVER_REDIS_URL` is
set. The probe is `timeout`-bounded (`ARCHIVER_REDIS_FLOOR_TIMEOUT`, default 5s)
so it can never hang startup, and warns when `redis-cli` lacks TLS support for a
`rediss://` URL; it soft-skips (never blocks) on a dormant or unreachable broker
and blocks only a genuinely-<7.0 reachable one. Reinstall the unit after any edit
(see the parity note under the wheelhouse section) —
`tests/deploy/test_installed_unit_matches_repo.py` flags drift.

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
