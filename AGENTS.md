# archiver — Agent Guidelines

Be terse. Prefer fragments over full sentences. Skip filler and preamble. Sacrifice grammar for density. Lead with the answer or action.

## Project Overview

Central registry + authoring service for the Cannabis Observer information layer. FastAPI + PostgreSQL. Owns five registry tables (`info_items`, `info_sources`, `source_revisions`, `rep_specs`, `info_item_rep_specs`) plus two Item↔X join tables (`info_item_sources`, `info_item_source_revisions`). Dashboard adds two more: `app_users` (upserted from proxy headers) and `api_keys` (hashed key store). Consumed by Watcher and (forthcoming) Replicator via the `archiver-client` Python SDK; produces a Redis Stream (`info.changes`) via an internal outbox publisher.

Phase 4 (the current model — Archiver v2) shipped 2026-05-09 on branch `phase-4-archiver-v2`. Design + implementation plan:

- `docs/plans/2026-05-08-archiver-v2-architecture-design.md`
- `docs/plans/2026-05-08-phase-4-archiver-v2-implementation.md`

The earlier `InfoItem ↔ InfoSpec` Phase 1–3a model is gone — `info_specs` table dropped, `info_spec_schema` package deleted, all SDK methods retired. The 2026-05-06 trajectory research doc remains as historical context.

## Development Methodology

TDD required. Red → Green → Refactor. No production code without a failing test first.

## Environment & Tooling

Python ≥3.12, uv, pytest, ruff. Postgres on the local VM (shared instance with watcher and notifier; archiver owns its own database).

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

## Project Layout

```
src/api/                       FastAPI routes, deps, schemas, serializers
src/dashboard/                 HTML/HTMX admin dashboard (routes/, templates/, static/, deps.py)
src/core/                      Domain logic
  models/                      ORM (info_item, info_source, source_revision,
                               info_item_source, info_item_source_revision,
                               rep_spec, info_item_rep_spec, changes_outbox)
  source_spec_schema/          SourceSpec JSON Schema v1 + validator
  rep_spec_schema/             RepSpec envelope + per-provider sub-schemas
                               (providers/{gcs,gdrive,ia}/v1.json)
  rep_fields_schema/           rep_fields meta-schema + validator
  changes/                     Outbox publisher (background asyncio task) +
                               typed Pydantic event payloads
  tools/                       Authoring helpers (assign_rep_spec, bind_revision,
                               resolve_rep_fields, preview_extraction, etc.)
  fetchers/, extractors/,
  simhash.py, extraction_defaults.py, logging.py
                               Mirrored from watcher (see "Mirrored content-acquisition code")
  url_canonicalization.py      Write-time URL normalization for info_sources
clients/python/                archiver_client SDK v3.x (generated + hand-written wrappers)
clients/watcher-python/        watcher_client SDK — Archiver adapter for the Watcher service
                               (httpx-based; wraps provision, patch, get, check-now, list-revisions)
                               Regen: bash clients/watcher-python/scripts/regen.sh
alembic/                       Migration root (information schema scoped within the archiver database)
tests/                         Mirrors src/ structure; tests/integration/ for cross-component flows
                               (HTTP + DB + bus); tests/api/ for single-route HTTP behavior
scripts/                       dump_openapi.py + smoke_phase4.sh +
                               check_changelog_on_push.sh (pre-push guard;
                               wired via .pre-commit-config.yaml)
deploy/                        Systemd unit (archiver.service)
docs/                          Reference docs (SKILLS) + plans/ + research/
skills/                        Agent skills (committed overrides + symlinks → skills-vendor/)
skills-vendor/                 Git submodules for external skill repos
.claude/skills/                Claude Code skill discovery (symlinks → ../../skills/<name>)
.github/workflows/             CI — lint job (ruff check + ruff format --check),
                               test job (Postgres service container, alembic upgrade,
                               pytest), and changelog job (feat/fix changes must
                               touch CHANGELOG.md; opt out via `no-changelog` PR
                               label). Triggers on push/PR to main.
.pre-commit-config.yaml        ruff check + ruff format + standard pre-commit-hooks
                               (pre-commit stage), plus a pre-push guard
                               (scripts/check_changelog_on_push.sh) that mirrors
                               the CI changelog check before the push leaves the
                               clone. Run `uv run pre-commit install` once per
                               clone — installs both pre-commit and pre-push
                               hook types via default_install_hook_types.
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
set -a
[ -f /etc/archiver/.env ] && . /etc/archiver/.env
[ -f .env ] && . .env
set +a
uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8021 --reload
```

