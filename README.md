# archiver

Cannabis Observer **Archiver service** — central registry + authoring service for the information layer. Owns **Information Items**, **Information Sources** (URL + multi-spec extraction array), **Source Revisions** (content-addressed snapshots), **Replication Specifications**, and effective-dated item↔rep-spec assignments. FastAPI + PostgreSQL. Sibling to [watcher](../watcher) and [notifier](../notifier); consumed by Watcher (and the forthcoming Replicator) via the `archiver-client` v5.x Python SDK; produces the `info.changes` Redis Stream via an internal outbox publisher.

Extracted from the in-tree `src/information/` of watcher in 2026-05 (watcher#149). The current data model (Phase 4 / Archiver v2) is documented in [docs/plans/2026-05-08-archiver-v2-architecture-design.md](docs/plans/2026-05-08-archiver-v2-architecture-design.md); the implementation plan is at [docs/plans/2026-05-08-phase-4-archiver-v2-implementation.md](docs/plans/2026-05-08-phase-4-archiver-v2-implementation.md). Those are dated snapshots — for current behaviour see the live docs below.

## Documentation

[AGENTS.md](AGENTS.md) is the entry point; its **Detail Docs** index is the full list. Most-reached-for:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — repository layout and the co-core acquisition wiring
- [docs/API.md](docs/API.md) — every HTTP route, its SDK wrapper, and the `info.changes` event contract
- [docs/SCHEMA.md](docs/SCHEMA.md) — per-table contracts and invariants
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — wheelhouse, dev server, environment variables
- [docs/UI.md](docs/UI.md) / [docs/STYLE.md](docs/STYLE.md) — dashboard pages, patterns, and styling

## Run locally

```bash
# co-core / co-core-aio resolve from a wheelhouse mirrored from the private GCS
# index (see AGENTS.md → Environment & Tooling); populate it before uv sync:
set -a; . /etc/archiver/.env; set +a
uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py
uv sync
bash scripts/dev_server.sh
```

`scripts/dev_server.sh` is the only sanctioned way to start a dev server. It
sources the env files, resolves a **non-production** database
(`ARCHIVER_DEV_DATABASE_URL`, else `TEST_DATABASE_URL`), refuses to start
unless that database name ends in `_test`/`_dev`, runs `alembic upgrade head`,
and serves on 8021.

**Never hand-roll the `uvicorn` invocation.** The recipe this replaced sourced
`/etc/archiver/.env` and ran uvicorn directly, which left
`ARCHIVER_DATABASE_URL` pointed at production — on 2026-07-18 that wrote a
`verify79.example.com` Domain, two InfoSources, and an AppUser into the live
registry. The application now also refuses to serve a production database
unless `ARCHIVER_ALLOW_PRODUCTION_DB=1` is set, which only
`deploy/archiver.service` does.

Production listens on **port 8020** under `archiver.service`. The dev server uses 8021 to leave 8020 alone for systemd.

## Tests

```bash
set -a
[ -f /etc/archiver/.env ] && . /etc/archiver/.env
[ -f .env ] && . .env
set +a
uv run pytest
```

`TEST_DATABASE_URL` is required (a separate Postgres database from `ARCHIVER_DATABASE_URL`).

## SDK

Generated + hand-written Python client at [clients/python/](clients/python/). Its version lives in `clients/python/pyproject.toml` and moves **independently** of the service version in the root `pyproject.toml` — the SDK bumps only when its surface changes, so a service-only patch does not bump it (see [CHANGELOG.md](CHANGELOG.md), which carries both). Path-installed by Watcher and Replicator. To regenerate from the running service:

```bash
bash clients/python/scripts/regen.sh
```

(The script invokes `dump_openapi.py` internally.)

## Admin dashboard

HTML/HTMX admin UI at `/dashboard/`. Auth via `X-ExeDev-UserID` / `X-ExeDev-Email` proxy headers (redirects to `/__exe.dev/login` when absent). Covers all registry entities: Information Items, Information Sources, Source Revisions, Replication Specifications, and API key management. See [docs/UI.md](docs/UI.md) for the full page inventory and component catalogue.

## Optional: change-bus publisher

Set `ARCHIVER_REDIS_URL=redis://localhost:6379/0` in the environment to enable the outbox publisher background task that drains `changes_outbox` rows to the `info.changes` Redis Stream. Unset → publisher is silently disabled (degraded local-dev mode).
