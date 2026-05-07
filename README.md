# archiver

Cannabis Observer **Archiver service** — canonical registry of Information Items and Information Source Specifications. Sibling service to [watcher](../watcher) and [notifier](../notifier); consumed by Watcher (and a forthcoming Replicator) via the `archiver-client` Python SDK.

Extracted from the in-tree `src/information/` of watcher in 2026-05; see watcher#149 for the extraction history and `docs/research/2026-05-06-archiver-information-model.md` for the trajectory toward an `InfoSource` + `SourceRevision` content-addressed model.

## Run locally

```bash
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
uv sync
uv run alembic upgrade head
uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8021 --reload
```

Production listens on **port 8020** under `archiver.service`. The dev server uses 8021 to leave 8020 alone for systemd.

## Tests

```bash
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
uv run pytest
```

`TEST_DATABASE_URL` is required (a separate Postgres database from `ARCHIVER_DATABASE_URL`).

## SDK

Generated Python client at [`clients/python/`](clients/python/). Path-installed by Watcher and Replicator. To regenerate from the running service:

```bash
uv run python scripts/dump_openapi.py > /tmp/openapi.json
bash clients/python/scripts/regen.sh /tmp/openapi.json
```