## Environment Files

Two env files load in order (later overrides earlier):

1. `/etc/archiver/.env` — production secrets (`ARCHIVER_DATABASE_URL`, `ARCHIVER_API_KEY`). Persistent, managed manually on the VM.
2. `.env` (repo root, git-ignored) — dev/agent secrets (`TEST_DATABASE_URL`, `GH_TOKEN`). Never commit.

```bash
set -a
[ -f /etc/archiver/.env ] && . /etc/archiver/.env
[ -f .env ] && . .env
set +a
```

> Use `set -a; . <file>; set +a` (POSIX-portable source via `.`) rather than `export $(cat <file> | xargs)`. The xargs form silently breaks for values containing spaces, quotes, newlines, or embedded `=` — and produces hard-to-diagnose failures later when those env vars are read.

**Key variables:**
- `ARCHIVER_DATABASE_URL` — PostgreSQL connection (falls back to `DATABASE_URL`).
- `ARCHIVER_API_KEY` — convenience alias for a registered API key value (SHA-256 hash stored in `api_keys` table). The service does **not** read this env var for auth — `require_api_key` does a DB hash lookup. Used by `smoke_phase4.sh` and manual `curl` calls. The value must match a key registered via the dashboard Settings page.
- `TEST_DATABASE_URL` — separate test database. **Must not equal `ARCHIVER_DATABASE_URL` or `DATABASE_URL`** — teardown drops the entire `information` schema. Convention: database name should include `_test` (e.g. `archiver_test`). `conftest.py` asserts this at collection time and fails fast if violated.
- `ARCHIVER_REDIS_URL` — *optional*. When set, enables the outbox publisher background task that drains `changes_outbox` rows to the `info.changes` Redis Stream. Unset → publisher is silently disabled (degraded mode for local dev without Redis).
- `ARCHIVER_PUBLIC_BASE_URL` — *optional*. Public-facing base URL of this Archiver instance (e.g. `https://archiver.example.com`). When set, InfoItem API responses include `dashboard_url` pointing to the dashboard detail page (`{ARCHIVER_PUBLIC_BASE_URL}/info-items/{id}`). Unset → `dashboard_url` is `null`. Set this to the URL end-users open in a browser, distinct from any internal service-to-service address. Set in `/etc/archiver/.env` on the VM.
- `WATCHER_BASE_URL` — *optional*. Base URL of the sibling Watcher service for **service-to-service API calls** (e.g. `http://localhost:8000`). When set (together with `WATCHER_API_KEY`), the Archiver provisions WatchedItems on InfoItem create and patches them on primary-source swap. Unset → Watcher integration disabled; `watcher_item_id` stays `NULL` on all InfoItems. **Do not use a public proxy URL here on the same VM** — hairpin NAT means the proxy URL won't route from within the VM; use `http://localhost:<port>` instead.
- `WATCHER_PUBLIC_BASE_URL` — *optional*. Public-facing base URL of the Watcher service for **browser deeplinks** (e.g. `https://watcher.exe.xyz:8000`). When set, the dashboard "View in Watcher ↗" link uses this URL instead of `WATCHER_BASE_URL`. Unset → falls back to `WATCHER_BASE_URL`. Set in `/etc/archiver/.env`. Analogous to `ARCHIVER_PUBLIC_BASE_URL`.
- `WATCHER_API_KEY` — *optional*. API key sent as `X-API-Key` to the Watcher service. Store in `/etc/archiver/.env`. Required when `WATCHER_BASE_URL` is set.
- `WATCHER_CACHE_DIR`, `WATCHER_CACHE_TTL_SECONDS`, `WATCHER_CACHE_SWEEP_INTERVAL_SECONDS` — Watcher-side, not Archiver-side; documented here because the `content_cache_uri` lifecycle protocol they govern is a registry contract (see design doc Section 2).

