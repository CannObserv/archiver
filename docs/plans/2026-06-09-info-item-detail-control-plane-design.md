# InfoItem Detail — Control Plane Hub Design

**Date:** 2026-06-09
**Status:** Approved

---

## Goal

Redesign the InfoItem detail page from a data-record view into an operational hub. The top
operator jobs are: (1) at-a-glance health/freshness assessment, (2) triggering out-of-band
Watcher checks, (3) InfoSource management including primary failure detection and swap,
(4) copying Replicator public URLs, (5) reviewing revision history. The current 5-section
layout (shipped in #49) is organised around the data model; this design reorganises it around
those jobs and wires the Watcher integration that the prior design left stubbed.

Archiver is the control plane for sibling services. This work completes Phase B of the
standalone Watcher architecture (designed in `watcher/docs/plans/2026-06-07-watcher-standalone-service-design.md`):
Archiver provisions and updates WatchedItems in Watcher whenever InfoItems and their sources
change.

---

## Context

After #48 (InfoSource simplification) and #49 (dashboard UX redesign), the InfoItem detail
page has five vertical-scroll sections: Overview, Sources, Watcher (stub), Replicator,
Revision History. The Watcher section contains only static placeholder copy.

Watcher #185 shipped Phase A of the standalone architecture: the pipeline no longer calls
Archiver at runtime. `WatchedItem` now stores `effective_url`, `source_specs`,
`health_status`, `last_checked_at`, `last_changed_at`, and an optional `archiver_info_source_id`
locally. Phase B (Archiver calling Watcher's API to provision and update WatchedItems) is
unbuilt.

---

## Approved Approach

**Archiver provisions WatchedItems.** On InfoItem creation, primary source change, and spec
update, Archiver calls Watcher's API. All provisioning calls are best-effort, post-commit,
and logged on failure — they never fail the primary Archiver operation.

**WatcherClient generated from Watcher's OpenAPI spec** using the same `openapi-python-client`
pattern as `archiver-client`. The generated output lives untouched under
`clients/watcher-python/src/watcher_client/generated/`; an Archiver adapter layer
(`client.py`) wraps it with ergonomic methods. No post-generation modifications to the
generated output. This structure anticipates Watcher eventually publishing its own SDK.

**InfoItem detail sections:** the health strip moves into Section 1 (loaded as a separate
HTMX partial so Watcher outages degrade gracefully); Section 2 (Sources) gains per-row health
context and a swap-primary inline flow; Section 3 (Watcher) becomes fully functional.

---

## Key Decisions

### 1. `watcher_item_id` column on `info_items`

New nullable `watcher_item_id TEXT` column on `information.info_items`. Populated when
Archiver provisions a WatchedItem; null for InfoItems created before this integration ships.
Allows the detail page to call Watcher directly without a lookup round-trip on every render.

The "Begin watching" button in Section 3 handles on-demand provisioning for pre-existing
InfoItems — `watcher_item_id IS NULL` renders that affordance rather than an error.

### 2. Watcher API additions (all required before client generation)

| Change | Detail |
|---|---|
| `WatchedItemResponse` | Add `health_status: str` (enum: `unknown\|ok\|error\|stale`) |
| `WatchedItemResponse` | Add `last_checked_at: datetime\|null` |
| `WatchedItemResponse` | Add `archiver_info_source_id: str\|null` |
| `WatchedItemCreate` / `WatchedItemPatch` | Add `archiver_info_source_id: str\|null` |
| `GET /api/v1/watched-items` | Add `?info_item_id=` query filter |
| New: `POST /api/v1/watched-items/{id}/check-now` | Enqueue immediate fetch cycle; respond 202 with updated WatchedItem |

### 3. WatcherClient package layout

```
clients/watcher-python/
  src/watcher_client/
    generated/          ← openapi-python-client output, never modified by hand
    client.py           ← Archiver adapter layer
    errors.py
    __init__.py
  scripts/regen.sh      ← fetches http://localhost:8000/openapi.json, WATCHER_API_KEY auth
  pyproject.toml
```

Main `pyproject.toml` adds `watcher-client = { path = "clients/watcher-python", editable = true }`.
Ruff excludes list gains `clients/watcher-python/src/watcher_client/generated/`.

**Adapter layer methods:**

| Method | Watcher endpoint |
|---|---|
| `provision_watched_item(url, source_specs, info_item_id, archiver_info_source_id)` | `POST /api/v1/watched-items` |
| `patch_watched_item(watcher_item_id, *, effective_url?, source_specs?, archiver_info_source_id?)` | `PATCH /api/v1/watched-items/{id}` |
| `get_watched_item(watcher_item_id)` | `GET /api/v1/watched-items/{id}` |
| `get_by_info_item_id(info_item_id)` | `GET /api/v1/watched-items?info_item_id={id}` |
| `check_now(watcher_item_id)` | `POST /api/v1/watched-items/{id}/check-now` |
| `list_revisions(watcher_item_id)` | `GET /api/v1/watched-items/{id}/revisions` |

### 4. Provisioning hooks

| Archiver trigger | Watcher call |
|---|---|
| `POST /info-items` (API create) | `provision_watched_item(...)` → store `watcher_item_id` on InfoItem |
| `POST /dashboard/register` (wizard) | Same — inlined in the atomic create handler |
| `POST /info-items/{id}/info-sources` (primary swap) | `patch_watched_item(watcher_item_id, effective_url=new_url, source_specs=new_specs, archiver_info_source_id=new_source_id)` |
| `PATCH /info-sources/{id}/source-specs` (spec update) | Look up active InfoItem binding for this source → `patch_watched_item(watcher_item_id, source_specs=new_specs)` |

All calls: async, post-commit, wrapped in `try/except`, logged on error. No retry — the
"Begin watching" affordance and `PATCH /dashboard/info-items/{id}/resync-watcher` (see §5)
cover recovery.

### 5. InfoItem detail — section changes

**Section 1 — Overview**

Compact health strip added below the identity block, loaded via a separate HTMX partial
(`GET /dashboard/info-items/{id}/watcher-status`). Partial calls Watcher via `get_watched_item`
and renders one of five states:

```
● OK   Last checked: 4 min ago   Last changed: 3 days ago   Cadence: ~15 min   [Check now]
● ERROR   Last checked: 2 hr ago   —   [Check now]
● STALE   Last checked: 6 hr ago   Last changed: 12 days ago   [Check now]
● UNKNOWN   (watching, no check yet)   [Check now]
  Not watching   [Begin watching]
```

"Check now" fires `POST /dashboard/info-items/{id}/check-now` (Archiver proxy → Watcher
`check-now`), then re-triggers the `watcher-status` partial via HTMX swap.

"Begin watching" fires `POST /dashboard/info-items/{id}/begin-watching`, which provisions
the WatchedItem on demand (for pre-existing InfoItems) and re-renders the strip.

If `WATCHER_BASE_URL` is unset, the partial renders a single muted line:
"Watcher not configured." with no spinner or error state.

**Section 2 — Information Sources**

Primary row gains a health indicator dot (colour-coded from `health_status`) pulled from the
watcher-status partial response cached in the page context.

"Deactivate" action replaced with **"Swap primary"** — expands an inline panel with two paths:
- **Author new source:** embedded steps 2–3 of the registration wizard (URL + spec editor +
  preview), inline. On submit: `POST /info-items/{id}/info-sources` with the new
  `info_source_id`, which auto-deactivates the old primary; Archiver then calls
  `patch_watched_item` with the new URL and specs.
- **Bind existing source by ID:** ULID input, collapsed under `<details>` as an advanced option.

The old "Bind Existing Information Source" `<details>` form below the table is removed; it is
replaced entirely by the Swap primary panel.

**Section 3 — Watcher (now functional)**

No longer a stub. Shows:
- `effective_url`, source_spec summary (algorithm name + selector count), `domain_name`
- `health_status` badge, `last_checked_at`, `last_changed_at`
- Cadence derived from `default_schedule_config`
- "Check now" button (same proxy endpoint as the strip; re-renders this section on success)
- "View in Watcher ↗" deeplink to `{WATCHER_BASE_URL}/watched-items/{watcher_item_id}`
- "Re-sync" button (`POST /dashboard/info-items/{id}/resync-watcher`) — PATCHes the
  WatchedItem with the InfoItem's current URL and specs; handles drift recovery.
- "Not watching" state (same as strip) when `watcher_item_id IS NULL`.

**Sections 4–5** — unchanged from #49.

### 6. New dashboard proxy endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/dashboard/info-items/{id}/watcher-status` | HTMX partial: load WatchedItem health from Watcher |
| `POST` | `/dashboard/info-items/{id}/check-now` | Proxy to Watcher `check-now`; re-renders status partial |
| `POST` | `/dashboard/info-items/{id}/begin-watching` | Provision WatchedItem on demand; re-renders status partial |
| `POST` | `/dashboard/info-items/{id}/resync-watcher` | PATCH WatchedItem with current URL+specs; re-renders Section 3 |

---

## Implementation Sequence

**Workstream 1 — Watcher (prerequisite):**
Watcher API additions (#_TBD_). Must ship before client generation.

**Workstream 2 — Archiver (after Watcher ships):**
1. Generate `clients/watcher-python/` from updated Watcher spec
2. Alembic migration: `watcher_item_id TEXT NULL` on `information.info_items`
3. Provisioning hooks wired into API routes and registration wizard
4. Dashboard proxy endpoints + watcher-status HTMX partial
5. Section 1 health strip
6. Section 2 swap-primary inline flow
7. Section 3 functional Watcher panel
8. Docs + CHANGELOG

---

## Out of Scope

- **Revision History cross-linking** — `ChangeRevision.archiver_revision_id` exists for
  future cross-reference between Watcher's change history and Archiver's `SourceRevision`
  records. Deferred; Section 5 remains Archiver-only for now.
- **Watcher rate-limiter config** — `min_interval`, `max_concurrency` are Watcher-owned.
  Archiver surfaces a "View in Watcher ↗" link only.
- **Bus-event-driven sync (Phase C)** — Archiver will call Watcher's API directly on
  source changes rather than publishing a bus event. Phase C (Redis-driven sync) remains
  deferred per the Watcher standalone design.
- **WatcherClient published as an installable package** — the package structure anticipates
  this but publication is Watcher's responsibility when they are ready.
