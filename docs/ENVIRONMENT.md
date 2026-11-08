# archiver — Environment

**Every environment variable, the dev server's knobs, and why
`scripts/dev_server.sh` exists.** Split out of [DEPLOYMENT.md](DEPLOYMENT.md)
when that file reached twice its context budget; DEPLOYMENT.md keeps releases,
the drift check, the service user, reading production and the timers.
`AGENTS.md` keeps the five variables that carry safety rules; the reference
lives here, the change-bus ones in [ENVIRONMENT_BUS.md](ENVIRONMENT_BUS.md).

## Why `scripts/dev_server.sh` exists

**Never hand-roll the uvicorn invocation.** The recipe this replaced sourced
`/etc/archiver/.env` and then ran uvicorn directly, which left
`ARCHIVER_DATABASE_URL` pointing at **production** — the dev server on 8001 and
the live service on 8000 shared one database. On 2026-07-18 a dashboard
verification run drove the dev server and wrote a `verify79.example.com`
Domain, two InfoSources, and an AppUser into the production registry.

`scripts/dev_server.sh` resolves the dev database from
`ARCHIVER_DEV_DATABASE_URL`, else `TEST_DATABASE_URL`; refuses to start if that
resolution equals `ARCHIVER_DATABASE_URL` or `DATABASE_URL`; clears the
`DATABASE_URL` fallback; refuses port 8000; and runs `alembic upgrade head`
against the dev database before serving. It takes only `ARCHIVER_DEV_*` and
`TEST_DATABASE_URL` from the repo `.env`, never `/etc/archiver/.env`
([DEPLOYMENT.md](DEPLOYMENT.md) § Parse env files, never source them), and
unsets the `GH_TOKEN` an agent session inherits from `gh-env.sh` (#466). This mirrors `_check_test_url_safety`
in `tests/conftest.py`, which guards pytest but not a hand-run server.

## Dev-server knobs

| Knob | Effect |
|---|---|
| `ARCHIVER_DEV_DATABASE_URL` | Persistent dev DB; wins over `TEST_DATABASE_URL` |
| `ARCHIVER_DEV_REDIS_URL` | Dev change-bus broker. Unset → dev runs bus-dormant (prod's `ARCHIVER_REDIS_URL` is never inherited); refused if on prod's `host:port`, whatever the DB index |
| `ARCHIVER_DEV_PORT` | Default 8001; 8000 is refused |
| `ARCHIVER_DEV_SKIP_MIGRATE=1` | Skip the alembic upgrade |
| `ARCHIVER_DEV_POWER_MAP_API_KEY` | Dev Power Map read key. Unset → Power Map dormant on dev (prod's `ARCHIVER_POWER_MAP_API_KEY` is never inherited) |
| `ARCHIVER_DEV_POWER_MAP_BASE_URL` | Dev Power Map base URL; default production Power Map |

> pytest teardown runs `DROP SCHEMA information CASCADE` against
> `TEST_DATABASE_URL`. A dev server pointed at the same database therefore
> loses its data mid-suite — survivable, and strictly better than writing to
> production, which is the failure the fallback was chosen to avoid.
>
> **`archiver_dev` now exists and `ARCHIVER_DEV_DATABASE_URL` is set** (#193
> D5), so the fallback is no longer the normal case on this host.

## Environment variable reference

**Key variables:**
- `ARCHIVER_DATABASE_URL` — PostgreSQL connection (falls back to `DATABASE_URL`).
- `TEST_DATABASE_URL` — separate test database. **Must not equal `ARCHIVER_DATABASE_URL` or `DATABASE_URL`** — teardown drops the entire `information` schema. Convention: database name **must** end in `_test` (e.g. `archiver_test`) — `scripts/dev_server.sh` enforces the suffix, and `conftest.py` asserts both non-equality and the `_test` suffix at collection time, failing fast. The suffix is the rule that holds in an agent shell, which cannot read the production URL to compare (#339). Role `archiver_agent`.
- `ARCHIVER_ALLOW_PRODUCTION_DB` — *optional*. `1` permits the process to serve a database whose name lacks a `_test`/`_dev` suffix. **Only `deploy/` units set it**: `archiver.service`, `archiver-bus-health.service` (read-only, #130), `archiver-pm-org-refresh.service` (#305) and `archiver-temporal-boundary.service` (#365) - **and `scripts/deploy.sh`**, for the production `schema_state` check, `alembic upgrade head` and the read role's grants it runs (archiver#330, #348). `alembic/env.py` and `src/core/schema_state.py` refuse production without it, as the API does. Without it `src/core/db_safety.py` refuses to start at lifespan, so a hand-rolled `uvicorn` cannot reach the production registry no matter which env files it sourced (2026-07-18 incident). Never set this in `/etc/archiver/.env` or `.env` — putting it in an env file would re-open the hole for every process that sources them.
- `ARCHIVER_DEV_DATABASE_URL` — *optional in code, set in practice*. Persistent dev database for `scripts/dev_server.sh`; wins over `TEST_DATABASE_URL`. Points at `archiver_dev` on this host (#193 D5), as role `archiver_agent`, like `TEST_DATABASE_URL` (#339). Leaving it unset falls back to the test database, where pytest's `DROP SCHEMA` teardown wipes dev data mid-session. Name must end in `_test`/`_dev`. `scripts/deploy.sh` reads it from `/etc/archiver/dev.env` (never the shell) to rehearse each migration before production sees it (archiver#330 D2).
- `ARCHIVER_DEV_PORT` — *optional*. Dev server port, default `8001`. `8000` is refused (systemd's). See **Server Lifecycle**.
- **The change-bus variables** (the outbox publisher, the stream caps, the reaper, issuance, the producer and consumer opt-ins): `ARCHIVER_REDIS_URL`, `ARCHIVER_REDIS_STREAM_MAXLEN`, `ARCHIVER_OUTBOX_RETENTION_DAYS`, `ARCHIVER_REGISTRY_SNAPSHOT_INTERVAL`, `ARCHIVER_REPLICATION_REAP_INTERVAL`, `ARCHIVER_REPLICATION_REAP_HORIZON`, `ARCHIVER_PERSIST_ISSUANCE`, `ARCHIVER_REGISTRY_STREAM_MAXLEN`, `ARCHIVER_REDIS_FLOOR_TIMEOUT`, `ARCHIVER_FETCH_POLICY_PRODUCER`, `ARCHIVER_FETCH_POLICY_STREAM_MAXLEN`, `ARCHIVER_WATCH_CHECK_ENABLED`, `ARCHIVER_WATCH_CHECK_TIMEOUT_SECONDS`, `ARCHIVER_BUS_CONSUMER`. [ENVIRONMENT_BUS.md](ENVIRONMENT_BUS.md).
- `ARCHIVER_DEV_REDIS_URL` — *optional*. Dev change-bus broker for `scripts/dev_server.sh`. Unset → the dev server runs **bus-dormant** and never inherits prod's `ARCHIVER_REDIS_URL` from `/etc/archiver/.env` (the Redis analogue of the DB `_test`/`_dev` guard). The supported posture is **dormant, or a local throwaway broker** — `docker run --rm -p 127.0.0.1:6380:6379 redis:7` with `ARCHIVER_DEV_REDIS_URL=redis://127.0.0.1:6380/0` (≥ 7.0, the `check_redis_floor.sh` floor). A value on production's `host:port` is refused **whatever its DB index** (archiver#240), and so is any broker that isn't loopback or a unix socket (#339): an agent shell no longer holds production's URL to compare against.

  **Do not re-add a `.../1` recommendation: a logical DB index is not a boundary** ([BUS_CLIENT.md](BUS_CLIENT.md#the-broker-boundary)).
- `ARCHIVER_POWER_MAP_API_KEY` — *optional*. Archiver's **read-only** Power Map key (archiver#304), sent as `X-API-Key`. **The switch**: unset → Power Map features are dormant, `PUT /info-items/{id}/org` and a create with `pm_org_id` answer 503 "Power Map not configured", and nothing else changes — rendering and replication read only the local `pm_organizations` snapshot, never Power Map. Set in `/etc/archiver/.env`; takes effect on restart. It is also the follower's switch: `archiver-pm-org-refresh.service` exits 0 without touching the database when it is unset (see [DEPLOYMENT.md](DEPLOYMENT.md#timers) § Timers). `scripts/dev_server.sh` never passes it through (see `ARCHIVER_DEV_POWER_MAP_API_KEY`); the test suite scrubs it.
- `ARCHIVER_POWER_MAP_BASE_URL` — *optional*. Power Map's base URL, default `https://power-map.exe.xyz` (public HTTPS, no tailnet hop). Read only when the key is set.
- `ARCHIVER_DEV_POWER_MAP_API_KEY` / `ARCHIVER_DEV_POWER_MAP_BASE_URL` — *optional*, dev only. What `scripts/dev_server.sh` exports as the two above; unset → the dev server runs Power Map-dormant. Unlike the Redis guard there is no same-target refusal: the key is read-only and dev writes only `archiver_dev`, so reading production Power Map from 8001 is the supported posture. Only inheriting the service's credential is refused. Set in the repo `.env`.
- `CO_ARCHIVER_DRIFT_MONITOR_ID` — the drift check's co-status monitor, `co-archiver-drift` (archiver#338). Not a secret: set in `deploy/archiver-drift.service`, never an env file. Must be a ULID (it lands in a URL path); anything else exits 2. Unset → the check runs, logs that nothing was sent, exits 1. Scrubbed by `tests/conftest.py`: no test may hold the real one (§ The drift check).
- `ARCHIVER_STATUS_URL` — *optional*. co-status's base URL for the drift check, the backup and the service's liveness heartbeat, default `http://status:9000` (MagicDNS over the tailnet). Its key is never an env var: the units' `status-checkin-key` credential.
- `CO_ARCHIVER_LIVE_MONITOR_ID` — the service's liveness monitor, `co-archiver-live` (archiver#297, CannObserv/status#47). Set only in `deploy/archiver.service`, never an env file: a hand-run server holding it (and the key) would check in `ok` for production and hide a real outage. Unset → `liveness: off`; not a ULID, or no `status-checkin-key` credential → off at ERROR, and the service runs regardless. `scripts/dev_server.sh` drops it and `CREDENTIALS_DIRECTORY` whatever it inherits; `tests/conftest.py` scrubs both ([MONITORING.md](MONITORING.md) § Liveness).
- `CO_ARCHIVER_BACKUP_MONITOR_ID` — the backup's co-status monitor, `co-archiver-backup` (archiver#233). `01M4XBGKAD52BN3J69B7AX95GS`, set in `deploy/archiver-backup.service`, never an env file (CannObserv/status#41). Unset → the backup runs, warns that a stop will go unnoticed, and sends nothing. Scrubbed by `tests/conftest.py`.
- `ARCHIVER_BACKUP_BUCKET` — the backup's and the restore's bucket, `co-gcs-archiver-backup`. Set in the unit; given by hand to a restore. No default: unset is exit 2. Scrubbed by `tests/conftest.py`.
- `ARCHIVER_BACKUP_PREFIX` — *optional*. The object prefix; default this host's name (`co-registrar`), so a replacement host never writes into the timeline it restores from.
- `GOOGLE_APPLICATION_CREDENTIALS` — the GCS key's path, for the wheel fetch (`/etc/archiver/deploy.env`) and the backup, where only the unit's own `%d/gcs` is accepted ([BACKUP.md](BACKUP.md)). Scrubbed by `tests/conftest.py`.
- `ARCHIVER_API_KEY` — read only by the operator-run Watcher imports (`python -m src.core.tools.import_watcher_domains`, archiver#360; `…import_watcher_item_cadence`, archiver#364): the `X-API-Key` it sends to `--base-url`, which has no default. Supplied inline per run, never in an env file. Scrubbed by `tests/conftest.py`.
- `ARCHIVER_PUBLIC_BASE_URL` — *optional*. The **origin** people open in a browser (`https://co-registrar.exe.xyz`), never an internal address. API `dashboard_url` is `{origin}/dashboard/info-items/{id}`; notifications' `app_url`/`change_url` come from the same helper (`src/core/public_base_url.py`). Unset, or anything but `http(s)://host[:port]` (a path, query, userinfo) → no link (`dashboard_url` `null`). Set as `deploy/archiver.service`'s own `Environment=` line; `/etc/archiver/.env` must not carry it, since `EnvironmentFile=` would win.
- `ARCHIVER_NOTIFIER_ENABLED`, `ARCHIVER_NOTIFIER_BASE_URL`, `ARCHIVER_NOTIFIER_API_KEY` — the Notifier gate (archiver#368, `src/core/notifier/gate.py`). The flag opts in only as exactly `1`; only `deploy/archiver.service` and `scripts/dev_server.sh` (beside a dev pair) set it, never an env file. The URL is the unit's own `Environment=` line. Production's key is the `notifier-key` systemd credential only: an env key aimed at `:9000` is refused. Neither flag nor URL → dormant; every half-configuration refuses startup. Scrubbed by `tests/conftest.py`. [NOTIFICATIONS.md](NOTIFICATIONS.md#the-credential).
- `ARCHIVER_DEV_NOTIFIER_BASE_URL` / `ARCHIVER_DEV_NOTIFIER_API_KEY` — *optional*, dev only, in the repo `.env`. `scripts/dev_server.sh` maps the pair onto the URL and key above and sets the flag only beside both; one alone → dormant; a dev URL on `:9000` is refused. Scrubbed by `tests/conftest.py`.
- `ARCHIVER_PROCESSOR_TEXT_BUCKET` — the bucket change-diff texts are read from, `co-gcs-processor`; set only by `deploy/archiver.service` (#367). A URI naming another bucket is never read. Unset → no reader, every diff unavailable. Its key is the `processor-text-reader` credential, never `GOOGLE_APPLICATION_CREDENTIALS`. Scrubbed by `tests/conftest.py`. [NOTIFICATION_COMPOSER.md](NOTIFICATION_COMPOSER.md#the-processor-text-reader-srccorenotificationsdiff_loaderpy).
- `ARCHIVER_DIFF_MAX_INPUT_BYTES` — *optional*. Caps each side's text (default `1048576`, 1 MiB); non-positive or non-integer keeps the default with a WARNING (`src/core/notifications/diff_loader.py`).
- `ARCHIVER_NOTIFY_CUTOVER_AT` — the cutover instant T (archiver#369 D3), ISO 8601 UTC (`…Z` or `+00:00`). Rows for facts at or after T send; unset, every row is shadow. **`deploy/archiver.service`'s own `Environment=` line, set at F3, never an env file.** T without the Notifier gate, or not a UTC instant, refuses startup. Scrubbed by `tests/conftest.py`. [NOTIFICATIONS.md](NOTIFICATIONS.md#dispatch-on-events-archiver369).
- `ARCHIVER_DEV_NOTIFY_CUTOVER_AT` — *optional*, dev only. `scripts/dev_server.sh` maps it onto T only beside a mapped dev Notifier pair; the unit's T is never inherited.
- `ARCHIVER_ERROR_RENOTIFY_INTERVAL` — *optional*. How long an open error episode waits between reminders (default `24h`; `30s`/`15m`/`6h`/`1d`; malformed keeps the default with a WARNING, as Watcher's did).
- `ARCHIVER_NOTIFY_RETENTION_DAYS` — *optional*. Days a terminal `notification_dispatches` row is kept (default `90`, outliving F3's parity window; `≤0` keeps every row; invalid keeps the default). `pending` is never pruned.
- `WATCHER_CACHE_DIR`, `WATCHER_CACHE_TTL_SECONDS`, `WATCHER_CACHE_SWEEP_INTERVAL_SECONDS` — Watcher-side, not Archiver-side; documented here because the `content_cache_uri` lifecycle protocol they govern is a registry contract (see design doc Section 2).

**Retired with the Watcher HTTP edge (archiver#142).** `WATCHER_BASE_URL`,
`WATCHER_PUBLIC_BASE_URL`, `WATCHER_API_KEY`, `ARCHIVER_WATCHER_PUSH_ENABLED`,
and `ARCHIVER_ALLOW_WATCH_IMPORT` are no longer read by anything. Archiver has no
outbound HTTP edge to Watcher at all — policy travels on `info.registry`, status
returns on `info.watch-status` — so there is no base URL to configure, no key to
present, and no push to gate. **Delete them from `/etc/archiver/.env`**: a stale
credential that nothing reads is still a credential on disk, and a leftover
`ARCHIVER_WATCHER_PUSH_ENABLED=0` reads as a live switch to whoever finds it next.

## Adding a new outbound env var

Any variable that *addresses an external resource* - a `*_URL`, `*_API_KEY`,
`*_TOKEN`, `*_DSN` - must be registered when it is added, not later:

1. Add it to `_OUTBOUND_SERVICE_ENV_VARS` in `tests/conftest.py`, so a suite run
   that sourced `/etc/archiver/.env` cannot inherit the live resource.
2. If a test process may legitimately hold it, add it to
   `_OUTBOUND_ENV_ALLOWLIST` in `tests/outbound_env_audit.py` **with the reason**
   - naming the other mechanism that contains it, so the exemption can be
   re-checked when that mechanism changes. An empty reason is rejected.
3. Spell the read as a string literal or a module-level constant. A computed
   name (`os.environ.get(f"{prefix}_URL")`) cannot be resolved statically, so
   `test_no_env_read_escapes_static_resolution` fails rather than let it pass by
   being invisible to the registry check.

`test_every_outbound_env_var_is_accounted_for` turns forgetting step 1 or 2 into
a test failure. It scans `src/` **and** `alembic/` - `tests/conftest.py` runs
`alembic upgrade head` in-process at session setup, so `alembic/env.py` reads the
environment under pytest exactly as the application does. `scripts/` is out of
scope: those run by hand or in CI, never inside the test process.

The guard exists because its predecessor could only iterate the list it was
given, and so was blind to a variable that never made the list. That is precisely
how the same hole re-opened in a sibling service (CannObserv/watcher#277: a
notifier client read `NOTIFIER_BASE_URL`/`NOTIFIER_API_KEY`, the conftest scrub
never gained them, and a prod-sourced pytest run dispatched to production
silently). Archiver's #157 was that shape under an earlier name.
