# archiver — Deployment & Configuration

Wheelhouse reproducibility, dev-server internals, and the full environment
variable reference. `AGENTS.md` keeps the safety rules; the reference lives here.

## cannobserv substrate

**cannobserv substrate (archiver#72/#75).** `co-core` + `co-core-aio` (the shared
Cannabis Observer core library — pure models/utils + async drivers) are declared
as plain floors and resolved from a local **wheelhouse**
(`./.wheelhouse`, gitignored) via `[tool.uv] find-links`, mirrored from the private
GCS index `gs://co-gcs-pypi` by `scripts/sync_wheelhouse.py`. This is Phase 0 of the
cluster-integration strategy — the precedent Watcher/Replicator follow. Populate the
wheelhouse before `uv sync`/`uv run`:

## Wheelhouse reproducibility

Reproducibility is `uv.lock` (pinned version + wheelhouse artifact), not the
wheelhouse contents. Upgrade: re-sync, then `uv lock --upgrade-package co-core`
(bump the floor if the minor moved). CI resolves the wheelhouse keyless via Workload
Identity Federation; the deploy unit syncs it in `ExecStartPre`. No git sources and
no `cannobserv`/`co-core-sync` (heavy google/trello deps). Archiver depends on
**`co-core[extract]`** + `co-core-aio` — the authoring tools use `co_core_aio.fetch`
(fetch) and `co_core.pure.extract` (extract + fingerprint); see "Content-acquisition
via co-core".

## Why `scripts/dev_server.sh` exists

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

## Dev-server knobs

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

## One-time data imports

### `scripts/import_watch_specs.py` — Watcher's cadence + active state (archiver#150)

Moves `default_schedule_config` and `is_active` off Watcher's `watched_items` onto
`info_items.watch_spec` / `info_items.watch_active`. The `watcher_client` SDK is the only reader
of those two fields, and archiver#142 deletes it — this is step 4b's single irreversible action.

```bash
set -a; . /etc/archiver/.env; [ -f .env ] && . .env; set +a
uv run python -m scripts.import_watch_specs            # dry run — default, writes nothing
uv run python -m scripts.import_watch_specs --apply    # write
```

Ordering, which is the part that matters:

1. **After** `uv run alembic upgrade head` — the columns must exist.
2. **Again, immediately before** the announcement producer's first publish (archiver#141).
   Watcher stays authoritative in between and its values can still change, so a snapshot taken
   only at step 1 would be announced stale. The pass is idempotent, so the re-run is free.
3. **Before** archiver#142 deletes the SDK. After that the source values are unreadable.

A dry run prints a per-item mapping table — InfoItem, WatchedItem, disposition, resolved policy.
That table **is** the verification artefact the acceptance criterion asks for: read it against the
live WatchedItems before running `--apply`.

Exit codes: `0` clean · `1` completed with anomalies · `2` could not run (Watcher not configured).
Three things raise an anomaly, and the first is the one that fired on the production run:

