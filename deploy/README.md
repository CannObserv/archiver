# deploy/

Systemd units for the Archiver VM.

| Unit | Type | Purpose |
|---|---|---|
| `archiver.service` | service | The live API on port 8020 (see CLAUDE.md → Server Lifecycle). |
| `watcher-live-drift.service` | oneshot | Layer C (#70): detect `watcher_client` snapshot drift vs **live** Watcher and open a regen PR. |
| `watcher-live-drift.timer` | timer | Fires the oneshot daily. |

## watcher-live-drift (Layer C, archiver#70)

The committed `clients/watcher-python/watcher-openapi.json` snapshot can go stale
relative to the live Watcher service — the #66 failure mode the hermetic CI
`client-drift` gate cannot see. This timer runs **on the VM** (so it reaches
Watcher at `http://localhost:8000` — no public URL, no hairpin-NAT, no
runner↔Watcher uptime coupling) and turns real upstream drift into a reviewable
PR instead of a prod incident.

- `scripts/check_watcher_live_drift.py` — pure detector (stdlib): fetch live
  `/openapi.json`, canonicalize as `regen.sh` does, byte-compare to the snapshot.
  Exit `0` no drift · `1` drift · `3` unreachable (skip).
- `scripts/watcher_live_drift_pr.sh` — remediation: on drift, regen snapshot +
  tree via `regen.sh` in an isolated worktree off `origin/main`, then open a PR.
  Branch is keyed on the live spec SHA, so re-runs while a PR is open are no-ops.

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
- `GH_TOKEN` in `/etc/archiver/.env` (for `gh pr create`) and push auth on the
  repo's `origin` remote.
- `/openapi.json` is public, so no `WATCHER_API_KEY` is needed for the fetch.
