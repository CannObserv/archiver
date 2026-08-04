# archiver — Agent Guidelines

Be terse. Prefer fragments over full sentences. Skip filler and preamble. Sacrifice grammar for density. Lead with the answer or action.

## Project Overview

Central registry + authoring service for the Cannabis Observer information layer. FastAPI + PostgreSQL. Owns five registry tables (`info_items`, `info_sources`, `source_revisions`, `rep_specs`, `info_item_rep_specs`) plus one Item↔X join table (`info_item_sources`; the `info_item_source_revisions` pin table was dropped in archiver#101). Dashboard adds two more: `app_users` (upserted from proxy headers) and `api_keys` (hashed key store). Consumed by Watcher and (forthcoming) Replicator via the `archiver-client` Python SDK; produces a Redis Stream (`info.changes`) via an internal outbox publisher.

Phase 4 (the current model — Archiver v2) shipped 2026-05-09 on branch `phase-4-archiver-v2`. Design + implementation plan:

- `docs/plans/2026-05-08-archiver-v2-architecture-design.md`
- `docs/plans/2026-05-08-phase-4-archiver-v2-implementation.md`

The earlier `InfoItem ↔ InfoSpec` Phase 1–3a model is gone — `info_specs` table dropped, `info_spec_schema` package deleted, all SDK methods retired. The 2026-05-06 trajectory research doc remains as historical context.

## Development Methodology

TDD required. Red → Green → Refactor. No production code without a failing test first.

## Environment & Tooling

Python ≥3.12, uv, pytest, ruff. Postgres on the local VM (shared instance with watcher and notifier; archiver owns its own database).

**cannobserv substrate (archiver#72/#75).** `co-core` + `co-core-aio` (the shared
Cannabis Observer core library — pure models/utils + async drivers) are declared
as plain floors and resolved from a local **wheelhouse**
(`./.wheelhouse`, gitignored) via `[tool.uv] find-links`, mirrored from the private
GCS index `gs://co-gcs-pypi` by `scripts/sync_wheelhouse.py`. This is Phase 0 of the
cluster-integration strategy — the precedent Watcher/Replicator follow. Populate the
wheelhouse before `uv sync`/`uv run`:

```bash
set -a; . /etc/archiver/.env; set +a   # GOOGLE_APPLICATION_CREDENTIALS=co-pypi-reader key
uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py
```

Reproducibility is `uv.lock` (pinned version + wheelhouse artifact), not the
wheelhouse contents. Upgrade: re-sync, then `uv lock --upgrade-package co-core`
(bump the floor if the minor moved). CI resolves the wheelhouse keyless via Workload
Identity Federation; the deploy unit syncs it in `ExecStartPre`. No git sources and
no `cannobserv`/`co-core-sync` (heavy google/trello deps). Archiver depends on
**`co-core[extract]`** + `co-core-aio` — the authoring tools use `co_core_aio.fetch`
(fetch) and `co_core.pure.extract` (extract + fingerprint); see "Content-acquisition
via co-core".

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
src/dashboard/                 HTML/HTMX admin dashboard (routes/, templates/, static/, deps.py,
                               pagination.py — shared clamped limit/offset dependency; see
                               docs/UI.md for why the dashboard clamps where the API 422s)
src/core/                      Domain logic
  models/                      ORM (info_item, info_source, source_revision,
                               info_item_source, rep_spec, info_item_rep_spec,
                               changes_outbox)
  source_spec_schema/          SourceSpec JSON Schema v1 + validator
  rep_spec_schema/             RepSpec envelope + per-provider sub-schemas
                               (providers/{gcs,gdrive,ia}/v1.json)
  rep_fields_schema/           rep_fields meta-schema + validator
  changes/                     Outbox publisher (background asyncio task) +
                               typed Pydantic event payloads
  tools/                       Authoring helpers (assign_rep_spec + lock_rep_specs,
                               update_rep_spec, resolve_rep_fields,
                               preview_extraction, etc.)
  logging.py                   Structured logging config (configure_logging at
                               entry points; still mirrored to watcher).
                               build_json_formatter() is the single source of
                               truth for the JSON field contract. Fetch +
                               extract + fingerprint now come from co-core — see
                               "Content-acquisition via co-core"
  log_config.json              uvicorn --log-config dictConfig — routes
                               uvicorn/.access/.error through build_json_formatter
                               so uvicorn lines match app logs (archiver#122);
                               each uvicorn logger also runs the
                               ColorMessageFilter to strip uvicorn's ANSI
                               color_message extra at the record source
                               (archiver#123 — filter on the loggers, not a sink);
                               wired into archiver.service + dev_server.sh
  url_canonicalization.py      Write-time URL normalization for info_sources
  db_safety.py                 Production-DB startup guard — refuses to serve a
                               database whose name lacks a _test/_dev suffix
                               unless ARCHIVER_ALLOW_PRODUCTION_DB=1 (set only
                               by deploy/archiver.service). Called from the
                               FastAPI lifespan; mirrored in scripts/dev_server.sh
                               and kept in step by tests/scripts/test_db_guard_parity.py
clients/python/                archiver_client SDK v3.x (generated + hand-written wrappers)
clients/watcher-python/        watcher_client SDK — Archiver adapter for the Watcher service
                               (httpx-based; wraps provision, patch, get, check-now, list-revisions)
                               Regen: bash clients/watcher-python/scripts/regen.sh
                               watcher-openapi.json: committed OpenAPI snapshot
                               (contract-of-record). CI `client-drift` job fails
                               if generated/ != regen-from-snapshot (catches the
                               #66 stale-client drift). Fix hand-edits: python
                               scripts/check_client_drift.py --write watcher; on
                               a real Watcher change re-run regen.sh (refreshes
                               snapshot + tree). The `client-drift` gate is
                               consistency-only; a daily on-VM systemd timer
                               (Layer C, #70) — check_watcher_live_drift.py +
                               watcher_live_drift_pr.sh — detects the snapshot
                               going stale vs LIVE Watcher (localhost:8000) and
                               opens a regen PR. See deploy/watcher-live-drift.*.
alembic/                       Migration root (information schema scoped within the archiver database)
tests/                         Mirrors src/ structure; tests/integration/ for cross-component flows
                               (HTTP + DB + bus); tests/api/ for single-route HTTP behavior;
                               tests/deploy/ asserts the installed systemd unit matches
                               deploy/ (skips when the unit is absent, so CI passes)
scripts/                       dump_openapi.py +
                               check_client_drift.py (regen vendored clients from
                               committed OpenAPI snapshots; diff vs generated/;
                               CI gate, see client-drift job) +
                               check_watcher_live_drift.py (Layer C #70: detect
                               snapshot stale vs LIVE Watcher) +
                               watcher_live_drift_pr.sh (timer remediation:
                               regen + open PR on live drift) +
                               ff_deploy_clone.sh (timer ExecStartPre: best-effort
                               fast-forward clean main to origin/main) +
                               check_changelog_on_push.sh (pre-push guard;
                               wired via .pre-commit-config.yaml) +
                               dev_server.sh (ONLY sanctioned way to start the
                               8021 dev server; refuses to resolve onto the
                               production DB — see "Server Lifecycle")
deploy/                        Systemd units: archiver.service +
                               watcher-live-drift.{service,timer} (Layer C #70
                               daily live-drift check; install: see deploy/README.md)
docs/                          Reference docs (SKILLS) + plans/ + research/
skills/                        Agent skills (committed overrides + symlinks → skills-vendor/)
skills-vendor/                 Git submodules for external skill repos
.claude/skills/                Claude Code skill discovery (symlinks → ../../skills/<name>)
.github/workflows/             CI — lint job (ruff check + ruff format --check),
                               test job (Postgres service container, alembic upgrade,
                               pytest), client-drift job (regen vendored clients
                               from committed OpenAPI snapshots, fail on diff),
                               and changelog job (changes under
                               alembic/versions/, src/api/routes/,
                               src/api/schemas/, or clients/python/ must touch
                               CHANGELOG.md — path-triggered, not commit-type;
                               opt out via `no-changelog` PR label).
                               Triggers on push/PR to main.
.pre-commit-config.yaml        ruff check + ruff format + standard pre-commit-hooks
                               (pre-commit stage), plus a pre-push guard
                               (scripts/check_changelog_on_push.sh) that mirrors
                               the CI changelog check before the push leaves the
                               clone. Run `uv run pre-commit install` once per
                               clone — installs both pre-commit and pre-push
                               hook types via default_install_hook_types.
```

## Content-acquisition via co-core (archiver#72 Phase 1)

Fetch, extract, and the content fingerprint are consumed from **co-core**,
the canonical implementation upstreamed in cannobserv#255. The former
`src/core/{fetchers,extractors,simhash,extraction_defaults}` mirror was deleted when
Phase 1b landed — **no more mirror discipline for the acquisition pipeline.**

- **Fetch** — `co_core_aio.fetch.AsyncFetchDriver` executes the `co_core.effects.fetch.FetchContent`
  effect (raw bytes, captures non-2xx as `FetchResult`). Wired into `app.state.fetch_driver`
  at the FastAPI composition root (`main.lifespan`), injected via `deps.get_fetch_driver`.
- **Extract + fingerprint** — `co_core.pure.extract.*` (`html`/`csv_excel`/`pdf` extractors,
  now **synchronous**; `sha256` + `simhash` per `Chunk`). Requires the **`co-core[extract]`**
  extra; import parsers from their submodules (`co_core.pure.extract.html`, …) — they are not
  re-exported from `__init__`.

**No cross-repo mirror discipline (CannObserv/watcher#159, #236).** Content
acquisition is co-core's (above) and the change-bus contracts + driver are too
(see "Change-bus producer"). `src/core/logging.py` is service-local — Watcher
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

**Never hand-roll the uvicorn invocation.** The recipe this replaced sourced
`/etc/archiver/.env` and then ran uvicorn directly, which left
`ARCHIVER_DATABASE_URL` pointing at **production** — the dev server on 8021 and
the live service on 8020 shared one database. On 2026-07-18 a dashboard
verification run drove the dev server and wrote a `verify79.example.com`
Domain, two InfoSources, and an AppUser into the production registry.

`scripts/dev_server.sh` resolves the dev database from
`ARCHIVER_DEV_DATABASE_URL`, else `TEST_DATABASE_URL`; refuses to start if that
resolution equals `ARCHIVER_DATABASE_URL` or `DATABASE_URL`; clears the
`DATABASE_URL` fallback; refuses port 8020; and runs `alembic upgrade head`
against the dev database before serving. This mirrors `_check_test_url_safety`
in `tests/conftest.py`, which guards pytest but not a hand-run server.

Anything that writes — curl against the dashboard, SDK scripts, manual
verification — must target 8021, never 8020.

| Knob | Effect |
|---|---|
| `ARCHIVER_DEV_DATABASE_URL` | Persistent dev DB; wins over `TEST_DATABASE_URL` |
| `ARCHIVER_DEV_REDIS_URL` | Dev change-bus broker. Unset → dev runs bus-dormant (prod's `ARCHIVER_REDIS_URL` is never inherited); refused if equal to prod's |
| `ARCHIVER_DEV_PORT` | Default 8021; 8020 is refused |
| `ARCHIVER_DEV_SKIP_MIGRATE=1` | Skip the alembic upgrade |

> pytest teardown runs `DROP SCHEMA information CASCADE` against
> `TEST_DATABASE_URL`. Running the suite while a dev server points at the same
> database wipes dev data mid-session — survivable, and strictly better than
> writing to production. Set `ARCHIVER_DEV_DATABASE_URL` to a dedicated
> database (e.g. `archiver_dev`) if that becomes annoying.

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

> Use `set -a; . <file>; set +a` (POSIX-portable source via `.`) rather than `export $(cat <file> | xargs)`. The xargs form silently breaks for values containing spaces, quotes, newlines, or embedded `=` — and produces hard-to-diagnose failures later when those env vars are read.

**Key variables:**
- `ARCHIVER_DATABASE_URL` — PostgreSQL connection (falls back to `DATABASE_URL`).
- `TEST_DATABASE_URL` — separate test database. **Must not equal `ARCHIVER_DATABASE_URL` or `DATABASE_URL`** — teardown drops the entire `information` schema. Convention: database name **must** end in `_test` (e.g. `archiver_test`) — `scripts/dev_server.sh` enforces the suffix, and `conftest.py` asserts non-equality at collection time and fails fast if violated.
- `ARCHIVER_ALLOW_PRODUCTION_DB` — *optional*. `1` permits the process to serve a database whose name lacks a `_test`/`_dev` suffix. **Only `deploy/archiver.service` sets it.** Without it `src/core/db_safety.py` refuses to start at lifespan, so a hand-rolled `uvicorn` cannot reach the production registry no matter which env files it sourced (2026-07-18 incident). Never set this in `/etc/archiver/.env` or `.env` — putting it in an env file would re-open the hole for every process that sources them.
- `ARCHIVER_DEV_DATABASE_URL` — *optional*. Persistent dev database for `scripts/dev_server.sh`; wins over `TEST_DATABASE_URL`. Use when pytest's `DROP SCHEMA` teardown wiping your dev data mid-session becomes annoying. Name must end in `_test`/`_dev`.
- `ARCHIVER_DEV_PORT` — *optional*. Dev server port, default `8021`. `8020` is refused (systemd's). See **Server Lifecycle**.
- `ARCHIVER_REDIS_URL` — *optional*. When set, enables the outbox publisher background task that drains `changes_outbox` rows to the `info.changes` Redis Stream. Unset → publisher is silently disabled (degraded mode for local dev without Redis). **Archiver operates the local `redis-server` broker** (archiver#109 — it is the change-bus producer + cluster control-plane); see `deploy/redis-server.dropin.conf`, `deploy/README.md`, and the design note `docs/plans/2026-07-29-redis-bus-ownership-design.md`. The connection string is the only switch — `rediss://user:pass@host:port/db` moves to a managed provider with no code change (`RedisAsync.from_url` handles TLS + auth). `archiver.service` orders after `redis-server` (`Wants=`/`After=`, soft — the outbox tolerates broker downtime) and an `ExecStartPre` (`scripts/check_redis_floor.sh`) asserts the ≥7.0 server floor when the bus is active.
- `ARCHIVER_REDIS_STREAM_MAXLEN` — *optional*. Approximate cap on the `info.changes` stream (default `100000`; `≤0` disables; an **invalid value falls back to the default** rather than disabling the publisher). The outbox publisher periodically issues `XTRIM info.changes MAXLEN ~ N` so the stream stays bounded before a consumer (Replicator, Phase 3) exists — operator-side retention, since co-core exposes no XADD-time trim arg.
- `ARCHIVER_REDIS_FLOOR_TIMEOUT` — *optional*. Seconds (default `5`) bounding the Redis version-floor probe in `scripts/check_redis_floor.sh` (the `archiver.service` `ExecStartPre`). `redis-cli` has no connect-timeout flag, so the probe is wrapped in `timeout`; this prevents a `rediss://`-vs-plaintext (or unreachable) endpoint from hanging archiver startup — a timeout yields a soft-skip, never a block.
- `ARCHIVER_DEV_REDIS_URL` — *optional*. Dev change-bus broker for `scripts/dev_server.sh`. Unset → the dev server runs **bus-dormant** and never inherits prod's `ARCHIVER_REDIS_URL` from `/etc/archiver/.env` (the Redis analogue of the DB `_test`/`_dev` guard). Point it at a distinct broker or logical DB index (e.g. `.../1`); a value equal to the production URL is refused.
- `ARCHIVER_PUBLIC_BASE_URL` — *optional*. Public-facing base URL of this Archiver instance (e.g. `https://archiver.example.com`). When set, InfoItem API responses include `dashboard_url` pointing to the dashboard detail page (`{ARCHIVER_PUBLIC_BASE_URL}/info-items/{id}`). Unset → `dashboard_url` is `null`. Set this to the URL end-users open in a browser, distinct from any internal service-to-service address. Set in `/etc/archiver/.env` on the VM.
- `WATCHER_BASE_URL` — *optional*. Base URL of the sibling Watcher service for **service-to-service API calls** (e.g. `http://localhost:8000`). When set (together with `WATCHER_API_KEY`), the Archiver provisions WatchedItems on InfoItem create and patches them on primary-source swap. Unset → Watcher integration disabled; `watcher_item_id` stays `NULL` on all InfoItems. **Do not use a public proxy URL here on the same VM** — hairpin NAT means the proxy URL won't route from within the VM; use `http://localhost:<port>` instead.
- `WATCHER_PUBLIC_BASE_URL` — *optional*. Public-facing base URL of the Watcher service for **browser deeplinks** (e.g. `https://watcher.exe.xyz:8000`). When set, the dashboard's Watcher-section header deeplink ("Watcher ↗" on the InfoItem detail page) uses this URL instead of `WATCHER_BASE_URL`. Unset → falls back to `WATCHER_BASE_URL`. Set in `/etc/archiver/.env`. Analogous to `ARCHIVER_PUBLIC_BASE_URL`.
- `WATCHER_API_KEY` — *optional*. API key sent as `X-API-Key` to the Watcher service. Store in `/etc/archiver/.env`. Required when `WATCHER_BASE_URL` is set.
- `WATCHER_CACHE_DIR`, `WATCHER_CACHE_TTL_SECONDS`, `WATCHER_CACHE_SWEEP_INTERVAL_SECONDS` — Watcher-side, not Archiver-side; documented here because the `content_cache_uri` lifecycle protocol they govern is a registry contract (see design doc Section 2).

## Authoring tools + assignment endpoints (v2)

The Archiver exposes authoring helpers under `/api/v1/tools/*` and mutating sub-resource routes under `/api/v1/info-items/{id}/*`. All routes use `X-API-Key` auth (only `/health` and `/openapi.json` are open). Each route has an ergonomic SDK wrapper on `ArchiverClient` (v5.x; see [CHANGELOG.md](CHANGELOG.md) for version history).

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
| List InfoSources (filter by URL or domain, paginated) | `GET /info-sources?url=…&domain_name=…&limit=&offset=` | `list_info_sources(url=None, domain_name=None, limit=None, offset=None)` |
| Author a RepSpec | `POST /rep-specs` | `create_rep_spec(provider, name, document)` |
| Get a RepSpec | `GET /rep-specs/{id}` | `get_rep_spec(id)` |
| Update a RepSpec (name always; document only while draft) | `PATCH /rep-specs/{id}` | `update_rep_spec(id, name=None, document=None)` |
| List RepSpecs (filter by provider, paginated) | `GET /rep-specs?provider=…&limit=&offset=` | `list_rep_specs(provider=None, limit=None, offset=None)` |
| Assign a RepSpec | `POST /info-items/{id}/rep-spec-assignments` | `assign_rep_spec(info_item_id, rep_spec_id, activated_at=None)` |
| Deactivate an assignment | `DELETE /info-items/{id}/rep-spec-assignments/{aid}` | `deactivate_rep_spec_assignment(info_item_id, assignment_id)` |
| Public-URL writeback | `PATCH /info-items/{id}/rep-spec-assignments/{aid}` | `set_public_url(info_item_id, assignment_id, public_url)` |
| Record a SourceRevision (idempotent) | `POST /source-revisions` | `post_source_revision(...)` |
| Clear cache fields | `PATCH /source-revisions/{id}` | `patch_source_revision_cache(id, content_cache_uri=None, content_cache_expires_at=None)` |

`POST /info-sources` accepts `{url, source_specs}`. Multiple InfoSources at the same URL are valid. Returns 422 on invalid URL or spec validation failure.

**Pagination:** `GET /info-items`, `GET /info-sources`, and `GET /rep-specs` return a `Page` envelope — `{items, has_more, limit, offset}`. All accept `limit` (default 100, max 500) and `offset` (default 0) query params. Ordering is stable: `(created_at, id)`. `has_more` is computed via a `limit+1` probe — no total count. SDK methods `list_info_items` / `list_info_sources` / `list_rep_specs` return `PageInfoItemOut` / `PageInfoSourceOut` / `PageRepSpecOut`; pass `limit`/`offset` to forward to the server.

**SDK version history:** see [CHANGELOG.md](CHANGELOG.md).

**Change-bus producer (co-core bus, archiver#106):** Writes rows to
`information.changes_outbox` in the same transaction (the **outbox stays
archiver-owned** — it is the producer-side delivery guarantee); the publisher
background task (`src/core/changes/publisher.py`) drains the outbox and publishes
each row to the Redis Stream `info.changes` **through the shared co-core bus
driver** — `co_core_aio.bus.AsyncBusPublisher.execute(BusPublish(...))`, with the
wire envelope built by `co_core.pure.adapters.bus.envelope.to_wire`. Publisher
only starts when `ARCHIVER_REDIS_URL` is set. Two event types:

| Event type | Trigger | Payload type (co-core) |
|---|---|---|
| `source_revision_captured` | New `SourceRevision` insert (`POST /source-revisions` on non-idempotent path) | `co_core.pure.models.changes.SourceRevisionCapturedEvent` |
| `info_item_primary_changed` | New active `InfoItemSource` binding created (`POST /info-items/{id}/info-sources`) | `co_core.pure.models.changes.InfoItemPrimaryChangedEvent` |

The payload models live in **co-core** (`co_core.pure.models.changes`) — lifted
from archiver in cannobserv#261 so the whole cluster shares one contract. Emit
sites construct the **strict `*Emit` subclasses** (`SourceRevisionCapturedEmit` /
`InfoItemPrimaryChangedEmit`, `extra="forbid"`) for emit-time typo-catch; the
canonical classes are `extra="ignore"` (consumer-safe forward-compat). The
**wire envelope** is the XADD field map `key` / `payload` (full event JSON) /
`event_type` / `schema_version` / `occurred_at` / `content_type`; the idempotency
`key` is derived per type by co-core (`source_revision_id`; the
`{info_item_id}:{new_info_source_id}` composite).

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

## Agent Skills

Skills live in `skills/` (agentskills.io) and `.claude/skills/` (Claude Code). Local overrides in `skills/` shadow vendor submodules in `skills-vendor/`.

| Skill | Triggers / when to invoke |
|---|---|
| `reviewing-code-python-fastapi` | CR, code review |
| `reviewing-architecture` | AR, architecture review |
| `enforcing-architecture` | add a fitness function, enforce this contract, lock this rule (delegated to by `reviewing-architecture` on a `fitness` directive) |
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

That is: deployed migrations, the HTTP API surface, the Pydantic
request/response models, and the SDK. Everything else — **dashboard UX
included** — needs no entry, along with internal refactors, test-only,
lint/tooling, and docs-only changes. A dashboard-only behaviour fix does
not get a changelog entry even though it is user-visible; the surface
that matters here is the contract, not the UI.

Tag each entry `[service]`, `[sdk]`, or `[both]` per the format header in
`CHANGELOG.md`. The SDK README links here; do not maintain a second
changelog there. On a PR, the `no-changelog` label opts out.

**Dashboard living docs:** each doc is scoped to what it actually documents —
update the one(s) the change touches, in the same commit. Failure to update an
applicable doc is a CR blocker.

- `docs/UI.md` — required for any change to a Jinja2 template in
  `src/dashboard/templates/`, a JS module under `src/dashboard/static/`, or a
  new/changed dashboard route.
- `docs/STYLE.md` — required when the change introduces or alters *styling*:
  `src/dashboard/static/dashboard.css`, or a template that adds a new visual
  pattern rather than reusing existing classes.

A template change that composes only existing CSS classes needs UI.md alone.

**Logging:**
```python
from src.core.logging import get_logger
logger = get_logger(__name__)
```
Entry points only: call `configure_logging()` once.

The app's own records — including uvicorn's access/error lines via `--log-config`
— are JSON. `ExecStartPre` steps in `deploy/archiver.service` (wheelhouse sync,
redis floor check) write **plain text** to journald by design: they run
before the app process exists and cannot import the project, so they cannot share
`build_json_formatter()`. A journald consumer that blindly `json.loads` every
`MESSAGE` must tolerate these lines (the failure-path `error: could not sync gs://…`
in particular); native field-based readers are unaffected. See archiver#124,
gregoryfoster/skills#83.

**Date & Time:** All UTC. ISO 8601: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (timestamps), `YYYY-MM-DD` (dates).

**General:**
- No inline module imports; all at file top — `src/`, `tests/`, `scripts/`, and
  `alembic/` alike. Ruff `PLC0415` enforces this in CI (archiver#97); `if
  TYPE_CHECKING:` guards are module-level and pass. The vendored SDKs under
  `clients/` resolve their own `[tool.ruff]` config and are exempt — their
  generated code imports lazily to dodge circular imports.
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

- **`RepSpec`** (`rep_specs`) — replication specification. JSONB `document` carries provider config, `credentials_alias`, `path_template`, `required_fields`. Per-provider sub-schemas under `src/core/rep_spec_schema/providers/`.
  **Tiered mutability** (#83): `name` always editable; `document` editable only while the RepSpec is a
  *draft* — zero `info_item_rep_specs` rows, active **or** deactivated; `provider` frozen always.
  `updated_at` is nullable and never backfilled (NULL = never edited). An assigned spec is frozen
  because its assignment rows assert which document produced the artefacts at their `public_url`;
  clone + migrate is #95. See `docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md`.
- **`InfoItemRepSpec`** (`info_item_rep_specs`) — effective-dated assignment + `public_url` writeback target.
- **`ChangesOutboxRow`** (`changes_outbox`) — pending change-bus event awaiting publication.

The Phase 1–3a `InfoSpec` model has been retired. Avoid any new references to `info_spec*` outside historical alembic migration files. The "Archiver" rename was service-name-only; `info_*` table prefix and `information` schema preserved per design decision.
