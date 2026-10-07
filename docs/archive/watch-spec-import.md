# `scripts/import_watch_specs.py` — retired (archiver#150 → #142)

Archived from docs/DEPLOYMENT.md (*One-time data imports*) on 2026-10-07: the script
is gone and nothing operational remains.

The one-time pass that moved Watcher's `default_schedule_config` and `is_active`
onto `info_items.watch_spec` / `info_items.watch_active` ran on production and is
gone, along with `src/core/watch_spec_import.py` and the
`ARCHIVER_ALLOW_WATCH_IMPORT` guard that armed its `--apply`. It read those two
fields over the `watcher_client` SDK, which archiver#142 deleted; there is nothing
left to import *from*, and nothing to import *to* that the dashboard does not now
own outright.

Recorded because the ordering mattered and the reasoning outlives the script: the
import had to complete before the SDK was deleted, since the SDK was the only
reader of Watcher's copy. It did (archiver#150, closed), the control-plane cutover
made those columns authoritative (archiver#158), and the teardown followed.
