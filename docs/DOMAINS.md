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

## The two dark fields

Both are stored and editable, and nothing reads them yet.

- **`min_interval_seconds FLOAT NOT NULL DEFAULT 1.0`**: request spacing for the host.
  - The `CHECK` requires a finite value `>= 0`. `NaN` is excluded explicitly, since Postgres sorts
    it above every number.
  - It takes effect when #366 publishes `content.fetch-policy` (flip F1).
  - Until then, Watcher's value is live, and the pre-F1 re-import
    (`src/core/tools/import_watcher_domains.py`) overwrites an edit.
- **`default_watch_spec JSONB NULL`**: the domain tier of cadence.
  - It is a WatchSpec v1 document that carries `interval`, judged by `validate_domain_watch_spec`.
    `NULL` means no domain default.
  - It takes effect when #364 resolves cadence (flip F2).
  - It's stored in WatchSpec shape, never Watcher's `ScheduleConfig`, so #364 merges like with
    like.

## Left open

- Per-host fetch headers (#376) and a fetch timeout (#377) will get their own columns or table.
  Neither field above is a policy blob to extend.
- `DELETE` stays legal: it's a 409 while any InfoSource names the host. #366 draws fetch-policy
  generations from a sequence, so a re-added host cannot go backwards (cannobserv#566).
