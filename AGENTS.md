# archiver — Agent Guidelines

Be terse. Prefer fragments over full sentences. Skip filler and preamble. Sacrifice grammar for density. Lead with the answer or action.

## Project Overview

Canonical registry of **Information Items** and **Information Source Specifications** (InfoSpecs) for the Cannabis Observer ecosystem. FastAPI + PostgreSQL service consumed by Watcher and (forthcoming) Replicator via the `archiver-client` Python SDK.

Trajectory anchor: `docs/research/2026-05-06-archiver-information-model.md` describes the eventual evolution to an `InfoSource` + `SourceRevision` content-addressed model. Current state implements the Phase 1–3a `InfoItem ↔ InfoSpec` model.

## Development Methodology

TDD required. Red → Green → Refactor. No production code without a failing test first.

## Environment & Tooling

Python ≥3.12, uv, pytest, ruff. Postgres on the local VM (shared instance with watcher and notifier; archiver owns its own database).

## Project Layout

```
src/api/         FastAPI routes, deps, schemas, serializers
src/core/        Domain — models, tools, info_spec_schema, plus mirrored content-acquisition primitives
clients/python/  archiver_client SDK (generated + hand-written wrappers)
alembic/         Migration root (information schema scoped within the archiver database)
tests/           Mirrors src/ structure
scripts/         dump_openapi.py + smoke_phase3a.sh
deploy/          Systemd unit (archiver.service)
docs/            Reference docs + plans/ + research/
```

## Mirrored content-acquisition code

These modules are **mirrors** of watcher's `src/core/` — when changing them here, mirror to watcher AND when watcher changes them, mirror here. (Notifier-style discipline. Drift acceptable for now; revisit if Replicator joins and fingerprint parity becomes load-bearing.)

- `src/core/fetchers/{base,http}.py`
- `src/core/extractors/{base,html,csv_excel,pdf}.py`
- `src/core/simhash.py`
- `src/core/extraction_defaults.py`
- `src/core/logging.py`

## Infrastructure

| Service | Port | Managed by |
|---|---|---|
| Archiver (live) | 8020 | `systemctl` (`archiver.service`) |
| Archiver (dev) | 8021 | manual uvicorn |

The exe.dev proxy forwards 3000–9999. Dev server reachable at `https://watcher.exe.xyz:8021/` (the host is shared with the watcher VM).

## Server Lifecycle

**Port 8020 belongs to systemd. Never start uvicorn manually on 8020.**

After committing to `main`: `sudo systemctl restart archiver`. After DB model changes: `uv run alembic upgrade head` then restart. Logs: `sudo journalctl -u archiver -f`.

Dev server (port 8021):

```bash
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8021 --reload
```

## Environment Files

Two env files load in order (later overrides earlier):

1. `/etc/archiver/.env` — production secrets (`ARCHIVER_DATABASE_URL`, `ARCHIVER_API_KEY`). Persistent, managed manually on the VM.
2. `.env` (repo root, git-ignored) — dev/agent secrets (`TEST_DATABASE_URL`, `GH_TOKEN`). Never commit.

```bash
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
```

**Key variables:**
- `ARCHIVER_DATABASE_URL` — PostgreSQL connection (falls back to `DATABASE_URL`)
- `ARCHIVER_API_KEY` — required X-API-Key for all routes outside `/healthz` and `/openapi.json`
- `TEST_DATABASE_URL` — separate test DB

## Authoring tools (Phase 3a)

The Archiver service exposes authoring helpers under `/api/v1/tools/*`. Same `X-API-Key` auth as CRUD. Each route has an ergonomic SDK wrapper on `ArchiverClient`.

| Tool | HTTP | SDK method | Use when |
|---|---|---|---|
| `validate_info_spec` | `POST /tools/validate-info-spec` | `validate_info_spec(doc)` | Schema-validate a candidate InfoSpec. |
| `find_info_item` | `GET /tools/find-info-items?q=…` | `find_info_item(query, limit=20)` | Dedupe before creating a new InfoItem. |
| `fetch_and_render` | `POST /tools/fetch-and-render` | `fetch_and_render(url)` | Inspect what the extractor will see. HTTP-only in v1. |
| `preview_extraction` | `POST /tools/preview-extraction` | `preview_extraction(url, doc)` | Dry-run validate + fetch + extract + fingerprint. |
| `propose_selectors` | `POST /tools/propose-selectors` | `propose_selectors(url, description, top_k=5)` | Heuristic CSS selector ranking. |
| `create_info_item` (atomic) | `POST /info-items` w/ `initial_info_spec` | `create_info_item(..., initial_info_spec=doc)` | Mutating. Atomically create InfoItem + primary InfoSpec. |

Smoke: `bash scripts/smoke_phase3a.sh` exercises the authoring loop end-to-end against the live service.

## Common Commands

```bash
uv sync                                      # install deps
uv run pytest                                # tests
uv run ruff check .                          # lint
uv run alembic upgrade head                  # apply migrations
uv run alembic revision --autogenerate -m "description"
```

## Conventions

**Commit Messages:**
```
#<number> [type]: <description>      # with issue
[type]: <description>                # without issue
```
Types: feat, fix, refactor, docs, test, chore.

**Logging:**
```python
from src.core.logging import get_logger
logger = get_logger(__name__)
```
Entry points only: call `configure_logging()` once.

**Date & Time:** All UTC. ISO 8601: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (timestamps), `YYYY-MM-DD` (dates).

**General:**
- No inline module imports; all at file top
- Docstrings for public modules, classes, functions
- Test structure mirrors source (`src/foo.py` → `tests/test_foo.py`)
- Explicit imports only
- Small, focused functions

## Vocabulary

Terminology preserved from the original Information service rename — the data model identifiers (`InfoItem`, `info_item_id`, `InfoSpec`, `info_spec_id`, table names, route paths, stream topics) stay verbatim. The "Archiver" rename is service-name-only. The `InfoSource` / `SourceSpec` / `SourceRevision` evolution lives in `docs/research/2026-05-06-archiver-information-model.md` — implement as a deliberate v2 effort, not in passing.
