---
title: Production runs immutable releases built by scripts/deploy.sh, never the dev checkout
date: 2026-10-09
status: draft
---

# Deploy releases - design

**Issue:** archiver#330 ([review comment](https://github.com/CannObserv/archiver/issues/330#issuecomment-6081843731),
[skills proposal: gregoryfoster/skills#372](https://github.com/gregoryfoster/skills/issues/372)) ·
**Cohort design:** CannObserv/broker#22 · **Adopted from:** CannObserv/status
`docs/specs/2026-09-30-deploy-releases-design.md` (R1-R13, plus status#11, #12, #14, #15, #18)
and CannObserv/processor `docs/DEPLOYMENT.md` (CR 11, the cohort-skill feedback list).

## Problem

All three units (`archiver`, `archiver-bus-health`, `archiver-pm-org-refresh`) run
`/home/exedev/archiver`, the checkout agents edit. On 2026-10-08 a feature branch checked out
there failed the follower timer twice (`No module named src.core.power_map.follower`); a restart
or reboot in that window would have served unmerged code. The same arrangement loads the dev
`.env` (the cohort's PATs) into production, lets `uv run` re-sync the dev venv at each start
(gregoryfoster/skills#201), reports `git describe --dirty` of whatever is checked out as
`/health`'s `build_id`, and fetches wheels from GCS at **start**. Separately, `alembic/env.py`
never consults `db_safety`, so any shell that sourced `/etc/archiver/.env` can migrate - or
downgrade - production, and CLAUDE.md tells agents to do exactly that by hand.

## Approach

Adopt status's R1-R13 with the deltas below. A release is `git archive` of a commit on
`origin/main` at `/srv/archiver/releases/<sha12>`, built in place
(`UV_LINK_MODE=copy uv sync --locked --no-dev --compile-bytecode`), `REVISION` written last,
then read-only and root's; `/srv/archiver/live` points at one. `scripts/deploy.sh` gates on CI,
builds, rehearses the migration on `archiver_dev`, migrates `archiver` (skipped when the schema
is `ahead`), swaps `live`, installs changed units, restarts, verifies, and switches back on
failure. Units run `uv run --frozen --no-sync` from `/srv/archiver/live` and read
`/etc/archiver/` only.

| # | Decision | Status R it adopts / why it differs |
|---|---|---|
| D1 | Units stay `User=exedev`; root owns `/srv/archiver`, `releases/` and each finished release | R2 as amended by status#14. A dedicated `archiver` user is a follow-up (processor's shape) |
| D2 | No deployed `dev` target. `dev_server.sh` stays the 8001 loop; the deploy's rehearsal is migrate + `schema_state` against `archiver_dev` from the new release (`/etc/archiver/dev.env`) | Differs from R12: CLAUDE.md routes agent writes to 8001 through `dev_server.sh`, and nothing consumes a stable 8001 |
| D3 | Migrate → swap → units → restart → verify → switch back; expand-only; skip on `ahead`; never block a start | R6, R7, R8, R9 unchanged. The runtime check is a CLI plus a bus-health WARN, not `/ready` (only `/health` and `/openapi.json` may be open) |
| D4 | Both timers run `live`. Verify forces one `archiver-bus-health` pass (waiting out one in flight); never forces `pm-org-refresh` | R6's forced pass, applied to the read-only probe only |
| D5 | Keep 5 releases plus the linked one | R13 (~250 MB each; 9 GB free) |
| D6 | CI gate: newest `push` run of `ci.yml` on `main`, every job `success`, floor `lint test client-drift changelog`; `--skip-ci` logged | status#11 / processor#34 unchanged; the repo is public, no token |
| D7 | Drift check reporting to co-status `co-archiver-drift` | processor#35's shape; **separate issue** (operator prerequisites) |
| D8 | `/health` `build_id` comes from the release's `REVISION`; `null` outside a release | R10, but `null` not `"dev"`: the field is already nullable, so the contract change is description-only |
| D9 | `alembic/env.py` refuses an un-opted-in production DB when online; only `deploy.sh` passes `ARCHIVER_ALLOW_PRODUCTION_DB=1` to it | status#15 |
| D10 | Wheels are fetched into the release by the release's own `sync_wheelhouse.py`, at build time, with the co-pypi-reader key from a deploy-only `/etc/archiver/deploy.env` | broker#22 Q5. Not processor's copy of the dev `.wheelhouse`: find-links locks by filename without a hash. The fetch must carry every file `uv.lock` names for co-core - sdists too - or `--locked` fails (seen building PR A's worktree) |
| D11 | Before `REVISION`, every `ExecStart` module under the release's `deploy/*.service` must import from the release venv, and every executable a unit runs from `/srv/archiver/live/` must exist in the release (CR 7) | New: the 2026-10-08 failure mode, caught at deploy time |
| D12 | Units are installed from the release (only those that differ); new units installed, never enabled; host configs compared, never installed | status#18 |
| D13 | A failed **first** deploy has no release to return to: it puts back the units it replaced (the checkout-backed ones), removes `live`, restarts on them, and exits 1 when archiver answers, 4 when not. The cutover is one `scripts/deploy.sh`; there is no `--no-restart` | processor's first-deploy rule. status's `--no-restart` existed because its units went in by hand before status#18 |
| D14 | The deploy runs only merged logic: `scripts/deploy.sh` refuses unless it is byte-identical to `origin/main:scripts/deploy.sh` (CR 10) | New. The commit must be on `origin/main`; so must the logic deploying it |

## Tradeoffs / alternatives

- **Main-checkout guard (`ExecStartPre` refusing a non-`main` tree)** - rejected: trades silent
  drift for a refused restart (replicator#94).
- **Dedicated `archiver` user now** - deferred, not rejected: it changes identity, `/etc/archiver`
  ownership and credential delivery in the same cutover as the code path. Filed as a follow-up.
- **Deployed `dev` unit on 8001** - rejected for now: contends with `dev_server.sh`, the
  sanctioned agent write target, and nothing consumes it.
- **An open `/ready` with the schema state** - rejected: breaks the "only `/health` and
  `/openapi.json` are open" rule; the bus-health timer is already the out-of-process surface.
- **Copying `.wheelhouse` from the dev checkout** - rejected: re-admits dev-writable bytes into
  a release.

## Steps

1. **PR A - groundwork, no production change** (this branch): this note; `alembic/env.py`
   crosses `db_safety` online (D9); `src/core/schema_state.py` with `classify()` and a CLI
   exiting 0 `current`/`ahead`, 3 `behind`/`unmigrated`, 2 otherwise (D3); `archiver-bus-health`
   WARNs on `behind`/`unmigrated`; `src/core/build.py` reads `REVISION` and `/health` uses it
   (D8), with CHANGELOG, OpenAPI snapshot and SDK regenerated. The unit keeps writing
   `BUILD_ID` until PR B, so the build path falls back to it there.
2. **PR B - the deploy**: `scripts/deploy.sh` (D1-D6, D10-D12) and `tests/deploy/test_deploy.py`
   on status's stub harness; units moved to `/srv/archiver/live` with `--frozen --no-sync`, no
   repo `.env`, no git stamp, no wheelhouse `ExecStartPre`; unit invariant tests (no
   `/home/exedev`, no unit syncs); `test_installed_unit_matches_repo.py` compares with the live
   release; CLAUDE.md § Server Lifecycle and § Infrastructure, `docs/DEPLOYMENT.md`,
   `docs/CONVENTIONS.md`, `docs/SCHEMA.md` (expand-only), `deploy/README.md`.
3. **Cutover - operator present.** Merging PR B changes nothing that runs: the installed units
   stay checkout-backed until a deploy replaces them. The cutover is PR B's first
   `scripts/deploy.sh` (D13; docs/DEPLOYMENT.md § First deploy): create root-owned
   `/srv/archiver` and `/etc/archiver/{dev,deploy}.env` (0640 before writing), switch the
   checkout to an up-to-date `main` (D14), run it; verify `/health` `build_id` ==
   `readlink /srv/archiver/live`; switch the checkout to a branch, restart and start both
   timers' services, and show `build_id` unchanged.
4. **Cleanup**: delete `.skills/worktree_venv`; drop the hand-run `alembic upgrade head` from
   docs; set `.skills/deploy_command` when gregoryfoster/skills#345 ships.
5. **Follow-ups filed**: drift check (D7), dedicated service user (D1), the skills issue
   (filed as gregoryfoster/skills#372).

## Open questions / risks

- **`BUILD_ID` fallback lifetime.** PR A keeps reading the unit's `BUILD_ID` when no `REVISION`
  exists, so `/health` does not go `null` between PR A and the cutover. PR B removes it.
- **Restart budget.** `archiver.service` has the default `TimeoutStopSec` (90 s); the verify
  window is derived from it plus start time, not a fixed 60 s.
- **First deploy rollback.** With nothing to switch back to, a failed first deploy restores the
  replaced units (the checkout-backed ones) and restarts on them - the cutover's escape hatch.