## Authoring tools + assignment endpoints (v2)

The Archiver exposes authoring helpers under `/api/v1/tools/*` and mutating sub-resource routes under `/api/v1/info-items/{id}/*`. All routes use `X-API-Key` auth (only `/health` and `/openapi.json` are open). Each route has an ergonomic SDK wrapper on `ArchiverClient` (v4.x; see [CHANGELOG.md](CHANGELOG.md) for version history).

**Domain endpoints (v4.1+):**

| Endpoint | HTTP | SDK method |
|---|---|---|
| List Domains | `GET /domains?is_active=&archived=&limit=&offset=` | `list_domains(is_active=None, archived=None, limit=None, offset=None)` |
| Get a Domain | `GET /domains/{name}` | `get_domain(name)` |
| Upsert a Domain | `PATCH /domains/{name}` | `upsert_domain(name, notes=None, is_active=None)` |
| Delete a Domain | `DELETE /domains/{name}` | `delete_domain(name)` (409 if sources exist) |
| Archive a Domain | `POST /domains/{name}/archive` | `archive_domain(name)` |
| Restore a Domain | `POST /domains/{name}/restore` | `restore_domain(name)` |

`InfoSourceOut` gains `domain_name: str | None` (hostname auto-set from URL at create time).
`GET /info-sources` gains `?domain_name=` filter.

**Read-only tools:**

| Tool | HTTP | SDK method |
|---|---|---|
| `validate_source_spec` | `POST /tools/validate-source-spec` | `validate_source_spec(doc)` |
| `validate_rep_spec` | `POST /tools/validate-rep-spec` | `validate_rep_spec(doc)` |
| `validate_rep_fields` | `POST /tools/validate-rep-fields` | `validate_rep_fields(bag, required_fields=None)` |
| `resolve_rep_fields` | `POST /tools/resolve-rep-fields` | `resolve_rep_fields(bag)` |
| `find_info_item` | `GET /tools/find-info-items?q=…` | `find_info_item(query, limit=20)` |
| `fetch_and_render` | `POST /tools/fetch-and-render` | `fetch_and_render(url)` |
| `preview_extraction` | `POST /tools/preview-extraction` | `preview_extraction(url, source_spec)` |
| `propose_selectors` | `POST /tools/propose-selectors` | `propose_selectors(url, description, top_k=5)` |

**Mutating endpoints:**

| Endpoint | HTTP | SDK method |
|---|---|---|
| Atomic InfoItem create | `POST /info-items` | `create_info_item(name, ..., initial_url=None, initial_source_specs=None, initial_rep_spec_assignments=None, rep_fields=None)` |
| Bind a Source to an Item | `POST /info-items/{id}/info-sources` | `add_info_source(info_item_id, info_source_id)` |
| Deactivate a source binding | `DELETE /info-items/{id}/info-sources/{source_id}` | `deactivate_info_source_binding(info_item_id, info_source_id)` |
| Author a top-level InfoSource | `POST /info-sources` | `create_info_source(url, source_specs)` |
| Update InfoSource specs | `PATCH /info-sources/{id}/source-specs` | `update_info_source_specs(info_source_id, source_specs)` |
| Get an InfoSource | `GET /info-sources/{id}` | `get_info_source(id)` |
| List InfoSources (filter by URL, paginated) | `GET /info-sources?url=…&limit=&offset=` | `list_info_sources(url=None, limit=None, offset=None)` |
| Author a RepSpec | `POST /rep-specs` | `create_rep_spec(provider, name, document)` |
| Get a RepSpec | `GET /rep-specs/{id}` | `get_rep_spec(id)` |
| List RepSpecs (filter by provider, paginated) | `GET /rep-specs?provider=…&limit=&offset=` | `list_rep_specs(provider=None, limit=None, offset=None)` |
| Assign a RepSpec | `POST /info-items/{id}/rep-spec-assignments` | `assign_rep_spec(info_item_id, rep_spec_id, activated_at=None)` |
| Deactivate an assignment | `DELETE /info-items/{id}/rep-spec-assignments/{aid}` | `deactivate_rep_spec_assignment(info_item_id, assignment_id)` |
| Public-URL writeback | `PATCH /info-items/{id}/rep-spec-assignments/{aid}` | `set_public_url(info_item_id, assignment_id, public_url)` |
| Bind a SourceRevision | `POST /info-items/{id}/source-revisions` | `bind_revision(info_item_id, source_revision_id, bound_at=None)` |
| Record a SourceRevision (idempotent) | `POST /source-revisions` | `post_source_revision(...)` |
| Clear cache fields | `PATCH /source-revisions/{id}` | `patch_source_revision_cache(id, content_cache_uri=None, content_cache_expires_at=None)` |