- **an InfoItem with no WatchedItem** — Watcher has no counterpart, so nothing was imported for it
- a `watcher_item_id` mismatch (Watcher's link wins; the row still imports)
- an unusable `default_schedule_config`, or a failed lookup or write

It commits per row, so a transient Watcher failure or a failed write skips one item rather than
discarding the pass; re-running picks up where it left off.

## Environment variable reference

**Key variables:**
- `ARCHIVER_DATABASE_URL` — PostgreSQL connection (falls back to `DATABASE_URL`).
- `TEST_DATABASE_URL` — separate test database. **Must not equal `ARCHIVER_DATABASE_URL` or `DATABASE_URL`** — teardown drops the entire `information` schema. Convention: database name **must** end in `_test` (e.g. `archiver_test`) — `scripts/dev_server.sh` enforces the suffix, and `conftest.py` asserts non-equality at collection time and fails fast if violated.
- `ARCHIVER_ALLOW_PRODUCTION_DB` — *optional*. `1` permits the process to serve a database whose name lacks a `_test`/`_dev` suffix. **Only `deploy/archiver.service` sets it.** Without it `src/core/db_safety.py` refuses to start at lifespan, so a hand-rolled `uvicorn` cannot reach the production registry no matter which env files it sourced (2026-07-18 incident). Never set this in `/etc/archiver/.env` or `.env` — putting it in an env file would re-open the hole for every process that sources them.
- `ARCHIVER_DEV_DATABASE_URL` — *optional*. Persistent dev database for `scripts/dev_server.sh`; wins over `TEST_DATABASE_URL`. Use when pytest's `DROP SCHEMA` teardown wiping your dev data mid-session becomes annoying. Name must end in `_test`/`_dev`.
- `ARCHIVER_DEV_PORT` — *optional*. Dev server port, default `8021`. `8020` is refused (systemd's). See **Server Lifecycle**.
- `ARCHIVER_REDIS_URL` — *optional*. When set, enables the outbox publisher background task that drains `changes_outbox` rows to the `info.changes` Redis Stream. Unset → publisher is silently disabled (degraded mode for local dev without Redis). **Archiver operates the local `redis-server` broker** (archiver#109 — it is the change-bus producer + cluster control-plane); see `deploy/redis-server.dropin.conf`, `deploy/README.md`, and the design note `docs/plans/2026-07-29-redis-bus-ownership-design.md`. The connection string is the only switch — `rediss://user:pass@host:port/db` moves to a managed provider with no code change (`RedisAsync.from_url` handles TLS + auth). `archiver.service` orders after `redis-server` (`Wants=`/`After=`, soft — the outbox tolerates broker downtime) and an `ExecStartPre` (`scripts/check_redis_floor.sh`) asserts the ≥7.0 server floor when the bus is active, plus a warn-only check that the live `maxmemory` is non-zero.

  **Lockstep invariant (archiver#128) — spans `deploy/` and `src/`.** The drop-in's `--maxmemory` cap and `OutOfMemoryError` being listed in `_TRANSIENT_PUBLISH_ERRORS` (`src/core/changes/publisher.py`) are **one decision; never change either alone.** `maxmemory-policy noeviction` with the default `maxmemory 0` is inert — nothing is ever refused, so an untrimmed stream is OOM-killed rather than erroring. The cap restores bounded, instance-wide `OOM command not allowed` errors; the transient classification is what stops those from dead-lettering valid `info.changes` events (`OutOfMemoryError` is a `ResponseError` subclass, so the default "possibly-permanent" branch would otherwise catch it). Removing the cap makes the classification pointless; removing the classification makes the cap lossy. The blast radius is instance-wide — **every** producer on the shared broker is refused, and only Archiver's is known to retry.
- `ARCHIVER_REDIS_STREAM_MAXLEN` — *optional*. Approximate cap on the `info.changes` stream (default `100000`; `≤0` disables; an **invalid value falls back to the default** rather than disabling the publisher). The outbox publisher periodically issues `XTRIM info.changes MAXLEN ~ N` so the stream stays bounded before a consumer (Replicator, Phase 3) exists. Operator-side retention rather than co-core's XADD-time trim (`BusPublish.maxlen`, cannobserv#285) is a deliberate choice for this fact stream — rationale in the `TRIM_INTERVAL_ITERATIONS` comment in `src/core/changes/publisher.py`.
- `ARCHIVER_REGISTRY_SNAPSHOT_INTERVAL` — *optional*. Seconds between `info.registry` full-set republishes (default `3600`; invalid or `≤0` falls back). The period bounds the failure cases (trimmed stream, dead-lettered delta, cold-starting consumer) — healthy-delta convergence is outbox latency, sub-second.
- `ARCHIVER_REGISTRY_STREAM_MAXLEN` — *optional*. Approximate cap carried on **every** `info.registry` publish via `BusPublish.maxlen` (default `50000`; invalid or `≤0` falls back — never unbounded). This stream is deliberately **excluded** from the periodic `XTRIM`: consumers replay from `0-0`, so retention is a consumer contract whose floor is one full set plus the deltas since. Size from key count × sets retained, never from the `info.changes` number.
- `ARCHIVER_REDIS_FLOOR_TIMEOUT` — *optional*. Seconds (default `5`) bounding **each** broker probe in `scripts/check_redis_floor.sh` — the version floor and the live-`maxmemory` check — at the `archiver.service` `ExecStartPre`. `redis-cli` has no connect-timeout flag, so each probe is wrapped in `timeout`; this prevents a `rediss://`-vs-plaintext (or unreachable) endpoint from hanging archiver startup — a timeout yields a soft-skip, never a block.
- `ARCHIVER_BUS_CONSUMER` — *optional*. `1` opts this process into the `archiver.revisions` consumer group on `content.revisions` (archiver#139). **Only `deploy/archiver.service` sets it**, and — like `ARCHIVER_ALLOW_PRODUCTION_DB` — it must **never** appear in `/etc/archiver/.env` or `.env`, or every process that sources them joins the group. The asymmetry with the publisher is the point: producing from a stray process is noisy, whereas *consuming* removes messages from the group, so a second member silently takes half the revisions and writes them into whatever database it happens to hold. Unset (or with `ARCHIVER_REDIS_URL` unset) → the consumer is dormant and the service starts with no bus-read dependency. Setting it does not affect the publisher, and a consumer that fails to start leaves the publisher running. **The `info.watch-status` tail (archiver#151) is deliberately *not* behind this gate** — it is groupless, and a stray tail removes nothing from any PEL, so `ARCHIVER_REDIS_URL` alone starts it. Do not "fix" that by adding the gate: the gate's entire meaning is group membership.
- `ARCHIVER_DEV_REDIS_URL` — *optional*. Dev change-bus broker for `scripts/dev_server.sh`. Unset → the dev server runs **bus-dormant** and never inherits prod's `ARCHIVER_REDIS_URL` from `/etc/archiver/.env` (the Redis analogue of the DB `_test`/`_dev` guard). Point it at a distinct broker or logical DB index (e.g. `.../1`); a value equal to the production URL is refused.
- `ARCHIVER_PUBLIC_BASE_URL` — *optional*. Public-facing base URL of this Archiver instance (e.g. `https://archiver.example.com`). When set, InfoItem API responses include `dashboard_url` pointing to the dashboard detail page (`{ARCHIVER_PUBLIC_BASE_URL}/info-items/{id}`). Unset → `dashboard_url` is `null`. Set this to the URL end-users open in a browser, distinct from any internal service-to-service address. Set in `/etc/archiver/.env` on the VM.
- `WATCHER_BASE_URL` — *optional*. Base URL of the sibling Watcher service for **service-to-service API calls** (e.g. `http://localhost:8000`). When set (together with `WATCHER_API_KEY`), the Archiver provisions WatchedItems on InfoItem create and patches them on primary-source swap. Unset → Watcher integration disabled; `watcher_item_id` stays `NULL` on all InfoItems. **Do not use a public proxy URL here on the same VM** — hairpin NAT means the proxy URL won't route from within the VM; use `http://localhost:<port>` instead.
- `WATCHER_PUBLIC_BASE_URL` — *optional*. Public-facing base URL of the Watcher service for **browser deeplinks** (e.g. `https://watcher.exe.xyz:8000`). When set, the dashboard's Watcher-section header deeplink ("Watcher ↗" on the InfoItem detail page) uses this URL instead of `WATCHER_BASE_URL`. Unset → falls back to `WATCHER_BASE_URL`. Set in `/etc/archiver/.env`. Analogous to `ARCHIVER_PUBLIC_BASE_URL`.
- `WATCHER_API_KEY` — *optional*. API key sent as `X-API-Key` to the Watcher service. Store in `/etc/archiver/.env`. Required when `WATCHER_BASE_URL` is set.
- `ARCHIVER_WATCHER_PUSH_ENABLED` — *optional*, default **on**. `0`/`false`/`no`/`off` disables every outbound Watcher **write** (`provision_on_create`, `sync_on_source_swap`, `sync_on_spec_update`) while leaving the client — and therefore the dashboard's Watcher deeplinks — intact. This is the archiver#158 dual-run switch: the design's step 7 calls for disabling the HTTP push and confirming policy still propagates via the announcement, and the blunt alternative (unsetting `WATCHER_BASE_URL`) would also take out unrelated reads. Default is on because the flag exists to retire an existing behaviour deliberately; defaulting off would silently disable the push on any deployment that forgot to set it. archiver#142 deletes the flag with the SDK.
- `ARCHIVER_ALLOW_WATCH_IMPORT` — *optional*. `1` arms `scripts/import_watch_specs.py --apply`. Same posture as `ARCHIVER_ALLOW_PRODUCTION_DB`: **never put it in an env file**, because sourcing the environment must not arm it. The script's writes are blind overwrites, which was safe only while the dashboard did not write `watch_spec`/`watch_active`; after the archiver#158 cutover it does, so a stray `--apply` would clobber operator-authored policy *and announce the clobber* as desired state. Dry runs stay ungated — the guard is on writing, not on looking.
- `WATCHER_CACHE_DIR`, `WATCHER_CACHE_TTL_SECONDS`, `WATCHER_CACHE_SWEEP_INTERVAL_SECONDS` — Watcher-side, not Archiver-side; documented here because the `content_cache_uri` lifecycle protocol they govern is a registry contract (see design doc Section 2).

## Sourcing env files — why not `export $(cat … | xargs)`

> Use `set -a; . <file>; set +a` (POSIX-portable source via `.`) rather than `export $(cat <file> | xargs)`. The xargs form silently breaks for values containing spaces, quotes, newlines, or embedded `=` — and produces hard-to-diagnose failures later when those env vars are read.
