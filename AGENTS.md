# archiver - Agent Guidelines

Be terse. Prefer fragments over full sentences; sacrifice grammar for density. Skip filler and preamble - lead with the answer or action.

## Project Overview

Central registry + authoring service for the Cannabis Observer information layer. FastAPI + PostgreSQL. Owns five registry tables (`info_items`, `info_sources`, `source_revisions`, `rep_specs`, `info_item_rep_specs`) plus the join table `info_item_sources`; the dashboard adds `app_users` and `api_keys`. Consumed by the (forthcoming) Replicator and external callers via the `archiver-client` Python SDK - **not** by Watcher (watcher#254). Produces `info.changes`, `info.registry` and `content.replicate` via an internal outbox publisher; consumes `content.revisions`, `info.watch-status` and `content.artifacts` ([docs/BUS.md](docs/BUS.md) carries each stream's provenance). **Never `content.blobs`**: that role boundary is unqualified, with no read-only exception.

**Archiver makes no outbound HTTP call to Watcher (archiver#142).** The edge is bus-only in both directions: policy goes out on `info.registry`, status comes back on `info.watch-status`. There is no Watcher SDK, no `WATCHER_BASE_URL`, and no provisioning push. Do not reintroduce one - a synchronous call to a sibling service is the coupling the decoupling epic (#137) exists to remove.

## Development Methodology

TDD required: Red → Green → Refactor. No production code without a failing test first.

## Environment & Tooling

Python ≥3.12, uv, pytest, ruff. **Postgres 16 on archiver's own VM** - dedicated since #193 D5, not the instance shared with watcher and notifier. Three databases: `archiver`, `archiver_dev`, `archiver_test`. Set `ARCHIVER_DEV_DATABASE_URL` or `scripts/dev_server.sh` falls back to the test DB and races the suite.

**`co-core` + `co-core-aio` resolve from a local wheelhouse** (`./.wheelhouse`,
gitignored), not PyPI. Populate it before `uv sync`/`uv run` or resolution fails:

```bash
set -a; . /etc/archiver/.env; set +a   # GOOGLE_APPLICATION_CREDENTIALS=co-pypi-reader key
uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py
```

Reproducibility, the upgrade path, and the CI/deploy resolution: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Code Exploration Policy

SocratiCode is configured here (`.socraticodecontextartifacts.json`); the index is per-host, and the SessionStart health hook reports whether it is built. Its MCP tools are **deferred** - schemas load only after a `ToolSearch` prefetch, and the SessionStart hook prints the query. Run it before exploring.

**Negative rule.** For broad semantic questions ("where is X", "how does Y work", "what depends on Z"), use SocratiCode MCP tools first. Reach for `grep`/`ripgrep` only on exact strings (error messages, log lines, known symbols). Reserve the Explore subagent for path-pattern walks (e.g. "all `*.py` under `src/api/routes/`"), not semantic search.

Tool-by-goal map and the `ToolSearch` prefetch query: [docs/SKILLS.md](docs/SKILLS.md).

## Architecture

Full layout tree: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The boundaries an
`ls` will not explain:

- `src/api/` is the HTTP contract, `src/dashboard/` the HTMX admin UI, `src/core/`
  the domain. The dashboard **clamps** paginated `limit`/`offset` where the API
  **422s** - deliberate, see [docs/SCREENS.md](docs/SCREENS.md).
- `alembic/` is scoped to the `information` schema *inside* the archiver database.
- `clients/python/` is the one vendored SDK - regenerated from a committed
  OpenAPI snapshot, gated by the CI `client-drift` job; never hand-edit
  `generated/`.
- `src/core/db_safety.py` is mirrored by `scripts/dev_server.sh`, kept in step by
  `tests/scripts/test_db_guard_parity.py`.
- `tests/` mirrors `src/`; `tests/deploy/` asserts installed systemd artifacts match `deploy/`.

## Content-acquisition via co-core

Fetch, extract, and the content fingerprint come from **co-core**; the former
`src/core/{fetchers,extractors,simhash,extraction_defaults}` mirror is deleted. Wiring: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**The broker is not operated from this repo (#193 D6).** Its tuning, health
probe, and stream inventory live in
[CannObserv/broker](https://github.com/CannObserv/broker); archiver is a client.
One seam survives that split with no test spanning it: the broker config's
`maxmemory` cap and `OutOfMemoryError` being transient in
`_TRANSIENT_PUBLISH_ERRORS` are **one decision**, and each repo names the other
in a comment (R5).

**No cross-repo mirror discipline (CannObserv/watcher#159, #236).** Content
acquisition is co-core's (above) and the change-bus contracts + driver are too
(see [docs/BUS.md](docs/BUS.md)). `src/core/logging.py` is service-local - Watcher
keeps its own copy; there is no parity requirement and no sibling sync. Don't
reintroduce a mirror obligation for anything under `src/`.

## Infrastructure

| Service | Port | Managed by |
|---|---|---|
| Archiver (live) | 8000 | `systemctl` (`archiver.service`) |
| Archiver (dev) | 8001 | `bash scripts/dev_server.sh` (never hand-rolled uvicorn) |

The exe.dev proxy maps the bare hostname to 8000: dashboard
`https://co-registrar.exe.xyz/`, dev server `https://co-registrar.exe.xyz:8001/`.
Archiver has its own VM (archiver#193); the broker is on a third node
(CannObserv/broker#1).

**The broker is a network hop.** Archiver reaches it over the tailnet as
`redis://default:<password>@broker:6379/0`. This host answers to two names,
`co-registrar` and `archiver`, both on port 8000, so **an HTTP 200 on a short
name proves nothing about the tailnet**. Node identity, the ACL, the bind
decision, and the MagicDNS failure that took down three services:
[docs/reference/tailscale.md](docs/reference/tailscale.md).

## Server Lifecycle

**Port 8000 belongs to systemd. Never start uvicorn manually on 8000.**

After committing to `main`: `sudo systemctl restart archiver`. After DB model changes: `uv run alembic upgrade head` then restart. Logs: `sudo journalctl -u archiver -f`.

Dev server (port 8001) - **always** via the launch script:

```bash
bash scripts/dev_server.sh
```

Anything that writes - curl, SDK scripts, manual verification - targets 8001,
never 8000. Why the script exists, its knobs, and the 2026-07-18
production-write incident: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Environment Files

Two env files load in order (later overrides earlier):

1. `/etc/archiver/.env` - production secrets (`ARCHIVER_DATABASE_URL`); managed manually on the VM.
2. `.env` (repo root, git-ignored) - dev/agent secrets (`TEST_DATABASE_URL`, `GH_TOKEN`). Never commit.

```bash
set -a
[ -f /etc/archiver/.env ] && . /etc/archiver/.env
[ -f .env ] && . .env
set +a
```

Source exactly that way - `export $(cat … | xargs)` silently corrupts values.

**Four variables carry safety rules; the rest are reference
([docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).**

- `TEST_DATABASE_URL` - **must not equal** `ARCHIVER_DATABASE_URL` or
  `DATABASE_URL`; teardown drops the entire `information` schema. Name must end in
  `_test`.
- `ARCHIVER_ALLOW_PRODUCTION_DB` - set only by `deploy/` units
  (`archiver.service`; the outbox probe, #130). **Never in an env file** - it
  reopens the hole for every sourcing process.
- `ARCHIVER_BUS_CONSUMER` - same rule; gates the `archiver.revisions` group;
  only `archiver.service` holds it.
- `ARCHIVER_DEV_REDIS_URL` - unset means the dev server is bus-dormant; prod's
  `ARCHIVER_REDIS_URL` is never inherited, and a scratch bus is now a scratch
  *database on a shared remote broker*.

## Common Commands

```bash
uv sync                                      # deps; resolves co-core from ./.wheelhouse (populate it first)
uv run pytest                                # tests
uv run ruff check .                          # lint (also ruff format .)
uv run alembic upgrade head                  # apply migrations
uv run alembic revision --autogenerate -m "description"

# Pre-commit: install once per clone, then it runs on each git commit.
uv run pre-commit install
uv run pre-commit run --all-files            # manual sweep

# CI mirrors these checks; failing locally also fails CI on push/PR.
```

## API & Change-Bus Surface

Routes and SDK wrappers: [docs/API.md](docs/API.md); the bus contracts and the
`info.changes` payloads: [docs/BUS.md](docs/BUS.md).
Rules holding across all of it:

- `X-API-Key` on every route; only `/health` and `/openapi.json` are open.
- List routes return `{items, has_more, limit, offset}`; `limit` default 100,
  max 500. Over-max is a 422, not a clamp.
- Bus payloads carry `schema_version: int`. Bump only on *incompatible* reshapes;
  additive fields are not a bump, and consumers must tolerate them.
- Bus monitoring: outbox stats (archiver#112) on the dashboard badge + a
  journald line; the `archiver-bus-health` timer (#130) re-runs the query from
  outside the publisher process, the only surface still reporting when the
  publisher is down. **Broker-side monitoring is not this repo's** - it is
  CannObserv/broker's, on the broker's node (#193 D6). Never on `/health`
  (unauthenticated, DB-free). See [docs/BUS.md](docs/BUS.md).

## Conventions

Reasoning and worked examples for the changelog trigger, the journald contract,
the error envelope, the living-docs rule and `PLC0415`'s scope:
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

**Commit Messages:**
```
#<number> <type>: <description>      # with issue
<type>: <description>                # without issue
```
Types: feat, fix, refactor, docs, test, chore.

**Changelog:** Update `CHANGELOG.md` when a change touches a **contract-visible
path**, and only then. Path-based, not intent-based; CI and the pre-push guard
enforce the same regex:

```
^(alembic/versions/|src/api/routes/|src/api/schemas/|clients/python/)
```

**Dashboard living docs:** a dashboard change updates the doc it touches in the
same commit; failing to is a CR blocker. Which doc each change requires:
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

**Logging:**
```python
from src.core.logging import get_logger
logger = get_logger(__name__)
```
Entry points only: call `configure_logging()` once. `ExecStartPre` steps write
**plain text**, not JSON - a journald consumer must tolerate that.

**Date & Time:** UTC only. ISO 8601: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (timestamps), `YYYY-MM-DD` (dates).

**General:**
- No inline module imports; all at file top. Ruff `PLC0415` enforces this in CI
  (archiver#97).
- Translated exceptions chain via `raise HTTPException(...) from e` (capture the source with `as e`). Ruff `B904` enforces this in CI.
- Docstrings for public modules, classes, functions; explicit imports only; small, focused functions. Test structure mirrors source (`src/foo.py` → `tests/test_foo.py`).

**Error envelope:** Every non-2xx **API** response uses one shape
(`ErrorEnvelope`, `src/api/errors.py`); `/dashboard` renders HTML instead. Raise
via `raise_envelope(...)` or `raise_422(...)`, **never `HTTPException`
directly**; pass `source_exc=e` from inside `except X as e:`.

## Vocabulary

Data model identifiers (table names, FastAPI route paths, Redis Stream topics) stay verbatim - never rename casually. Model ↔ table:

`InfoItem` ↔ `info_items` · `InfoSource` ↔ `info_sources` · `SourceRevision` ↔
`source_revisions` · `InfoItemSource` ↔ `info_item_sources` · `RepSpec` ↔
`rep_specs` · `InfoItemRepSpec` ↔ `info_item_rep_specs` · `ChangesOutboxRow` ↔
`changes_outbox` · `RevokedInfoItem` ↔ `revoked_info_items` · `WatchStatus` ↔
`watch_status` · `ReplicationCommand` ↔ `replication_commands` ·
`BusTailCursor` ↔ `bus_tail_cursors`

What each one is, plus its contracts and invariants:
[docs/SCHEMA.md](docs/SCHEMA.md) - it documents every one of them. The Phase
1-3a `InfoSpec` model is retired - no new `info_spec*` references.

## Agent Skills

Skills live in `skills/` (agentskills.io) and `.claude/skills/` (Claude Code); overrides in `skills/` shadow vendor submodules in `skills-vendor/`. Cross-project search to `watcher`/`notifier` needs a per-instance `.claude/settings.local.json` (gitignored) - [docs/SKILLS.md](docs/SKILLS.md).

## SessionStart Hooks

`.claude/settings.json` wires three hooks: the SocratiCode prefetch reminder,
the once-per-day SocratiCode health check, and the once-per-day `skills-vendor/`
refresh. Both halves are load-bearing - a script `settings.json` does not name
never runs and looks identical to one that works
(`tests/scripts/test_claude_hooks_registered.py` fails on the missing half).
All three scripts are symlinks into `skills-vendor/`: never re-copy one, never
turn the committed `.skills/doctor.sh` into one, and never un-wire a hook to
hold a submodule - use `.skills/skills-pin`. Each hook and its logs:
[docs/SKILLS.md](docs/SKILLS.md).

## Detail Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - layout tree; co-core acquisition wiring
- [docs/API.md](docs/API.md) - every HTTP route, its SDK wrapper, pagination
- [docs/BUS.md](docs/BUS.md) - the outbox producer; the three streams published and the three consumed
- [docs/SCHEMA.md](docs/SCHEMA.md) - per-table contracts and invariants
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - wheelhouse, dev-server internals, full env-var reference
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) - the reasoning behind every Conventions rule
- [docs/SKILLS.md](docs/SKILLS.md) - skill inventory, overrides, trigger table, SessionStart hook mechanics
- [docs/reference/tailscale.md](docs/reference/tailscale.md) - this node on the tailnet: the ACL, the bind decision, the two-names-one-host trap
- The dashboard docs - [docs/UI.md](docs/UI.md) shared mechanics and the index to the rest: [docs/PAGES.md](docs/PAGES.md), [docs/SCREENS.md](docs/SCREENS.md), [docs/INFO_ITEM_DETAIL.md](docs/INFO_ITEM_DETAIL.md), [docs/COMPONENTS.md](docs/COMPONENTS.md), [docs/STYLE.md](docs/STYLE.md)