`POST /info-sources` accepts `{url, source_specs}`. Multiple InfoSources at the same URL are valid. Returns 422 on invalid URL or spec validation failure.

**Pagination:** `GET /info-items`, `GET /info-sources`, and `GET /rep-specs` return a `Page` envelope — `{items, has_more, limit, offset}`. All accept `limit` (default 100, max 500) and `offset` (default 0) query params. Ordering is stable: `(created_at, id)`. `has_more` is computed via a `limit+1` probe — no total count. SDK methods `list_info_items` / `list_info_sources` / `list_rep_specs` return `PageInfoItemOut` / `PageInfoSourceOut` / `PageRepSpecOut`; pass `limit`/`offset` to forward to the server.

**SDK version history:** see [CHANGELOG.md](CHANGELOG.md).

**Change-bus producer:** Writes rows to `information.changes_outbox` in the same transaction; the publisher background task drains the outbox to the Redis Stream `info.changes`. Publisher only starts when `ARCHIVER_REDIS_URL` is set. Two event types:

| Event type | Trigger | Payload type |
|---|---|---|
| `source_revision_captured` | New `SourceRevision` insert (`POST /source-revisions` on non-idempotent path) | `src.core.changes.payloads.SourceRevisionCapturedEvent` |
| `info_item_primary_changed` | New active `InfoItemSource` binding created (`POST /info-items/{id}/info-sources`) | `src.core.changes.payloads.InfoItemPrimaryChangedEvent` |

`source_revision_captured` schema_version is now **2** — `bindings[*].role` field removed. Consumers must branch on `schema_version` before destructuring. `info_item_primary_changed` carries `old_info_source_id` (null on first assignment, non-null on succession) and `new_info_source_id`. Subscribers use it to discover URL succession.

**Bus event versioning convention.** Every bus event payload carries
`schema_version: int` (start at `1`, monotonic). Bump only on *incompatible*
reshapes — field removal, type change, semantic redefinition. Additive
fields are not a bump; consumers must tolerate them. Apply the same
convention to any future event type added to `info.changes`.

Consumer rule: parsers must accept extra fields. With a Pydantic model,
use `ConfigDict(extra="ignore")` (or `model_construct`) on the
consumer-side mirror so additive producer fields do not raise
`ValidationError`. Branch on `schema_version` before destructuring when
the version is one the consumer recognises differently.

**Smoke:** `bash scripts/smoke_phase4.sh` exercises the v2 authoring loop end-to-end against the dev server (port 8021). Step 9 (Redis stream check) is skipped unless `ARCHIVER_REDIS_URL` is set.

## Agent Skills

Skills live in `skills/` (agentskills.io) and `.claude/skills/` (Claude Code). Local overrides in `skills/` shadow vendor submodules in `skills-vendor/`.

