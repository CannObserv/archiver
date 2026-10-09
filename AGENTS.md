# archiver - Agent Guidelines

Be terse. Prefer fragments over full sentences; sacrifice grammar for density. Skip filler and preamble - lead with the answer or action.

## Project Overview

Central registry + authoring service for the Cannabis Observer information layer. FastAPI + PostgreSQL. Owns five registry tables (`info_items`, `info_sources`, `source_revisions`, `rep_specs`, `info_item_rep_specs`) plus the join table `info_item_sources`; the dashboard adds `app_users` and `api_keys`. Consumed by Replicator and external callers via the `archiver-client` Python SDK - **not** by Watcher (watcher#254). Produces `info.changes`, `info.registry`, `content.replicate` and `content.persist` via an internal outbox publisher; consumes `content.revisions`, `info.watch-status` and `content.artifacts` ([docs/BUS.md](docs/BUS.md) and [docs/BUS_CONSUMERS.md](docs/BUS_CONSUMERS.md) carry each stream's provenance). **Never `content.blobs`**: that role boundary is unqualified, with no read-only exception.

**Archiver makes no outbound HTTP call to Watcher (archiver#142).** The edge is bus-only in both directions: policy goes out on `info.registry`, status comes back on `info.watch-status`. There is no Watcher SDK, no `WATCHER_BASE_URL`, and no provisioning push. Do not reintroduce one - a synchronous call to a sibling service is the coupling the decoupling epic (#137) exists to remove.

**Power Map (identity for `org.*`) is called on the authoring path and by the hourly follower (#305), never during replication (#304)**: rendering reads the `pm_organizations` snapshot ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).

## Development Methodology

TDD required: Red → Green → Refactor. No production code without a failing test first.

## Environment & Tooling

Python ≥3.12, uv, pytest, ruff. **Postgres 16 on archiver's own VM** (#193 D5), not shared with watcher or notifier. Three databases: `archiver`, `archiver_dev`, `archiver_test`. Set `ARCHIVER_DEV_DATABASE_URL` or `scripts/dev_server.sh` falls back to the test DB and races the suite.

**`co-core` + `co-core-aio` resolve from a local wheelhouse** (`./.wheelhouse`,
gitignored), not PyPI. Populate it before `uv sync`/`uv run` or resolution fails:

```bash
set -a; . /etc/archiver/deploy.env; set +a   # GOOGLE_APPLICATION_CREDENTIALS=co-pypi-reader key (#341)
uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py
```

Reproducibility, the upgrade path, and the CI/deploy resolution: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

<!-- BEGIN socraticode-policy -->
## Code Exploration Policy

SocratiCode is the preferred semantic-search tool here once indexed (manifest
`.socraticodecontextartifacts.json`). Its MCP tools are **deferred** — schemas
load only after the `ToolSearch` prefetch that
`.claude/hooks/socraticode-reminder.sh` prints each session.

**Negative rule.** Use SocratiCode MCP tools first for semantic questions
("where is X", "how does Y work", "what depends on Z"). Reach for `grep`/`rg`
only on exact strings (error messages, log lines, known symbols). Reserve the
Explore subagent for path-pattern walks (`*.py` under `src/api/routes/`), not
semantic search.

| Goal | Tool |
|------|------|
| Where is X defined / how does Y work / what touches Z | `codebase_search` |
| Exact string or regex (errors, log lines, known symbols) | `grep` / `rg` |
| Imports/dependents of a file · blast radius of a change | `codebase_graph_query` / `codebase_impact` |

Full tool table, prefetch hook, per-tool guidance: [`docs/SOCRATICODE.md`](docs/SOCRATICODE.md).
<!-- END socraticode-policy -->

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
- `tests/` mirrors `src/`; `tests/deploy/` pins host contracts - `deploy.sh`
  end to end, installed units against the live release, the needrestart drop-in
  and the memory reservation, and the SocratiCode client config and server pin.

## Content-acquisition via co-core

Fetch, extract, and the content fingerprint come from **co-core**. Wiring: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**The broker is CannObserv/broker's, not this repo's (#193 D6)**; the one seam
that split left untested: [docs/BUS.md](docs/BUS.md).

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

The exe.dev proxy forwards 3000-9999 and maps the bare hostname to 8000:
dashboard `https://co-registrar.exe.xyz/`, dev server
`https://co-registrar.exe.xyz:8001/`.

## Server Lifecycle

**Port 8000 belongs to systemd. Never start uvicorn manually on 8000.**

**Production runs a release, never this checkout (#330):** `/srv/archiver/live` →
`releases/<build>`. Ship = merge, then `scripts/deploy.sh` (CI gate, rehearse on
`archiver_dev`, migrate, switch, restart, verify, switch back on failure).
`systemctl restart archiver` restarts the *current* release - it deploys nothing; hand
alembic against production is refused without the opt-in. Logs: `sudo journalctl -u
archiver -f`; deploys `-t archiver-deploy`. [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

Dev server (port 8001) - **always** via the launch script:

```bash
bash scripts/dev_server.sh
```

Anything that writes - curl, SDK scripts, manual verification - targets 8001,
never 8000. Why the script exists, its knobs, and the 2026-07-18
production-write incident: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The one
exception is DLQ discard and reprocess (#238): the queues exist only on prod's
broker, so they go to 8000, and only when the operator asks
([docs/BUS_CONSUMERS.md](docs/BUS_CONSUMERS.md)). Outbox discard and rearm
(#191) follow the same rule on 8000 ([docs/BUS.md](docs/BUS.md)).

## Environment Files

Two env files load in order (later overrides earlier):

1. `/etc/archiver/.env` - production secrets (`ARCHIVER_DATABASE_URL`); managed manually on the VM.
2. `.env` (repo root, git-ignored) - dev/agent secrets (`TEST_DATABASE_URL`, `GH_TOKEN`). Never commit; no unit reads it (#330).

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
  (`archiver.service`; the outbox probe, #130; the Power Map org follower, #305) and
  `scripts/deploy.sh`'s migration (#330). **Never in an env file** - it
  reopens the hole for every sourcing process.
- `ARCHIVER_BUS_CONSUMER` - same rule; gates the `archiver.revisions` group;
  only `archiver.service` holds it.
- `ARCHIVER_DEV_REDIS_URL` - unset means bus-dormant; prod's URL is never
  inherited. A scratch bus is a local throwaway broker, never a DB index (#240).

## Common Commands

```bash
uv sync                                      # deps; resolves co-core from ./.wheelhouse (populate it first)
uv run pytest                                # tests
uv run ruff check .                          # lint (also ruff format .)
uv run alembic upgrade head                  # apply migrations (_test/_dev DBs; production: Server Lifecycle)
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
- Bus monitoring is never on `/health` (unauthenticated, DB-free), and broker-side
  monitoring is CannObserv/broker's (#193 D6). Outbox stats (archiver#112) reach the
  dashboard badge and journald; the `archiver-bus-health` timer (#130) re-runs them
  from outside the publisher, the one surface that survives a down publisher. See
  [docs/BUS.md](docs/BUS.md).

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
Entry points only: call `configure_logging()` once. `ExecStartPre` steps in
`deploy/archiver.service` write **plain text**, not JSON - a journald consumer
must tolerate that.

**Date & Time:** UTC only. ISO 8601: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (timestamps), `YYYY-MM-DD` (dates).

**General:**
- No inline module imports; all at file top. Ruff `PLC0415` enforces this in CI
  (archiver#97).
- Translated exceptions chain with `from e` (capture the source with `as e`). Ruff `B904` enforces this in CI.
- Docstrings for public modules, classes, functions; explicit imports only; small, focused functions. Test structure mirrors source (`src/foo.py` → `tests/test_foo.py`).

**Error envelope:** Every non-2xx **API** response uses one shape
(`ErrorEnvelope`, `src/api/errors.py`); `/dashboard` renders HTML instead. Raise
via `raise_envelope(...)` or `raise_422(...)`, **never `HTTPException`
directly**; pass `source_exc=e` from inside `except X as e:`.

## Vocabulary

Data model identifiers (table names, FastAPI route paths, Redis Stream topics) stay verbatim - never rename casually. Every model, its table, and its contracts and invariants: [docs/SCHEMA.md](docs/SCHEMA.md). The Phase 1-3a `InfoSpec` model is retired - no new `info_spec*` references.

## Agent Skills

Skills live in `skills/` (agentskills.io) and `.claude/skills/` (Claude Code); overrides in `skills/` shadow the `skills-vendor/` submodules. Layout, triggers and the SessionStart hook rules: [docs/SKILLS.md](docs/SKILLS.md).

## Detail Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - layout tree; co-core acquisition wiring
- [docs/API.md](docs/API.md) - every HTTP route, its SDK wrapper, pagination
- [docs/BUS.md](docs/BUS.md) - the outbox producer; the four streams published
- [docs/BUS_CONSUMERS.md](docs/BUS_CONSUMERS.md) - the three streams consumed; consumer naming
- [docs/SCHEMA.md](docs/SCHEMA.md) - per-table contracts and invariants; the bus-state tables: [docs/SCHEMA_BUS.md](docs/SCHEMA_BUS.md)
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - wheelhouse, dev-server internals, full env-var reference
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) - changelog trigger, journald contract, error envelope, living-docs rule, `PLC0415` scope
- [docs/SKILLS.md](docs/SKILLS.md) - skill inventory, overrides, trigger table, SessionStart hook mechanics
- [docs/SOCRATICODE.md](docs/SOCRATICODE.md) - tool map, `co-index` traps, cross-repo search
- [docs/reference/tailscale.md](docs/reference/tailscale.md) - this node on the tailnet: the ACL, the bind decision, the two-names-one-host trap
- The dashboard docs - [docs/UI.md](docs/UI.md) shared mechanics and the index to the rest: [docs/PAGES.md](docs/PAGES.md), [docs/SCREENS.md](docs/SCREENS.md), [docs/INFO_ITEM_DETAIL.md](docs/INFO_ITEM_DETAIL.md), [docs/ORG_ROW.md](docs/ORG_ROW.md), [docs/REGISTER.md](docs/REGISTER.md), [docs/HEALTH_ROW.md](docs/HEALTH_ROW.md), [docs/COMPONENTS.md](docs/COMPONENTS.md), [docs/STYLE.md](docs/STYLE.md)
