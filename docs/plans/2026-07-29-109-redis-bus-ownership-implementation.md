---
title: Redis change-bus ownership — implementation plan (archiver#109)
date: 2026-07-29
status: draft
---

# Redis change-bus ownership — implementation

Design of record: `docs/plans/2026-07-29-redis-bus-ownership-design.md` (approved).
This plan is the *how* — task-by-task execution of that design.

## Problem

The approved design (#109) assigns Archiver operational ownership of the local
Redis broker and activates the dormant producer. It needs turning into concrete,
verifiable changes: tracked deploy artifacts, unit ordering + a version-floor
guard, an operator-side stream cap, a dev/prod isolation guard, cross-repo doc
updates, and a gated prod activation. Getting the ordering and the
hard-to-reverse activation step right matters — this is the moment `info.changes`
starts carrying real traffic.

## Approach

Land everything except activation in one Archiver PR on branch
`109-redis-bus-ownership`: the tracked `redis-server` drop-in, `archiver.service`
soft ordering + version-floor `ExecStartPre`, an operator-side periodic `XTRIM`
in the outbox publisher loop (TDD), the `dev_server.sh` Redis-equality guard
(TDD), and Archiver's own doc updates. Watcher's AGENTS.md correction is a
separate PR against `CannObserv/watcher`. Prod activation (setting
`ARCHIVER_REDIS_URL`, restart, confirm drain) is the final manual, gated step
after merge — deliberately isolated because it is the one hard-to-reverse action.
All three former open items are already resolved in the design doc against
co-core source, so no upstream dependency blocks this.

## Tradeoffs / alternatives

- **Fold the `MAXLEN` cap into each XADD via a co-core `BusPublish.maxlen` arg** —
  rejected for now: requires a co-core release + wheelhouse re-sync + lock bump on
  the critical path. Operator-side `XTRIM` is self-contained; upstreaming stays a
  later optimization.
- **Activate in the same PR as the artifacts** — rejected: activation is the only
  irreversible, prod-touching action and should be a separate deliberate step with
  its own verification, not buried in a code-review merge.
- **`Requires=`/`BindsTo=redis-server.service`** — rejected in design: defeats the
  outbox's downtime tolerance and cascades restarts. Soft `Wants=`+`After=` only.

## Steps

1. **Tracked Redis drop-in.** Add `deploy/redis-server.dropin.conf` (`appendonly
   yes`, `appendfsync everysec`, assert `maxmemory-policy noeviction`) + install
   instructions in `deploy/README.md`. *Verify:* install to
   `/etc/systemd/system/redis-server.service.d/`, `systemctl daemon-reload &&
   systemctl restart redis-server`, then `redis-cli CONFIG GET appendonly` → `yes`
   and `... maxmemory-policy` → `noeviction`.
2. **Version-floor guard script.** Add `scripts/check_redis_floor.sh` — no-op when
   `ARCHIVER_REDIS_URL` unset; else read `redis_version` via `redis-cli -u "$URL"
   INFO server` and exit non-zero if `< 7.0`. *Verify:* passes against live
   7.0.15; returns non-zero when fed a `<7.0` stub.
3. **`archiver.service` ordering + floor check.** Add `Wants=redis-server.service`
   + `After=redis-server.service` to `[Unit]`; add `ExecStartPre=` invoking the
   step-2 script (before `ExecStart`). Reinstall the unit. *Verify:*
   `systemctl show archiver -p After,Wants` lists `redis-server.service`;
   `tests/deploy/` (installed-unit-matches-`deploy/`) passes.
4. **(TDD) Operator-side `XTRIM` in the publisher.** Failing test first: the drain
   loop issues `XTRIM info.changes MAXLEN ~ N` on a cadence (e.g. once per idle
   cycle / every K drains). Then thread the lifespan-owned `redis_client` into
   `outbox_publisher.run(...)`, add the trim + an `ARCHIVER_REDIS_STREAM_MAXLEN`
   knob (default per open question), wire it in `src/api/main.py`. *Verify:* new
   test green; full `uv run pytest` green.
5. **(TDD) `dev_server.sh` Redis-equality guard.** Failing test/parity assertion
   first: dev must refuse to start when resolved dev `ARCHIVER_REDIS_URL` equals
   prod's (mirror the Postgres `_test`/`_dev` guard already in the script and in
   `tests/scripts/test_db_guard_parity.py`). Then implement the guard. *Verify:*
   script exits non-zero on equal URLs; guard test green.
6. **Docs.** Archiver `CLAUDE.md`: state Archiver operates `redis-server`, add the
   `ARCHIVER_REDIS_STREAM_MAXLEN` env knob to the table, note dev `/1` vs prod
   `/0`. Separate PR on `CannObserv/watcher`: strike the vestigial `REDIS_URL`
   framing in its AGENTS.md, point to Archiver as operator. *Verify:* both read
   correctly; no CHANGELOG entry required (no path under
   `alembic/versions/|src/api/routes/|src/api/schemas/|clients/python/` is
   touched — publisher/main/deploy/scripts/docs are all outside the trigger regex).
7. **Green + merge.** `uv run ruff check . && uv run ruff format --check . && uv
   run pytest` all green; open PR, code review, merge to `main`.
8. **Activation (manual, gated — do last).** Set
   `ARCHIVER_REDIS_URL=redis://localhost:6379/0` in `/etc/archiver/.env`;
   `sudo systemctl restart archiver`. *Verify:* journal shows "Outbox publisher
   started"; produce a change (e.g. a source revision) and confirm it drains —
   `redis-cli XLEN info.changes` increments and `XINFO STREAM info.changes` shows
   entries; confirm `XLEN` stays bounded under the cap after step-4 trim fires.

## Open questions / risks

- **`XTRIM` cadence + `MAXLEN` default.** Proposed: `ARCHIVER_REDIS_STREAM_MAXLEN`
  default `100_000`, trimmed once per idle cycle (approximate `~`). Confirm the
  default value and cadence, or leave to implementer's judgement.
- **`fakeredis` availability for step 4's test.** If not already a dev dep, the
  trim test either adds it or asserts against a mocked client — decide at
  implementation.
- **Watcher PR is a separate review cycle** (cross-repo, `GH_TOKEN_WATCHER`); it
  can merge independently and is not a blocker for Archiver merge.
- **Activation (step 8) is the only irreversible action** and touches prod. Once
  the producer is live with no consumer yet, entries accumulate — bounded by the
  step-4 cap and made durable by the step-1 AOF config. Do it deliberately, verify
  the drain, and it can be rolled back by unsetting `ARCHIVER_REDIS_URL` + restart.