| Skill | Triggers / when to invoke |
|---|---|
| `reviewing-code-python-fastapi` | CR, code review |
| `reviewing-architecture` | AR, architecture review |
| `shipping-work-python-fastapi` | ship it, push GH, close GH, wrap up |
| `brainstorming` | brainstorm, design this, let's design |
| `writing-plans` | write plan, implementation plan |
| `writing-skills` | write skill, new skill, author skill |
| `systematic-debugging` | any bug, test failure, unexpected behavior |
| `verification-before-completion` | before any completion claim or commit |
| `test-driven-development` | before writing implementation code |
| `executing-plans` | execute approved plan from docs/plans/ |
| `subagent-driven-development` | dispatch agents for plan execution |
| `dispatching-parallel-agents` | 2+ independent tasks in parallel |
| `using-git-worktrees` | feature work needing isolation (dev port 8021) |
| `finishing-a-development-branch` | merge/ship a feature branch |
| `requesting-code-review` / `receiving-code-review` | CR handoff between agents |
| `managing-skills` | add skill repo, manage external skills |
| `orchestrating-issue-backlog` | backlog grooming, issue triage |
| `using-superpowers` | meta — when to invoke superpowers skills |
| `socraticode` (codebase MCP) | see **Code Exploration Policy** above |

Full skill reference: `docs/SKILLS.md`. Cross-project search to the sister `watcher` and `notifier` indexes requires a per-instance `.claude/settings.local.json` (gitignored) — see "Linked Projects" in `docs/SKILLS.md`.

## SessionStart Hooks

`.claude/settings.json` wires two `SessionStart` hooks (see `.claude/hooks/`):

- `socraticode-reminder.sh` — prints the deferred-tool prefetch query for SocratiCode MCP tools.
- `skills-submodule-update.sh` — once-per-day refresh of `skills-vendor/gregoryfoster-skills` and `skills-vendor/obra-superpowers`. Lock file: `.git/skills-update-YYYYMMDD`. Log: `.git/skills-update.log` (auto-rotates at 64 KiB → last 200 lines). **Auto-commits only on `main`** with `chore: update skills submodules` — feature branches fetch but don't commit. Network failures are logged and don't block session start. Mirror of watcher's hook (CannObserv/watcher#153 → CannObserv/archiver#8).

## Common Commands

```bash
uv sync                                      # install deps
uv run pytest                                # tests
uv run ruff check .                          # lint (also ruff format .)
uv run alembic upgrade head                  # apply migrations
uv run alembic revision --autogenerate -m "description"

# Pre-commit hooks (one-time per clone, then runs on each git commit):
uv run pre-commit install                    # install the hook
uv run pre-commit run --all-files            # manual sweep across the repo

# CI mirrors these checks; failing tests/lint locally also fails CI on push/PR.
```

## Conventions

**Commit Messages:**
```
#<number> [type]: <description>      # with issue
[type]: <description>                # without issue
```
Types: feat, fix, refactor, docs, test, chore.

**Changelog:** Update `CHANGELOG.md` at the repo root whenever a relevant
change merges to `main` — new endpoints, new SDK methods or types,
behaviour changes, breaking changes, public-surface fixes. Skip for
internal refactors, test-only changes, and docs-only changes. Tag each
entry `[service]`, `[sdk]`, or `[both]` per the format header in
`CHANGELOG.md`. The SDK README links here; do not maintain a second
changelog there.

**Dashboard living docs:** `docs/STYLE.md` and `docs/UI.md` must be updated in the same commit as any change to `src/dashboard/static/dashboard.css`, a JS module under `src/dashboard/static/`, a Jinja2 template in `src/dashboard/templates/`, or a new dashboard route. Failure to update them is a CR blocker.

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
- Translated exceptions chain via `raise HTTPException(...) from e` (capture the source with `as e`). Ruff `B904` enforces this in CI.

**Error envelope:** Every non-2xx response uses one shape, defined by
`ErrorEnvelope` in `src/api/errors.py`:

```json
{"detail": {"kind": "lookup", "message": "...", "errors": [...], "data": {...}}}
```

Routes raise via `raise_envelope(status, kind, message, ...)` or `raise_422(...)`
(in `src/api/errors.py`), never via `HTTPException` directly. The global
exception handlers in `register_error_handlers(app)` wrap any FastAPI-raised
HTTPException (unmatched route 404, 405) or uncaught Exception (500) into the
envelope. See archiver#15.

Examples:

