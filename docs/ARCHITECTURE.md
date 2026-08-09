# archiver — Architecture

Repository layout and the content-acquisition data flow. `AGENTS.md` keeps only
the non-obvious boundaries and the rules that constrain them; the enumeration
lives here.

> The authoritative list of live reference documents is the **Detail Docs** index
> in [AGENTS.md](../AGENTS.md); the `docs/` entry in the tree below mirrors it.

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
  changes/                     Two background asyncio tasks and their shared
                               pacing: publisher.py drains changes_outbox to
                               info.changes; consumer.py ingests
                               source_revision_observed from content.revisions
                               (archiver#139) and is gated on
                               ARCHIVER_BUS_CONSUMER; backoff.py holds the
                               retry/log-throttle constants both use — shared,
                               not copied, because they encode incident history
                               (#107, #128). The event payload models live in
                               co-core since #106, not here.
  services/                    Registry write paths shared by the HTTP surface
                               and the bus consumers. A service owns one
                               mutation end to end — domain validation, the
                               write, and its changes_outbox row — raises domain
                               errors rather than HTTPException, and never
                               commits: the caller owns the transaction, because
                               "row and event in one transaction" is the outbox
                               guarantee. source_revision.py is why the bus and
                               HTTP paths cannot emit divergent payloads.
  fingerprints.py              The sha256:<64 hex> content-fingerprint spelling.
                               Its own module so the API schema and the bus
                               consumer can share the rule without either
                               dragging in the ORM.
  tools/                       Authoring helpers (assign_rep_spec + lock_rep_specs,
                               update_rep_spec, resolve_rep_fields,
                               preview_extraction, etc.)
  logging.py                   Structured logging config (configure_logging at
                               entry points). Service-local — Watcher keeps its
                               own copy and there is NO parity requirement; see
                               "No cross-repo mirror discipline".
                               build_json_formatter() is the single source of
                               truth for the JSON field contract. Fetch +
                               extract + fingerprint come from co-core — see
                               "Content-acquisition via co-core"
  database.py                  Lazy async engine + async_sessionmaker singletons
                               (get_database_url / get_engine /
                               get_session_factory / reset_engine)
  watcher_provisioning.py      Best-effort Watcher provisioning helpers, called
                               post-commit from routes: provision_on_create,
                               sync_on_source_swap, sync_on_spec_update. Never
                               propagate — they swallow + log, and are no-ops when
                               WATCHER_BASE_URL / WATCHER_API_KEY are unset. The
                               first two return a WatcherSyncOutcome so the
                               dashboard can flash CONTRACT_ERROR (stale SDK)
                               separately from a transport FAILED
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
clients/python/                archiver_client SDK v5.x (generated + hand-written wrappers).
                               Version lives in clients/python/pyproject.toml and
                               bumps only when the SDK surface changes
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
                               tests/core/ for domain logic; tests/dashboard/ for the HTMX UI;
                               tests/js/ for the dashboard JS modules; tests/scripts/ for the
                               shell/Python helpers under scripts/ (incl.
                               test_db_guard_parity.py, which keeps dev_server.sh in step
                               with db_safety.py);
                               tests/deploy/ asserts the installed systemd artifacts match
                               deploy/ — archiver.service and the redis-server drop-in
                               (each skips when absent, so CI passes). File-parity only:
                               the LIVE broker config is checked by check_redis_floor.sh
scripts/                       sync_wheelhouse.py (mirror co-core wheels from the private
                               GCS index into ./.wheelhouse; run before uv sync, and in the
                               archiver.service ExecStartPre) +
                               dump_openapi.py +
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
                               check_changelog_lib.sh (the shared trigger-path
                               predicate; sourced by the guard) +
                               test_check_changelog.sh (its unit tests; runs as a
                               pre-commit hook) +
                               check_version_lockstep.py (CI lint job: pyproject
                               [project].version must equal the newest CHANGELOG
                               `## vX.Y.Z` heading — #85 silent drift) +
                               check_redis_floor.sh (archiver.service ExecStartPre:
                               ≥7.0 broker floor + warn-only live-maxmemory check,
                               each probe bounded by ARCHIVER_REDIS_FLOOR_TIMEOUT) +
                               dev_server.sh (ONLY sanctioned way to start the
                               8021 dev server; refuses to resolve onto the
                               production DB — see "Server Lifecycle")
deploy/                        README.md (install instructions) + systemd units:
                               archiver.service +
                               watcher-live-drift.{service,timer} (Layer C #70
                               daily live-drift check) +
                               redis-server.dropin.conf (the broker cap Archiver
                               owns — see the archiver#128 lockstep invariant)
docs/                          Live reference docs — ARCHITECTURE.md, API.md,
                               SCHEMA.md, DEPLOYMENT.md, CONVENTIONS.md,
                               SKILLS.md, plus the dashboard living docs
                               UI.md + PAGES.md + COMPONENTS.md + STYLE.md
                               (see "Dashboard living docs").
                               Indexed by the Detail Docs section of AGENTS.md.
                               Archival subtrees: plans/ + research/
skills/                        Agent skills (committed overrides + symlinks → skills-vendor/)
skills-vendor/                 Git submodules for external skill repos
.skills/doctor.sh              Committed skill-symlink doctor (real file, not a
                               symlink) — see "SessionStart Hooks"
.claude/skills/                Claude Code skill discovery (symlinks → ../../skills/<name>)
.github/workflows/             CI (ci.yml) — lint job (ruff check + ruff format --check
                               + check_version_lockstep.py),
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
                               + test_check_changelog.sh (pre-commit stage), plus a pre-push guard
                               (scripts/check_changelog_on_push.sh) that mirrors
                               the CI changelog check before the push leaves the
                               clone. Run `uv run pre-commit install` once per
                               clone — installs both pre-commit and pre-push
                               hook types via default_install_hook_types.
```

Quoted section names in the tree above ("Server Lifecycle", "Dashboard living
docs", "SessionStart Hooks", "Content-acquisition via co-core", "No cross-repo
mirror discipline") refer to sections of [AGENTS.md](../AGENTS.md).

## Content acquisition via co-core

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

## Retired model (Phase 1–3a)

The earlier `InfoItem ↔ InfoSpec` Phase 1–3a model is gone — `info_specs` table dropped, `info_spec_schema` package deleted, all SDK methods retired. The 2026-05-06 trajectory research doc remains as historical context.
