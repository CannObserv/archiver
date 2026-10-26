# Domains — per-host policy

`Domain` (`domains`) holds one row per hostname (`name`, unique). **Archiver is its sole owner**
(archiver#360, design D4 in watcher `docs/plans/2026-10-14-headless-watcher-and-cohort-boundaries-design.md`).
`info_sources.domain_name` names a host with **no FK**, so a host with no row counts as active.
`PATCH` therefore refuses a name no source could carry (`is_canonical_hostname`, CR 22):
an `Example.com` row would make suspension a silent no-op.
Routes and the SDK: [API.md](API.md). The dashboard rows: [PAGES.md](PAGES.md) § Domain pages.

## Suspension is intent

`is_active = false` *or* a set `archived_at` suspends the host. The one predicate is
`domain_suspended` (`src/core/services/registry_announcement.py`), matching Watcher's
`is_suspended`.

- Every item whose **active binding's** source names a suspended host announces `active = false`
  on `info.registry`.
- On an active host, `watch_active` passes through unchanged, `NULL` included.
- Both emit paths resolve this way: the delta path and the hourly snapshot.
- Before #360, `is_active` was described as gating suggestions, but nothing read it.

## One write path

`update_domain` (`src/core/services/domain_policy.py`) is the only write that can flip suspension.
It sits behind:
- the API's `PATCH`, archive and restore;
- the dashboard's archive, restore and fetch-policy save.

A flip announces the items whose resolved `active` moved, in the write's transaction, through the
policy path (never a tombstone). A write that flips nothing emits nothing.

The lock order is items, then the row, except for one case: a host that is still gaining items
after the write's three tries locks them after the row, with Postgres's deadlock detector as the
backstop. A write that can't flip suspension locks only the row. The newcomer retry and the
accepted limit for a host with no row are in that module's docstring.

## The two policy fields

Both are stored and editable. The interval is live since F1 (#438); the cadence goes live at F2.

- **`min_interval_seconds FLOAT NOT NULL DEFAULT 1.0`**: request spacing for the host.
  - The `CHECK` requires a finite value `>= 0`. `NaN` is excluded explicitly, since Postgres sorts
    it above every number.
  - Archiver publishes it on `content.fetch-policy` (#366), live since flip F1 (#438):
    § `content.fetch-policy` below. Watcher no longer produces it (CannObserv/watcher#374).
  - The dashboard's copy follows the process's `ARCHIVER_FETCH_POLICY_PRODUCER`: production reads
    live, and a dev or test process, where it is unset, says it doesn't publish.
- **`default_watch_spec JSONB NULL`**: the domain tier of cadence.
  - It is a WatchSpec v1 document that carries `interval`, judged by `validate_domain_watch_spec`.
    `NULL` means no domain default.
  - It takes effect when #364 resolves cadence (flip F2).
  - It's stored in WatchSpec shape, never Watcher's `ScheduleConfig`, so #364 merges like with
    like.

## `content.fetch-policy` (#366) - live since F1 (#438)

Archiver took over Watcher's producer at F1 (watcher `src/core/fetch_policy.py`): one
`FetchPolicyState` per host (`FetchPolicyEmit` at emit), keyed by the `host` field, read
grouplessly from `0-0` by Replicator through co-core's `fetch_policy_supersedes`
(CannObserv/replicator#136).

- **Unit-only.** Only `deploy/archiver.service` sets `ARCHIVER_FETCH_POLICY_PRODUCER` (since F1):
  a second writer would fight it, and no ACL refuses two (broker#93). Unset, as in every dev and
  test process, generations still advance and nothing reaches the outbox or the stream. Startup
  logs whether the process produces; flag on without a bus is an ERROR.
- **The frame** is `(revoked, min_interval_seconds if live)`. A suspended host (`domain_suspended`,
  the predicate `info.registry` uses) is `revoked` with no interval, never a fake number; so is a
  deleted host, from `fetch_policy_tombstones`.
- **Deltas** ride the outbox (`src/core/services/fetch_policy.py`), in the transaction that
  changed the host. **Full sets** go direct (`src/core/changes/fetch_policy_snapshot.py`): every
  Domain plus every tombstone, at startup and every 300 s, generations read and never drawn. No
  retry; an unpublishable host is skipped with a warning; a dead-lettered delta is discard-only.
- **Retention rides the `XADD`.** The grant is `+xadd` only (broker#93): no `XTRIM`, no read-back.
  The cap is `max(ARCHIVER_FETCH_POLICY_STREAM_MAXLEN or 500, 10 x set)`, computed only from a
  complete set (its one caller pinned by `test_fetch_policy_snapshot_callers.py`). Deltas carry
  the last set's cap, and none before the first.
- **Mirrored on the broker** (`src/broker/bus_health.py`): 500 (`LWW_PRODUCER_MAXLEN`), 10
  (`LWW_RETAINED_FULL_SETS`), 300 s (`LWW_REPUBLISH_PERIOD_SECONDS`, shared with
  `info.watch-status`). File on CannObserv/broker before changing one; the period has no env
  override for that reason.

### The generation

`domains.fetch_policy_generation BIGINT NOT NULL`, on every frame (cannobserv#566):
`build_policy` refuses a frame without one, since co-core accepts `None` until cannobserv#579 and
a consumer holding an ordered frame drops an unordered one silently. One sequence,
`fetch_policy_generation_seq`, never a per-row counter: a hostname is reusable, so a re-added host
must draw above its own tombstone.

- **When it draws:** `announce_domain`, when the frame changes or the row is new. An interval save
  on a live host and a suspension flip draw; notes, the cadence, and an interval save on a
  suspended host don't (the restore carries the new value).
- **Where:** `update_domain` (both surfaces), both insert sites (`update_domain`'s `create=True`
  for `PATCH` and the importer; `get_or_create_domain` for a source create), and `delete_domain`,
  which draws the tombstone's value.
- **Only once the row is the transaction's.** A column default is evaluated when an `INSERT … ON
  CONFLICT` forms its tuple, before it waits on a concurrent delete of the same name, so insert
  sites redraw after the insert. `delete_domain` locks the row before drawing, so a save that held
  it first orders below the tombstone.
- **Flag or not, it advances,** so the first full set at F1 carried current values.
- **Gaps are expected.** `ON CONFLICT DO NOTHING` still evaluates the default, so every `PATCH`
  of an existing host burns a value, and an insert draws twice. Only order matters on the wire.

### The F1 runbook - archiver's half

The operator's go is recorded on CannObserv/watcher#368.

1. Watcher's producer stops (CannObserv/watcher#374 deployed).
2. Watcher re-exports; the operator re-imports (`python -m src.core.tools.import_watcher_domains`).
   Read-back: a `--dry-run` of the same export prints no pending writes, so every host Watcher
   published live is an Archiver Domain and the first full set orders it. A host only in Watcher's
   tombstone table needs nothing: its last Watcher frame is already `revoked`.
3. The flag PR uncomments `#Environment=ARCHIVER_FETCH_POLICY_PRODUCER=1` in
   `deploy/archiver.service`; merge, then `scripts/deploy.sh`.
4. The journal shows `content.fetch-policy producer started`, then `fetch-policy full set
   published` with `published` = Domains + tombstones.
5. Read-backs: no new `ignoring a fetch policy without a generation` lines in Replicator's journal
   (CannObserv/replicator#135); no last-entry-age WARN from broker's probe (one is possible if
   steps 1-4 took over 15 minutes).

## Left open

- Per-host fetch headers (#376) and a fetch timeout (#377) will get their own columns or table.
  Neither field above is a policy blob to extend.
- `DELETE` stays legal: it's a 409 while any InfoSource names the host. The host's
  `content.fetch-policy` tombstone is recorded in `fetch_policy_tombstones` (#366).
