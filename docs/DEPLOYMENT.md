# archiver — Deployment & Configuration

Releases and `scripts/deploy.sh`, wheelhouse reproducibility, dev-server internals,
and the full environment variable reference. `AGENTS.md` keeps the safety rules; the reference lives here.
The host's place on the tailnet - node identity, the ACL, why there is no
tailnet-only bind - is [reference/tailscale.md](reference/tailscale.md).

## Releases (archiver#330)

**Production runs a release, never a checkout.** Design and reasons:
[plans/2026-10-09-330-deploy-releases-design.md](plans/2026-10-09-330-deploy-releases-design.md)
(D1-D12), adopted from CannObserv/status's R1-R13.

```
/srv/archiver/                 root:root 0755
  releases/<build>/            git archive of one origin/main commit + its own .venv;
                               root's, read-only; REVISION (12-char SHA) written last
  live -> releases/<build>     archiver.service, archiver-bus-health, archiver-pm-org-refresh
```

- **Nothing done in `/home/exedev/archiver` reaches a unit**: branch switches, uncommitted
  edits, `uv sync`, hook commits. Units run `uv run --frozen --no-sync` from
  `/srv/archiver/live`, read `/etc/archiver/.env` only, and stamp nothing: `/health`'s
  `build_id` is the release's `REVISION`.