```python
from src.api.errors import FieldError, raise_422, raise_envelope

# Plain lookup
raise_envelope(404, "lookup", "InfoItem not found")

# Schema-validator translation (preserve cause for ruff B904)
try:
    spec = await create_rep_spec(session, ...)
except InvalidRepSpecError as e:
    raise_422("invalid rep_spec", errors=e.errors, source_exc=e)

# Conflict with structured payload
raise_envelope(409, "conflict", "duplicate URL",
               data={"existing_info_source_id": str(existing.id)},
               source_exc=e)

# Domain error with field-level code
raise_envelope(422, "domain", "info_item_id is not a valid ULID",
               errors=[FieldError(path="/info_item_id",
                                  message="not a valid ULID",
                                  code="invalid_ulid")],
               source_exc=e)
```

`kind` is one of: `body` (Pydantic body validation), `schema` (envelope/JSON-schema
validators), `domain` (typed core-tool errors, malformed ULIDs, target unreachable),
`lookup` (404), `conflict` (409), `auth` (401/403), `unimplemented` (501/405),
`server` (5xx).  Always pass `source_exc=e` from inside `except X as e:` blocks.

## Vocabulary

Data model identifiers (table names, FastAPI route paths, Redis Stream topics) stay verbatim — never rename casually. The current vocabulary:

- **`InfoItem`** (`info_items`) — semantic anchor; carries domain meaning + `rep_fields` JSONB bag.
  `watcher_item_id VARCHAR(50)` — nullable; stores the Watcher-allocated WatchedItem ID once
  provisioned. `NULL` means not yet watched (use "Begin watching" in the dashboard or wait for
  the next `create_info_item` call with Watcher configured).
  **Fetch group invariant:** exactly one URL is fetched (the primary binding's InfoSource URL) and
  exactly one content-kind is produced (HTML/text or JSON). All specs in the bound InfoSource's
  `source_specs` list are evaluated against the same fetched bytes (no chaining off primary's
  extracted output). All specs in a list must share a content-kind family
  (`{css,xpath,regex,full_page}` ≠ `{jsonpath}`); see `src/core/source_spec_schema/families.py`.
- **`InfoSource`** (`info_sources`) — physical layer. `url TEXT NOT NULL` (non-unique — multiple
  InfoSources may share the same URL for different extraction strategies). `source_specs JSONB`
  (mutable array): first element is the primary extraction spec; subsequent elements are
  cross-check alternatives for selector-rot detection. Each spec: `{schema_version, extraction,
  fingerprint}` — no `target` section; URL is on the InfoSource directly.
- **`SourceRevision`** (`source_revisions`) — content-addressed snapshot. Identity is `(info_source_id, content_fingerprint)`; fingerprint is always `sha256:<hex>`.
- **`InfoItemSource`** (`info_item_sources`) — operator-declared item↔source binding. No `role`
  column — every binding is a primary binding. Two distinct states:
  - **Current primary** — the one active row (`deactivated_at IS NULL`). Enforced one-per-InfoItem
    by partial unique index `uq_info_item_sources_active`. Its InfoSource URL is what Watcher
    fetches each tick.
  - **Previous primary** — a deactivated row (`deactivated_at IS NOT NULL`). Preserved indefinitely
    as succession history. Watcher may continue watching previous primaries for unanticipated
    changes.

- **`InfoItemSourceRevision`** (`info_item_source_revisions`) — append-only history of which revisions an item has been pinned to.
- **`RepSpec`** (`rep_specs`) — replication specification. JSONB `document` carries provider config, `credentials_alias`, `path_template`, `required_fields`. Per-provider sub-schemas under `src/core/rep_spec_schema/providers/`.
- **`InfoItemRepSpec`** (`info_item_rep_specs`) — effective-dated assignment + `public_url` writeback target.
- **`ChangesOutboxRow`** (`changes_outbox`) — pending change-bus event awaiting publication.

The Phase 1–3a `InfoSpec` model has been retired. Avoid any new references to `info_spec*` outside historical alembic migration files. The "Archiver" rename was service-name-only; `info_*` table prefix and `information` schema preserved per design decision.
