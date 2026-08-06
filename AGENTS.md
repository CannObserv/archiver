# archiver — Agent Guidelines

Be terse. Prefer fragments over full sentences. Skip filler and preamble. Sacrifice grammar for density. Lead with the answer or action.

## Project Overview

Central registry + authoring service for the Cannabis Observer information layer. FastAPI + PostgreSQL. Owns five registry tables (`info_items`, `info_sources`, `source_revisions`, `rep_specs`, `info_item_rep_specs`) plus one Item↔X join table (`info_item_sources`; the `info_item_source_revisions` pin table was dropped in archiver#101). Dashboard adds two more: `app_users` (upserted from proxy headers) and `api_keys` (hashed key store). Consumed by Watcher and (forthcoming) Replicator via the `archiver-client` Python SDK; produces a Redis Stream (`info.changes`) via an internal outbox publisher.

Phase 4 (the current model — Archiver v2) shipped 2026-05-09 on branch `phase-4-archiver-v2`. Design + implementation plan:

- `docs/plans/2026-05-08-archiver-v2-architecture-design.md`
- `docs/plans/2026-05-08-phase-4-archiver-v2-implementation.md`

## Development Methodology

TDD required. Red → Green → Refactor. No production code without a failing test first.

## Environment & Tooling

Python ≥3.12, uv, pytest, ruff. Postgres on the local VM (shared instance with watcher and notifier; archiver owns its own database).

**`co-core` + `co-core-aio` resolve from a local wheelhouse** (`./.wheelhouse`,
gitignored), not PyPI. Populate it before `uv sync`/`uv run` or resolution fails:

```bash
set -a; . /etc/archiver/.env; set +a   # GOOGLE_APPLICATION_CREDENTIALS=co-pypi-reader key
uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py
```

Reproducibility, the upgrade path, and the CI/deploy resolution: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Code Exploration Policy

SocratiCode is indexed on this repo (`.socraticodecontextartifacts.json` present). Its MCP tools are **deferred** — schemas load only after a `ToolSearch` prefetch. The SessionStart hook prints the prefetch query; run it before exploring.

**Negative rule.** For broad semantic questions ("where is X", "how does Y work", "what depends on Z"), use SocratiCode MCP tools first. Reach for `grep`/`ripgrep` only on exact strings (error messages, log lines, known symbols). Reserve the Explore subagent for path-pattern walks (e.g. "all `*.py` under `src/api/routes/`"), not semantic search.

| Goal | Tool |
|------|------|
| Where is X defined / how does Y work / what files touch Z | `codebase_search` |
| Exact string/regex match (errors, log lines, known symbols) | `grep` / `rg` |
| Blast radius of changing/deleting a file or function | `codebase_impact` |
| What does an entry point actually do? | `codebase_flow` |
| Callers and callees of a function | `codebase_symbol` |
| List symbols in a file or search by name across the project | `codebase_symbols` |
| Imports/dependents of a file | `codebase_graph_query` |
| Spot circular deps or structural issues | `codebase_graph_circular`, `codebase_graph_stats` |
| Visualise module structure | `codebase_graph_visualize` |
| Verify index is up to date | `codebase_status` |
| DB schemas, deployment topology, runbook context | `codebase_context` / `codebase_context_search` |

Prefetch query (run via `ToolSearch` once per session if the SessionStart reminder isn't loaded):

`select:mcp__plugin_socraticode_socraticode__codebase_search,mcp__plugin_socraticode_socraticode__codebase_symbol,mcp__plugin_socraticode_socraticode__codebase_symbols,mcp__plugin_socraticode_socraticode__codebase_flow,mcp__plugin_socraticode_socraticode__codebase_impact,mcp__plugin_socraticode_socraticode__codebase_graph_query,mcp__plugin_socraticode_socraticode__codebase_graph_circular,mcp__plugin_socraticode_socraticode__codebase_graph_stats,mcp__plugin_socraticode_socraticode__codebase_graph_visualize,mcp__plugin_socraticode_socraticode__codebase_status,mcp__plugin_socraticode_socraticode__codebase_context,mcp__plugin_socraticode_socraticode__codebase_context_search`

## Architecture

Full layout tree: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The boundaries an
`ls` will not explain:

- `src/api/` is the HTTP contract, `src/dashboard/` the HTMX admin UI, `src/core/`
  the domain. The dashboard **clamps** paginated `limit`/`offset` where the API
  **422s** — deliberate, see [docs/UI.md](docs/UI.md).
- `alembic/` is scoped to the `information` schema *inside* the archiver database.
- `clients/` holds vendored SDKs regenerated from committed OpenAPI snapshots and
  gated by the CI `client-drift` job — never hand-edit `generated/`.
- `src/core/db_safety.py` is mirrored by `scripts/dev_server.sh`, kept in step by
  `tests/scripts/test_db_guard_parity.py`.
- `tests/` mirrors `src/`; `tests/deploy/` asserts installed systemd artifacts
  match `deploy/` (file-parity only).

## Content-acquisition via co-core (archiver#72 Phase 1)

Fetch, extract, and the content fingerprint come from **co-core**; the former
`src/core/{fetchers,extractors,simhash,extraction_defaults}` mirror is deleted.
Wiring detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**No cross-repo mirror discipline (CannObserv/watcher#159, #236).** Content
acquisition is co-core's (above) and the change-bus contracts + driver are too
(see [docs/API.md](docs/API.md)). `src/core/logging.py` is service-local — Watcher
keeps its own copy; there is no parity requirement and no sibling sync. Don't
reintroduce a mirror obligation for anything under `src/`.

## Infrastructure

| Service | Port | Managed by |
|---|---|---|
| Archiver (live) | 8020 | `systemctl` (`archiver.service`) |
| Archiver (dev) | 8021 | `bash scripts/dev_server.sh` (never hand-rolled uvicorn) |

The exe.dev proxy forwards 3000–9999. Dev server reachable at `https://watcher.exe.xyz:8021/` (the host is shared with the watcher VM).

## Server Lifecycle

**Port 8020 belongs to systemd. Never start uvicorn manually on 8020.**

After committing to `main`: `sudo systemctl restart archiver`. After DB model changes: `uv run alembic upgrade head` then restart. Logs: `sudo journalctl -u archiver -f`.

Dev server (port 8021) — **always** via the launch script:

```bash
bash scripts/dev_server.sh
```

Anything that writes — curl against the dashboard, SDK scripts, manual
verification — must target 8021, never 8020.

Why the script exists, its knobs, and the 2026-07-18 production-write incident:
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Environment Files

Two env files load in order (later overrides earlier):

1. `/etc/archiver/.env` — production secrets (`ARCHIVER_DATABASE_URL`). Persistent, managed manually on the VM.
2. `.env` (repo root, git-ignored) — dev/agent secrets (`TEST_DATABASE_URL`, `GH_TOKEN`). Never commit.

```bash
set -a
[ -f /etc/archiver/.env ] && . /etc/archiver/.env
[ -f .env ] && . .env
set +a
```

Source exactly that way — `export $(cat … | xargs)` silently corrupts values.

**Three variables carry safety rules; the rest are reference
([docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).**

- `TEST_DATABASE_URL` — **must not equal** `ARCHIVER_DATABASE_URL` or
  `DATABASE_URL`; teardown drops the entire `information` schema. Name must end in
  `_test`.
- `ARCHIVER_ALLOW_PRODUCTION_DB` — only `deploy/archiver.service` sets it. **Never
  put it in an env file** — that re-opens the hole for every process that sources
  them.
- `ARCHIVER_DEV_REDIS_URL` — unset means the dev server is bus-dormant; prod's
  `ARCHIVER_REDIS_URL` is never inherited.

## Common Commands

```bash
# Populate the cannobserv wheelhouse before installing (see Environment & Tooling):
set -a; . /etc/archiver/.env; set +a
uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py
uv sync                                      # install deps (resolves co-core from ./.wheelhouse)
uv run pytest                                # tests
uv run ruff check .                          # lint (also ruff format .)
uv run alembic upgrade head                  # apply migrations
uv run alembic revision --autogenerate -m "description"

# Pre-commit hooks (one-time per clone, then runs on each git commit):
uv run pre-commit install                    # install the hook
uv run pre-commit run --all-files            # manual sweep across the repo

# CI mirrors these checks; failing tests/lint locally also fails CI on push/PR.
```

## API & Change-Bus Surface

Routes, SDK wrappers, and the `info.changes` event contract: [docs/API.md](docs/API.md).
Rules holding across all of it:

- `X-API-Key` on every route; only `/health` and `/openapi.json` are open.
- List routes return `{items, has_more, limit, offset}`; `limit` default 100,
  max 500. Over-max is a 422, not a clamp.
- Bus payloads carry `schema_version: int`. Bump only on *incompatible* reshapes;
  additive fields are not a bump, and consumers must tolerate them.

## Conventions

**Commit Messages:**
```
#<number> [type]: <description>      # with issue
[type]: <description>                # without issue
```
Types: feat, fix, refactor, docs, test, chore.

**Changelog:** Update `CHANGELOG.md` at the repo root when a change
touches a **contract-visible path** — and only then. The trigger is
path-based, not intent-based; CI and the pre-push guard both enforce it
with the same regex:

```
^(alembic/versions/|src/api/routes/|src/api/schemas/|clients/python/)
```

What the regex covers and what it deliberately does not:
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

**Dashboard living docs:** each doc is scoped to what it actually documents —
update the one(s) the change touches, in the same commit. Failure to update an
applicable doc is a CR blocker. `docs/UI.md` covers templates, dashboard JS, and
routes; `docs/STYLE.md` covers styling. Which one a given change requires:
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

**Logging:**
```python
from src.core.logging import get_logger
logger = get_logger(__name__)
```
Entry points only: call `configure_logging()` once.

`ExecStartPre` steps in `deploy/archiver.service` write **plain text**, not JSON —
a journald consumer must tolerate that ([docs/CONVENTIONS.md](docs/CONVENTIONS.md)).

**Date & Time:** All UTC. ISO 8601: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (timestamps), `YYYY-MM-DD` (dates).

**General:**
- No inline module imports; all at file top. Ruff `PLC0415` enforces this in CI
  (archiver#97). Scope and exemptions: [docs/CONVENTIONS.md](docs/CONVENTIONS.md).
- Docstrings for public modules, classes, functions
- Test structure mirrors source (`src/foo.py` → `tests/test_foo.py`)
- Explicit imports only
- Small, focused functions
- Translated exceptions chain via `raise HTTPException(...) from e` (capture the source with `as e`). Ruff `B904` enforces this in CI.

**Error envelope:** Every non-2xx response uses one shape (`ErrorEnvelope`,
`src/api/errors.py`). Routes raise via `raise_envelope(...)` or `raise_422(...)`,
**never `HTTPException` directly**; always pass `source_exc=e` from inside
`except X as e:`. Shape, worked examples, and the `kind` vocabulary:
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

## Vocabulary

Data model identifiers (table names, FastAPI route paths, Redis Stream topics) stay verbatim — never rename casually. The current vocabulary:

- `InfoItem` (`info_items`) — semantic anchor + `rep_fields` bag
- `InfoSource` (`info_sources`) — physical layer; URL + `source_specs`
- `SourceRevision` (`source_revisions`) — content-addressed snapshot
- `InfoItemSource` (`info_item_sources`) — item↔source binding; one active primary
- `RepSpec` (`rep_specs`) — replication spec; `document` frozen once assigned
- `InfoItemRepSpec` (`info_item_rep_specs`) — effective-dated assignment + `public_url`
- `ChangesOutboxRow` (`changes_outbox`) — pending bus event awaiting publication

Per-entity contracts and invariants: [docs/SCHEMA.md](docs/SCHEMA.md). The
Phase 1–3a `InfoSpec` model is retired — no new `info_spec*` references.

## Agent Skills

Skills live in `skills/` (agentskills.io) and `.claude/skills/` (Claude Code). Local overrides in `skills/` shadow vendor submodules in `skills-vendor/`.

Full skill reference: `docs/SKILLS.md`. Cross-project search to the sister `watcher` and `notifier` indexes requires a per-instance `.claude/settings.local.json` (gitignored) — see "Linked Projects" in `docs/SKILLS.md`.

## SessionStart Hooks

`.claude/settings.json` wires the SocratiCode prefetch reminder. The once-per-day
`skills-vendor/` refresh is **suspended** — it auto-commits submodule bumps on
`main`, breaking the archiver#131 wave-A hold. Restore recipe + mechanics:
[docs/SKILLS.md](docs/SKILLS.md). Two footguns:

- `skills-submodule-update.sh` is a **symlink** into the vendored `managing-skills`
  scripts. **Never re-copy it** — a copy freezes at the version it was taken from.
- `.skills/doctor.sh` is a **committed real file**, not a symlink, so it survives a
  fresh `git worktree add` and a shallow CI clone (`bash .skills/doctor.sh --version`).

## Detail Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — full repository layout tree and the co-core acquisition wiring
- [docs/API.md](docs/API.md) — every HTTP route, its SDK wrapper, pagination, and the `info.changes` event contract
- [docs/SCHEMA.md](docs/SCHEMA.md) — per-table contracts and invariants for the five registry tables
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — wheelhouse reproducibility, dev-server internals, full env-var reference
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — changelog trigger, journald logging contract, error-envelope examples
- [docs/SKILLS.md](docs/SKILLS.md) — skill inventory, trigger table, SessionStart hook mechanics
- [docs/UI.md](docs/UI.md) — dashboard URL map, HTMX/Alpine patterns, per-page route inventory (large — open one section)
- [docs/STYLE.md](docs/STYLE.md) — dashboard theming, design tokens, component classes, accessibility