- **Root owns the root, `releases/` and each finished release** (status#14): changing what a
  unit runs takes `sudo`, which journals the command. Not a boundary against `exedev`.
- **The venv is copied** (`--link-mode copy`), not hardlinked to `~/.cache/uv`, on
  `/usr/bin/python3.12`; the private wheels are fetched into the release and removed once
  the venv is built (D10).

### `scripts/deploy.sh`

Run as `exedev`, from the checkout, after the PR merges. It fetches `origin` itself.

```bash
scripts/deploy.sh                       # origin/main, once its CI passed
scripts/deploy.sh <build>               # any origin/main commit with green CI: a rollback
scripts/deploy.sh --skip-ci [<build>]   # without asking CI: an emergency, logged
journalctl -t archiver-deploy -n 20     # "CI passed for <build>", "live -> <build> (was ...)"
```

In order, each step refusing before anything switches:

1. **CI gate** (D6): the newest `push` run of `ci.yml` on `main` for exactly that commit,
   every job `success`, `lint test client-drift changelog` among them. Pending waits up to
   10 min; a commit with no run (not the tip of its push) is refused. Unauthenticated: the
   repo is public.
2. **Build** `releases/<build>`, or reuse a finished one whose venv imports: `git archive`;
   the release's `scripts/sync_wheelhouse.py` with `GOOGLE_APPLICATION_CREDENTIALS` from
   `/etc/archiver/deploy.env`; `uv sync --locked --no-dev`; one Alembic head; **every unit's
   `ExecStart` module imports** (D11, the 2026-10-08 failure); read-only; root's; `REVISION`.
   The release `live` runs is never rebuilt in place.
3. **Rehearse** (D2): `python -m src.core.schema_state`, then `alembic upgrade head`, against
   `ARCHIVER_DEV_DATABASE_URL` from `/etc/archiver/dev.env`. `ahead` there means a branch
   migration from a worktree's `dev_server.sh` that never merged: downgrade it, or the
   rehearsal rehearses nothing.
4. **Migrate** `archiver` the same way, with `ARCHIVER_ALLOW_PRODUCTION_DB=1`; skipped when
   the schema is `ahead` (a rollback). Migrations are **expand-only** (D3): the old release
   runs on the new schema between this step and the switch, and after any rollback.
5. **Switch** `live` (rename(2)), then **install the units that differ** from the release,
   one `daemon-reload`, `try-restart` for a changed timer. A new unit is installed, never
   enabled: the deploy prints the `enable --now` it needs.
6. **Restart** `archiver`, wait out a running `archiver-bus-health` pass, force one, and
   **verify**: `/health` `build_id` is `<build>` and `schema_state` can serve, within
   `ARCHIVER_DEPLOY_VERIFY_SECONDS` (120). `archiver-pm-org-refresh` is never forced (D4).
7. **On failure**, switch back - link and units - `reset-failed`, restart, prove the old
   build. Exit 1 when it answers, 4 when it does not. The migration stays.

Then host configs under `deploy/` are compared with their installed copies (a difference is a
note, never an install), and releases beyond the 5 newest are pruned, never the linked one.

| Variable | Default | What |
|---|---|---|
| `ARCHIVER_DEPLOY_ROOT` | `/srv/archiver` | releases and the `live` link |
| `ARCHIVER_DEPLOY_ENV_DIR` | `/etc/archiver` | `.env` (units), `dev.env` (rehearsal), `deploy.env` (wheel fetch) |
| `ARCHIVER_DEPLOY_ETC` | `/etc` | units in `systemd/system/`; host configs compared there |
| `ARCHIVER_DEPLOY_KEEP` | `5` | releases kept besides the linked one |
| `ARCHIVER_DEPLOY_VERIFY_SECONDS` | `120` | `/health` and the schema must answer within it |
| `ARCHIVER_DEPLOY_PROBE_WAIT_SECONDS` | `90` | how long to wait out a running bus-health pass |
| `ARCHIVER_DEPLOY_CI_WAIT_SECONDS` / `_POLL_SECONDS` | `600` / `30` | the CI gate's wait |
| `ARCHIVER_DEPLOY_PYTHON` | `/usr/bin/python3.12` | the interpreter each venv is built on |

**Hand-run alembic against production is refused** unless `ARCHIVER_ALLOW_PRODUCTION_DB=1`
(D9); against dev, unset `ARCHIVER_DATABASE_URL` and set `DATABASE_URL` to the dev URL.
**A hand edit of an installed unit lasts until the next deploy**, which replaces it and says
so; put the fix in `deploy/`. `tests/deploy/` compares installed units with the live release.

### First deploy (the cutover, once per VM)

Operator-present. The first deploy has no release to switch back to: on a failed verify it
puts back the checkout-backed units it replaced, removes `live` and restarts on them (exit 1
when archiver answers, 4 when not).

```bash
sudo install -d -m 755 -o root -g root /srv/archiver
# The rehearsal URL, copied from the repo .env: never typed, so never in history.
grep '^ARCHIVER_DEV_DATABASE_URL=' /home/exedev/archiver/.env | sudo tee /etc/archiver/dev.env >/dev/null
printf 'GOOGLE_APPLICATION_CREDENTIALS=/etc/archiver/co-pypi-reader.json\n' \
    | sudo tee /etc/archiver/deploy.env >/dev/null
sudo chown root:exedev /etc/archiver/dev.env /etc/archiver/deploy.env
sudo chmod 640 /etc/archiver/dev.env /etc/archiver/deploy.env
cd /home/exedev/archiver && git switch main && git pull --ff-only
scripts/deploy.sh
curl -s http://127.0.0.1:8000/health; readlink /srv/archiver/live
```

Then prove the point: `git switch` the checkout to any branch, `sudo systemctl restart
archiver` and start both timers' services; `build_id` is unchanged. Then delete
`.skills/worktree_venv` (the checkout's `.venv` is no longer production's) and remove
`GOOGLE_APPLICATION_CREDENTIALS` from `/etc/archiver/.env`: no unit needs it.

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
Identity Federation; `scripts/deploy.sh` fetches it into each release (§ Releases). No git sources and
no `cannobserv`/`co-core-sync` (heavy google/trello deps). Archiver depends on
**`co-core[extract]`** + `co-core-aio` — the authoring tools use `co_core_aio.fetch`
(fetch) and `co_core.pure.extract` (extract + fingerprint); see "Content-acquisition
via co-core".

## Power Map SDK (git tag)

`power-map-client` (archiver#304) is **not** a wheelhouse package: it resolves as a uv git
source, `https://github.com/CannObserv/power-map.git`, `subdirectory = "clients/python"`, pinned
to a release tag (`[tool.uv.sources]` in `pyproject.toml`). The repo is public, so no credential;
`uv.lock` pins the tag's commit. **The CI and deploy hosts need outbound github.com** for
`uv sync`. Client and server share one version; live Power Map reports it as `build` on `/health`.
Only `src/core/power_map/client.py` imports it (a guard test enforces that).

Upgrade: bump `tag` to the new release, read that release's diff of `clients/python/openapi.json`
in Power Map for changed status codes or fields the adapter maps, `uv sync`, run the adapter tests
(`tests/core/power_map/`).

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
against the dev database before serving. This mirrors `_check_test_url_safety`
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
> D5), so the fallback is no longer the normal case on this host. The knob had
> always been honoured; there was simply never a database for it to name, so
> every dev server and every test run shared one and raced. Provisioning a
> dedicated VM was the moment to close that rather than port it.

## Timers

Periodic oneshots under `deploy/`, each holding its own
`ARCHIVER_ALLOW_PRODUCTION_DB=1`. Install, behaviour and logs:
[deploy/README.md](../deploy/README.md).

| Timer | Cadence | Runs | Writes | Dormant when |
|---|---|---|---|---|
| `archiver-bus-health` | 10 min | `python -m src.core.bus_health` | nothing (WARN-only outbox and schema probe, #130, #330) | never |
| `archiver-pm-org-refresh` | 1 h | `python -m src.core.tools.refresh_orgs` | `pm_organizations`; `info_items.pm_org_id` on a merge (#305) | `ARCHIVER_POWER_MAP_API_KEY` unset: exits 0, no database |

## Environment variable reference

**Key variables:**
- `ARCHIVER_DATABASE_URL` — PostgreSQL connection (falls back to `DATABASE_URL`).
- `TEST_DATABASE_URL` — separate test database. **Must not equal `ARCHIVER_DATABASE_URL` or `DATABASE_URL`** — teardown drops the entire `information` schema. Convention: database name **must** end in `_test` (e.g. `archiver_test`) — `scripts/dev_server.sh` enforces the suffix, and `conftest.py` asserts non-equality at collection time and fails fast if violated.
- `ARCHIVER_ALLOW_PRODUCTION_DB` — *optional*. `1` permits the process to serve a database whose name lacks a `_test`/`_dev` suffix. **Only `deploy/` units set it**: `archiver.service`, `archiver-bus-health.service` (read-only) and `archiver-pm-org-refresh.service` (the Power Map org follower, archiver#305). Without it `src/core/db_safety.py` refuses to start at lifespan, so a hand-rolled `uvicorn` cannot reach the production registry no matter which env files it sourced (2026-07-18 incident). Never set this in `/etc/archiver/.env` or `.env` — putting it in an env file would re-open the hole for every process that sources them.
- `ARCHIVER_DEV_DATABASE_URL` — *optional in code, set in practice*. Persistent dev database for `scripts/dev_server.sh`; wins over `TEST_DATABASE_URL`. Points at `archiver_dev` on this host (#193 D5). Leaving it unset falls back to the test database, where pytest's `DROP SCHEMA` teardown wipes dev data mid-session. Name must end in `_test`/`_dev`.
- `ARCHIVER_DEV_PORT` — *optional*. Dev server port, default `8001`. `8000` is refused (systemd's). See **Server Lifecycle**.
- `ARCHIVER_REDIS_URL` — *optional*. When set, enables the outbox publisher background task that drains `changes_outbox` rows to the `info.changes` Redis Stream. Unset → publisher is silently disabled (degraded mode for local dev without Redis). **Archiver no longer operates the broker** — archiver#193 D6 moved it to a neutral node and its operational code to [CannObserv/broker](https://github.com/CannObserv/broker); the cluster stream inventory is that repo's `docs/STREAMS.md`. The connection string is the only switch — write it as `redis://default:<password>@broker:6379/0`, with `default:` explicit: the empty-username form authenticates for redis-py and fails for `redis-cli`, so the service comes up green while `scripts/check_redis_floor.sh` goes silently blind on the floor (archiver#195). `archiver.service` declares **no** `redis-server` ordering — it was removed, not loosened, when the broker left the host (CannObserv/broker#1 Phase 3) — and an `ExecStartPre` (`scripts/check_redis_floor.sh`) asserts the ≥7.0 server floor when the bus is active, plus a warn-only check that the live `maxmemory` is non-zero.

  **Lockstep invariant (archiver#128) — now spans two REPOSITORIES (archiver#193 R5).** The broker config's `maxmemory` cap and `OutOfMemoryError` being listed in `_TRANSIENT_PUBLISH_ERRORS` (`src/core/changes/publisher.py`) are **one decision; never change either alone.** The cap now lives in `CannObserv/broker:deploy/redis.conf.broker`, so no test spans the pair — each side names the other in a comment and that is the whole mechanism. It rode a systemd drop-in overriding `ExecStart` while this repo tuned the broker; broker#1 Phase 5 appended it to `redis.conf` instead, because `requirepass` cannot ride an `ExecStart` argument without landing in `argv` and journald, and splitting the rest of the tuning across two mechanisms then buys nothing (archiver#196). `redis.conf.broker` is **not** a drop-in. `maxmemory-policy noeviction` with the default `maxmemory 0` is inert — nothing is ever refused, so an untrimmed stream is OOM-killed rather than erroring. The cap restores bounded, instance-wide `OOM command not allowed` errors; the transient classification is what stops those from dead-lettering valid `info.changes` events (`OutOfMemoryError` is a `ResponseError` subclass, so the default "possibly-permanent" branch would otherwise catch it). Removing the cap makes the classification pointless; removing the classification makes the cap lossy. The blast radius is instance-wide — **every** producer on the shared broker is refused, and every durable path retries through it: Archiver's outbox via this entry, Watcher's and Replicator's as verified in CannObserv/watcher#288 and CannObserv/replicator#79. At the cap the bus stalls rather than losing those writes. The periodic full-set publishes do not retry - `info.registry` snapshots, and Watcher's `content.fetch-policy` and `info.watch-status` - because the next period supersedes a lost one.
- `ARCHIVER_REDIS_STREAM_MAXLEN` — *optional*. Approximate cap on the `info.changes` stream (default `100000`; `≤0` disables; an **invalid value falls back to the default** rather than disabling the publisher). The outbox publisher periodically issues `XTRIM info.changes MAXLEN ~ N` so the stream stays bounded before a consumer (Replicator, Phase 3) exists. Operator-side retention rather than co-core's XADD-time trim (`BusPublish.maxlen`, cannobserv#285) is a deliberate choice for this fact stream — rationale in the `TRIM_INTERVAL_ITERATIONS` comment in `src/core/changes/publisher.py`.

  **Setting this obliges a note to [CannObserv/broker](https://github.com/CannObserv/broker).** Their bus-health probe mirrors the *default* (`DEFAULT_STREAM_MAXLEN`, `src/core/changes/publisher.py`) as `FACT_PRODUCER_MAXLEN`, and derives a stream-too-long warning threshold from it. Naming the source is not enough when an env var can move it underneath — an override here leaves their threshold stale with no commit in either repo (the CannObserv/broker#44 failure mode, agreed with broker-agent 2026-09-23). Unset in production as of 2026-09-23, so the mirror is correct today.
- `ARCHIVER_OUTBOX_RETENTION_DAYS` — *optional*. Days a **published** `changes_outbox` row is kept before the drain loop's retention pass deletes it (default `30`; `≤0` disables pruning entirely; an **invalid value falls back to the default** rather than disabling the publisher, same contract as the trim cap). Sized against what a published row is still good for: correlating its `bus_message_id` to an entry on `info.changes`, which is itself capped. Live rows (the drain's queue) and dead-lettered rows (the archiver#107 post-mortem record) are never pruned at any setting. Rides the publisher rather than a systemd timer so it needs no further sanctioned `ARCHIVER_ALLOW_PRODUCTION_DB` holder — see `src/core/changes/outbox_prune.py` and [BUS.md](BUS.md).
- `ARCHIVER_REGISTRY_SNAPSHOT_INTERVAL` — *optional*. Seconds between `info.registry` full-set republishes (default `3600`; invalid or `≤0` falls back). The period bounds the failure cases (trimmed stream, dead-lettered delta, cold-starting consumer) — healthy-delta convergence is outbox latency, sub-second.
- `ARCHIVER_REPLICATION_REAP_INTERVAL` — *optional*. Seconds between replication-reaper sweeps (default `900`, floor `60`; malformed falls back, low values clamp). Well under the horizon so a command crosses it in one period rather than one-and-a-bit.
- `ARCHIVER_REPLICATION_REAP_HORIZON` — *optional*. Seconds a `content.replicate` command may stay open before it is abandoned (default `21600` = 6h, floor `300`). Sized against Replicator's **unbounded** retry for a transient provider failure, not against a delivery ceiling: abandoning a command still being worked turns a slow success into a permanent-looking failure. Abandoned means "no fact arrived in time", never "this failed" — and the reaper never re-issues (archiver#170).
- `ARCHIVER_PERSIST_ISSUANCE` — *optional*, off unless `1`/`true`/`yes`/`on`. Switches on `content.persist` issuance and the reaper's persist re-issue (archiver#276). **Set it only after Replicator's `worker ready` reports `persist: enabled`** (broker#64's go-live order): `replicator.persist` is created at `$`, so a command sent before it existed is never delivered. It lives in `/etc/archiver/.env`, unlike the two systemd-only gates, because sourcing it cannot make a stray process issue: both actors, the `archiver.revisions` consumer (issuance on receipt and re-arm) and the reaper (re-issue), run only in `archiver.service` behind `ARCHIVER_BUS_CONSUMER`, and an HTTP-written revision never carries a digest. The test suite scrubs it (`tests/conftest.py`). A change takes effect on `sudo systemctl restart archiver`.
- `ARCHIVER_REGISTRY_STREAM_MAXLEN` — *optional*. Approximate cap carried on **every** `info.registry` publish via `BusPublish.maxlen` (default `50000`; invalid or `≤0` falls back — never unbounded). This stream is deliberately **excluded** from the periodic `XTRIM`: consumers replay from `0-0`, so retention is a consumer contract whose floor is one full set plus the deltas since. Size from key count × sets retained, never from the `info.changes` number.

  **Setting this obliges a note to [CannObserv/broker](https://github.com/CannObserv/broker)**, for the same reason as the fact-stream cap above: their `REGISTRY_PRODUCER_MAXLEN` mirrors this knob's *default* and feeds `REGISTRY_WARN_LENGTH`, the stream-too-long **ceiling**. Their shrink check (CannObserv/broker#42) deliberately carries no cap at all — it reads `entries-added - length` with `max-deleted-entry-id` — so an override here moves the ceiling only. Unset in production as of 2026-09-23.

  Note the fourth mover: the repo-root `.env` loads **after** `/etc/archiver/.env` and overrides it, is gitignored, and is agent-owned — the likeliest place for a scratch value to be set and forgotten.
- `ARCHIVER_REDIS_FLOOR_TIMEOUT` — *optional*. Seconds (default `5`) bounding **each** broker probe in `scripts/check_redis_floor.sh` — the version floor and the live-`maxmemory` check — at the `archiver.service` `ExecStartPre`. `redis-cli` has no connect-timeout flag, so each probe is wrapped in `timeout`; this prevents a `rediss://`-vs-plaintext (or unreachable) endpoint from hanging archiver startup — a timeout yields a soft-skip, never a block.
- `ARCHIVER_BUS_CONSUMER` — *optional*. `1` opts this process into the `archiver.revisions` consumer group on `content.revisions` (archiver#139). **Only `deploy/archiver.service` sets it**, and — like `ARCHIVER_ALLOW_PRODUCTION_DB` — it must **never** appear in `/etc/archiver/.env` or `.env`, or every process that sources them joins the group. The asymmetry with the publisher is the point: producing from a stray process is noisy, whereas *consuming* removes messages from the group, so a second member silently takes half the revisions and writes them into whatever database it happens to hold. Unset (or with `ARCHIVER_REDIS_URL` unset) → the consumer is dormant and the service starts with no bus-read dependency. Setting it does not affect the publisher, and a consumer that fails to start leaves the publisher running. **The `info.watch-status` tail (archiver#151) is deliberately *not* behind this gate** — it is groupless, and a stray tail removes nothing from any PEL, so `ARCHIVER_REDIS_URL` alone starts it. Do not "fix" that by adding the gate: the gate's entire meaning is group membership.
- `ARCHIVER_DEV_REDIS_URL` — *optional*. Dev change-bus broker for `scripts/dev_server.sh`. Unset → the dev server runs **bus-dormant** and never inherits prod's `ARCHIVER_REDIS_URL` from `/etc/archiver/.env` (the Redis analogue of the DB `_test`/`_dev` guard). The supported posture is **dormant, or a local throwaway broker** — `docker run --rm -p 127.0.0.1:6380:6379 redis:7` with `ARCHIVER_DEV_REDIS_URL=redis://127.0.0.1:6380/0` (≥ 7.0, the `check_redis_floor.sh` floor). A value on production's `host:port` is refused **whatever its DB index** (archiver#240).

  **Do not re-add a `.../1` recommendation: a logical DB index is not a boundary.** Redis ACLs cannot partition by index — any client that can reach db1 can `SELECT 0` — so isolation by index is isolation by good behaviour. The shared broker closes that axis with `databases 1` and no `+select` in archiver's ACL (after its 2026-09-10 incident, `docs/INCIDENT-2026-09-10.md` in [CannObserv/broker](https://github.com/CannObserv/broker)), so `.../1` there is `ERR DB index is out of range`. Nor is a scratch bus on the shared instance wanted: it shares `maxmemory` under `noeviction` instance-wide, so a dev run that fills it stalls every production publisher (the R5 lockstep, firing for a reason nobody would look for). A prefix-confined dev credential (`~archiver.dev.*`) is available from broker on request — not requested until a real need appears.
- `ARCHIVER_POWER_MAP_API_KEY` — *optional*. Archiver's **read-only** Power Map key (archiver#304), sent as `X-API-Key`. **The switch**: unset → Power Map features are dormant, `PUT /info-items/{id}/org` and a create with `pm_org_id` answer 503 "Power Map not configured", and nothing else changes — rendering and replication read only the local `pm_organizations` snapshot, never Power Map. Set in `/etc/archiver/.env`; takes effect on restart. It is also the follower's switch: `archiver-pm-org-refresh.service` exits 0 without touching the database when it is unset (see *Timers* below). `scripts/dev_server.sh` never passes it through (see `ARCHIVER_DEV_POWER_MAP_API_KEY`); the test suite scrubs it.
- `ARCHIVER_POWER_MAP_BASE_URL` — *optional*. Power Map's base URL, default `https://power-map.exe.xyz` (public HTTPS, no tailnet hop). Read only when the key is set.
- `ARCHIVER_DEV_POWER_MAP_API_KEY` / `ARCHIVER_DEV_POWER_MAP_BASE_URL` — *optional*, dev only. What `scripts/dev_server.sh` exports as the two above; unset → the dev server runs Power Map-dormant. Unlike the Redis guard there is no same-target refusal: the key is read-only and dev writes only `archiver_dev`, so reading production Power Map from 8001 is the supported posture. Only inheriting the service's credential is refused. Set in the repo `.env`.
- `ARCHIVER_PUBLIC_BASE_URL` — *optional*. Public-facing base URL of this Archiver instance (e.g. `https://archiver.example.com`). When set, InfoItem API responses include `dashboard_url` pointing to the dashboard detail page (`{ARCHIVER_PUBLIC_BASE_URL}/info-items/{id}`). Unset → `dashboard_url` is `null`. Set this to the URL end-users open in a browser, distinct from any internal service-to-service address. Set in `/etc/archiver/.env` on the VM.
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

## Sourcing env files — why not `export $(cat … | xargs)`

> Use `set -a; . <file>; set +a` (POSIX-portable source via `.`) rather than `export $(cat <file> | xargs)`. The xargs form silently breaks for values containing spaces, quotes, newlines, or embedded `=` — and produces hard-to-diagnose failures later when those env vars are read.
