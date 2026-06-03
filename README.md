# archiver

Cannabis Observer **Archiver service** — central registry + authoring service for the information layer. Owns **Information Items**, **Information Sources** (URL + multi-spec extraction array), **Source Revisions** (content-addressed snapshots), **Replication Specifications**, and effective-dated item↔rep-spec assignments. FastAPI + PostgreSQL. Sibling to [watcher](../watcher) and [notifier](../notifier); consumed by Watcher (and the forthcoming Replicator) via the `archiver-client` v4.x Python SDK; produces the `info.changes` Redis Stream via an internal outbox publisher.

Extracted from the in-tree `src/information/` of watcher in 2026-05 (watcher#149). The current data model (Phase 4 / Archiver v2) is documented in [docs/plans/2026-05-08-archiver-v2-architecture-design.md](docs/plans/2026-05-08-archiver-v2-architecture-design.md); the implementation plan is at [docs/plans/2026-05-08-phase-4-archiver-v2-implementation.md](docs/plans/2026-05-08-phase-4-archiver-v2-implementation.md).

## Run locally

```bash
set -a
[ -f /etc/archiver/.env ] && . /etc/archiver/.env
[ -f .env ] && . .env
set +a
uv sync
uv run alembic upgrade head
uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8021 --reload
```

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

Generated + hand-written Python client at [clients/python/](clients/python/), pinned 1:1 with the service version (see [CHANGELOG.md](CHANGELOG.md) for current). Path-installed by Watcher and Replicator. To regenerate from the running service:

```bash
bash clients/python/scripts/regen.sh
```

(The script invokes `dump_openapi.py` internally.)

## Admin dashboard

HTML/HTMX admin UI at `/dashboard/`. Auth via `X-ExeDev-UserID` / `X-ExeDev-Email` proxy headers (redirects to `/__exe.dev/login` when absent). Covers all registry entities: Information Items, Information Sources, Source Revisions, Replication Specifications, and API key management. See [docs/UI.md](docs/UI.md) for the full page inventory and component catalogue.

## Optional: change-bus publisher

Set `ARCHIVER_REDIS_URL=redis://localhost:6379/0` in the environment to enable the outbox publisher background task that drains `changes_outbox` rows to the `info.changes` Redis Stream. Unset → publisher is silently disabled (degraded local-dev mode).
