# archiver — Agent Guidelines

Be terse. Prefer fragments over full sentences. Skip filler and preamble. Sacrifice grammar for density. Lead with the answer or action.

## Project Overview

Central registry + authoring service for the Cannabis Observer information layer. FastAPI + PostgreSQL. Owns five registry tables (`info_items`, `info_sources`, `source_revisions`, `rep_specs`, `info_item_rep_specs`) plus one Item↔X join table (`info_item_sources`). Dashboard adds two more: `app_users` (upserted from proxy headers) and `api_keys` (hashed key store). Consumed by the (forthcoming) Replicator and external callers via the `archiver-client` Python SDK — **not** by Watcher, whose edge is bus-only in both directions (archiver#142 / watcher#254). Produces `info.changes`, `info.registry`, and `content.replicate` (archiver#169) via an internal outbox publisher, and consumes three streams — `content.revisions` (archiver#139), `info.watch-status` (archiver#151), and `content.artifacts` (archiver#170). **Never `content.blobs`**: that role boundary is unqualified, with no read-only exception.

**Archiver makes no outbound HTTP call to Watcher (archiver#142).** The edge is bus-only in both directions: policy goes out on `info.registry`, status comes back on `info.watch-status`. There is no Watcher SDK, no `WATCHER_BASE_URL`, and no provisioning push. Do not reintroduce one — a synchronous call to a sibling service is the coupling the decoupling epic (#137) exists to remove.

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

Tool-by-goal map and the `ToolSearch` prefetch query: [docs/SKILLS.md](docs/SKILLS.md).

## Architecture

Full layout tree: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The boundaries an
`ls` will not explain:

- `src/api/` is the HTTP contract, `src/dashboard/` the HTMX admin UI, `src/core/`
  the domain. The dashboard **clamps** paginated `limit`/`offset` where the API
  **422s** — deliberate, see [docs/UI.md](docs/UI.md).
- `alembic/` is scoped to the `information` schema *inside* the archiver database.
- `clients/python/` is the one vendored SDK — regenerated from a committed
  OpenAPI snapshot, gated by the CI `client-drift` job; never hand-edit
  `generated/`. It was two until archiver#142 retired the Watcher client along
  with every outbound HTTP call to Watcher.
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
(see [docs/BUS.md](docs/BUS.md)). `src/core/logging.py` is service-local — Watcher
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

**Four variables carry safety rules; the rest are reference
([docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).**

- `TEST_DATABASE_URL` — **must not equal** `ARCHIVER_DATABASE_URL` or
  `DATABASE_URL`; teardown drops the entire `information` schema. Name must end in
  `_test`.
- `ARCHIVER_ALLOW_PRODUCTION_DB` — only `deploy/archiver.service` sets it. **Never
  put it in an env file** — that re-opens the hole for every process that sources
  them.
- `ARCHIVER_BUS_CONSUMER` — same rule, same reason; gates joining the
  `archiver.revisions` consumer group.
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

Routes and SDK wrappers: [docs/API.md](docs/API.md); the bus contracts and the
`info.changes` payloads: [docs/BUS.md](docs/BUS.md).
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

**Dashboard living docs:** update the doc a change touches in the same commit —
PAGES.md (templates, routes), COMPONENTS.md (dashboard JS), UI.md (shared
patterns), STYLE.md (styling). Failing to is a CR blocker; per-trigger detail in
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

- `InfoItem` (`info_items`) — semantic anchor + `rep_fields`, `watch_spec`, `watch_active`
- `InfoSource` (`info_sources`) — physical layer; URL + `source_specs`
- `SourceRevision` (`source_revisions`) — content-addressed snapshot
- `InfoItemSource` (`info_item_sources`) — item↔source binding; one active primary
- `RepSpec` (`rep_specs`) — replication spec; `document` frozen once assigned
- `InfoItemRepSpec` (`info_item_rep_specs`) — effective-dated assignment + `public_url`
- `ChangesOutboxRow` (`changes_outbox`) — pending bus event awaiting publication
- `RevokedInfoItem` (`revoked_info_items`) — deleted InfoItem's identity + final generation; feeds the snapshot's tombstone republish
- `WatchStatus` (`watch_status`) — local LWW cache of `info.watch-status`; what the watched-item panel renders from. Reported by Watcher, never locally verified
- `ReplicationCommand` (`replication_commands`) — one `content.replicate` occasion: the MUST-2 mapping, the reaper's queue, and where a *skipped* replication is recorded rather than lost
- `BusTailCursor` (`bus_tail_cursors`) — resume point per groupless tail, so a restart is a delta not a `0-0` replay

Per-entity contracts and invariants: [docs/SCHEMA.md](docs/SCHEMA.md). The
Phase 1–3a `InfoSpec` model is retired — no new `info_spec*` references.

## Agent Skills

Skills live in `skills/` (agentskills.io) and `.claude/skills/` (Claude Code). Local overrides in `skills/` shadow vendor submodules in `skills-vendor/`.

Cross-project search to the sister `watcher` and `notifier` indexes requires a per-instance `.claude/settings.local.json` (gitignored) — see "Linked Projects" in [docs/SKILLS.md](docs/SKILLS.md).

## SessionStart Hooks

`.claude/settings.json` wires the SocratiCode prefetch reminder and the
once-per-day `skills-vendor/` refresh. Both halves of a hook are load-bearing: a
script in `.claude/hooks/` that `settings.json` does not name never runs and
looks identical to one that works — `tests/scripts/test_claude_hooks_registered.py`
fails on the missing half. Never re-copy the `skills-submodule-update.sh`
symlink, never turn the committed `.skills/doctor.sh` into one, and never
un-wire the hook to hold a submodule — use `.skills/skills-pin`. Why each, plus
the hook's gates and log paths: [docs/SKILLS.md](docs/SKILLS.md).

## Detail Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — full repository layout tree and the co-core acquisition wiring
- [docs/API.md](docs/API.md) — every HTTP route, its SDK wrapper, and pagination
- [docs/BUS.md](docs/BUS.md) — the outbox producer, the three published streams, and the three consumed
- [docs/SCHEMA.md](docs/SCHEMA.md) — per-table contracts and invariants for the five registry tables
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — wheelhouse reproducibility, dev-server internals, full env-var reference
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — changelog trigger, journald logging contract, error-envelope examples
- [docs/SKILLS.md](docs/SKILLS.md) — skill inventory, trigger table, SessionStart hook mechanics
- The five dashboard docs — [docs/UI.md](docs/UI.md) URL map, auth, HTMX, detail-screen conventions; [docs/PAGES.md](docs/PAGES.md) per-page/route inventory; [docs/INFO_ITEM_DETAIL.md](docs/INFO_ITEM_DETAIL.md) the InfoItem hub screen — its five sections, partials, swap targets; [docs/COMPONENTS.md](docs/COMPONENTS.md) Alpine catalogue; [docs/STYLE.md](docs/STYLE.md) theming, tokens, component classes, accessibility
