# deploy/

Systemd units for the Archiver VM.

| Unit | Type | Purpose |
|---|---|---|
| `archiver.service` | service | The live API on port 8020 (see CLAUDE.md → Server Lifecycle). Its `ExecStartPre` mirrors the cannobserv wheelhouse (see below). |
| `watcher-live-drift.service` | oneshot | Layer C (#70): detect `watcher_client` snapshot drift vs **live** Watcher and open a regen PR. |
| `watcher-live-drift.timer` | timer | Fires the oneshot daily. |

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
  google-cloud-storage`, so no system Cloud SDK is needed.

**Deploy step for the co-core adoption (one-time).** The unit gained an
`ExecStartPre`; reinstall it before the next restart or the parity test
(`tests/deploy/test_installed_unit_matches_repo.py`) flags drift:

```bash
sudo cp deploy/archiver.service /etc/systemd/system/ && sudo systemctl daemon-reload
# then, when safe: sudo systemctl restart archiver
```

(CI is keyless instead — the `lint`/`test` jobs authenticate via Workload
Identity Federation; see `.github/workflows/ci.yml`.)

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
