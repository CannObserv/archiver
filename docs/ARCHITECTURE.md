# archiver — Architecture

Repository layout and the content-acquisition data flow. `AGENTS.md` keeps only
the non-obvious boundaries and the rules that constrain them; the enumeration
lives here.

> The authoritative list of live reference documents is the **Detail Docs** index
> in [AGENTS.md](../AGENTS.md); the `docs/` entry in the tree below mirrors it.

## Current model (Phase 4 — Archiver v2)

Phase 4 (the current model — Archiver v2) shipped 2026-05-09 on branch `phase-4-archiver-v2`. Design + implementation plan:

- `docs/plans/2026-05-08-archiver-v2-architecture-design.md`
- `docs/plans/2026-05-08-phase-4-archiver-v2-implementation.md`

## Project Layout

```
src/api/                       FastAPI routes, deps, schemas, serializers
src/dashboard/                 HTML/HTMX admin dashboard (routes/, templates/, static/, deps.py,
                               pagination.py — shared clamped limit/offset dependency; see
                               docs/UI.md for why the dashboard clamps where the API 422s;
                               watch_panel.py — pure watched-item panel context from local
                               state: states, health rule, next-due, drift, archiver#151;
                               replication_actions.py — the manual-replication outcome→flash
                               translation shared by both screens that offer the action, and
                               the one place that records why a refusal is a 200 rather than
                               a 4xx, archiver#171)
src/core/                      Domain logic
  models/                      ORM (info_item, info_source, source_revision,
                               info_item_source, rep_spec, info_item_rep_spec,
                               changes_outbox, replication_command)
  source_spec_schema/          SourceSpec JSON Schema v1 + validator
  rep_spec_schema/             RepSpec envelope + per-provider sub-schemas
                               (providers/{gcs,gdrive,ia}/v1.json)
  rep_fields_schema/           rep_fields meta-schema + validator
  replication/                 The RepSpec path contract and the destination
                               renderer (archiver#168). template.py holds the
                               ONE placeholder parser — used by the create/update
                               gate (via rep_spec_schema/validator.py) and by the
                               renderer, so a document that validates is one that
                               renders; it also owns the occasion namespace
                               (source_revision.*, reserved out of
                               required_fields) and the R2 discriminator rule.
                               destination.py renders, refuses (segment charset,
                               T3 path guards, naive datetimes), pre-flights a
                               fan-out set for colliding paths, and probes
                               renderability at assignment time. errors.py is the
                               single base both raise under, so archiver#169 can
                               record a skip by catching one class. Archiver
                               renders because the issuer contract's T3 says so
                               — Replicator receives strings and never
                               interpolates. Do not write a second renderer.
  watch_spec_schema/           WatchSpec (cadence policy) v1 + validator. Cadence
                               only — pause state is info_items.watch_active
  changes/                     The background asyncio tasks and their shared
                               pacing. group_consumer.py owns the consumer-group
                               loop — read, claim, quarantine, ack, back off,
                               re-arm — and is SHARED by both group consumers
                               rather than copied: nearly every line encodes an
                               incident or a review finding, and a copy inherits
                               those once and then drifts. artifacts_consumer.py
                               applies replication outcomes from content.artifacts
                               (archiver#170) — public_url's automated writer;
                               replication_reaper.py closes commands that produced
                               no fact at all, on a timer because it detects an
                               absence. publisher.py drains changes_outbox to
                               info.changes; consumer.py ingests
                               source_revision_observed from content.revisions
                               (archiver#139) and is gated on
                               ARCHIVER_BUS_CONSUMER; backoff.py holds the
                               retry/log-throttle constants both use — shared,
                               not copied, because they encode incident history
                               (#107, #128). diagnostics.py renders an exception
                               plus its __cause__/__context__ chain for both
                               paths: co-core's wrappers name only the
                               event_type, so repr() alone drops the remedy —
                               and that string is the whole diagnostic a
                               dead-lettered row or a quarantined message leaves
                               (#141). registry_snapshot.py is the info.registry
                               full-set republish timer — direct publish,
                               bypassing the outbox (no pruner exists), no
                               retry (the next period is the repair), reading
                               generations without bumping (#141). The event
                               payload models live in co-core since #106, not
                               here. watch_status_consumer.py tails
                               info.watch-status groupless (AsyncBusTailReader,
                               archiver#151) into the watch_status cache —
                               resumes from bus_tail_cursors, no DLQ, and
                               deliberately no ARCHIVER_BUS_CONSUMER gate: a
                               tail removes nothing from a group PEL.
  services/                    Registry write paths shared by the HTTP surface
                               and the bus consumers. A service owns one
                               mutation end to end — domain validation, the
                               write, and its changes_outbox row — raises domain
                               errors rather than HTTPException, and never
                               commits: the caller owns the transaction, because
                               "row and event in one transaction" is the outbox
                               guarantee. source_revision.py is why the bus and
                               HTTP paths cannot emit divergent payloads.
                               replication_status.py is the one read-only member:
                               a projection of replication_commands for the
                               dashboard's assignment tables (archiver#171), so
                               a public_url with an automated writer can say
                               which occasion wrote it.
  spec_match.py                Compares an observed spec_fingerprint against the
                               InfoSource's own source_specs via co-core's shared
                               derivation (cannobserv#309). Every uncertain branch
                               resolves to "incomparable", never "superseded" — a
                               false mismatch reads exactly like a real one.
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
                               redis-server.dropin.conf (the broker cap Archiver
                               owns — see the archiver#128 lockstep invariant)
docs/                          Live reference docs — ARCHITECTURE.md, API.md,
                               BUS.md, SCHEMA.md, DEPLOYMENT.md, CONVENTIONS.md,
                               SKILLS.md, plus the dashboard living docs
                               UI.md + PAGES.md + INFO_ITEM_DETAIL.md +
                               COMPONENTS.md + STYLE.md
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
