# Archiver Dashboard — UI Reference

**Page inventory, HTMX swap patterns, Alpine.js component catalogue, flash/modal usage guide.**

> **AGENTS.md enforcement:** This file must be updated in the same commit as any Jinja2 template change, new route, or new Alpine.js component.

---

## URL Structure

```
/dashboard/                          Home — CTA, health strip, Recent Activity, domain overview
/dashboard/domains/                  Domains list (#49)
/dashboard/domains/{name}            Domain detail — notes, status, linked sources (#49)
/dashboard/register                  Register Information Item — 4-step flow (#49)
/dashboard/info-items/               Information Items list
/dashboard/info-items/{id}           Information Item detail (hub page — 5-section scroll) (#49)
/dashboard/info-items/new            → 301 redirect to /dashboard/register (#49)
/dashboard/info-sources/             Information Sources list
/dashboard/info-sources/{id}         Information Source detail
/dashboard/info-sources/new          Create Information Source
/dashboard/source-revisions/         Information Source Revisions list
/dashboard/source-revisions/{id}     Information Source Revision detail
/dashboard/rep-specs/                Replication Specifications list
/dashboard/rep-specs/{id}            Replication Specification detail
/dashboard/rep-specs/new             Create Replication Specification
/dashboard/settings/api-keys         API Keys management
```

### Domain pages (`/dashboard/domains/`)  *(#49 — implemented)*

**GET `/dashboard/domains/`** — paginated list. Columns: Domain (linked to detail), Sources (count), Status badge, Created. Filter bar: `?is_active=true|false|` (all). Source counts loaded via a GROUP BY query.

**GET `/dashboard/domains/{name}`** — detail. Status badge, operator notes (HTMX inline edit), linked Information Sources table.

**POST `/dashboard/domains/{name}/notes`** — HTMX partial; replaces `#notes-section` with `domains/_notes_partial.html`. Saves notes inline.

**POST `/dashboard/domains/{name}/archive`** — sets `archived_at`, redirects to detail (303).

**POST `/dashboard/domains/{name}/restore`** — clears `archived_at`, redirects to detail (303).

Templates: `domains/list.html`, `domains/detail.html`, `domains/_notes_partial.html`.

### Registration flow (`/dashboard/register`)  *(#49 — implemented)*

4-step flow: URL → Selector → Metadata → Review & Submit. Replaces `/dashboard/info-items/new`.
See design doc `docs/plans/2026-06-04-dashboard-ux-redesign-design.md` for full spec.

**Step 3 (Metadata) — Watcher settings (advanced)** *(#50)*: a collapsed
`<details>` block exposes a **Fetch cadence** `<select.form-select>`
(`name="cadence"`, `x-model="cadence"`, `x-ref="cadenceInput"`). The options and
default are rendered server-side from the shared cadence vocabulary
(`src/dashboard/cadence.py`: Hourly `1h` / Every 6 hours `6h` / Daily `1d` (default)
/ Weekly `7d`), injected as the `cadence_labels` / `default_cadence` Jinja globals.
The value is a Watcher interval string. On submit the server forwards
`{"interval": <value>}` as the WatchedItem `default_schedule_config` during
provisioning (best-effort, post-commit) **only when the value is a recognised
option**; otherwise it sends `None` so Watcher applies its own default (the handler
never fabricates a cadence). The selection is sticky across validation re-renders
(`cadence_value` → `selected` attribute). Step 4 review shows the human-readable
cadence label (`cadenceLabel` getter reads it off the selected `<option>`). The
same vocabulary backs `_format_cadence` on the InfoItem detail Watcher section, so
recognised cadences display with the same friendly labels.

The same `<details>` block also exposes a **Watch active immediately** checkbox
*(#60)* (`<input type="checkbox" id="reg-watch-active" name="watch_active" value="on"`,
`x-model="watchActive"`, `x-ref="watchActiveInput"`), checked by default. Checked →
the server omits `is_active` so Watcher provisions the WatchedItem active; unchecked
(the checkbox sends nothing) → the server forwards `is_active=False` to provision it
**paused**. The choice is sticky across validation re-renders (`watch_active_value` →
`checked` attribute, defaulting to checked via `|default(true)`). Step 4 review shows
"Active immediately" / "Paused" via the `watchActiveLabel` getter.

API stays at `/api/v1/*`. Health/OpenAPI unchanged.

---

## Authentication

Every dashboard request passes through `get_dashboard_user` (in `src/dashboard/deps.py`).
- Reads `X-ExeDev-UserID` and `X-ExeDev-Email` from request headers.
- Absent headers → 307 redirect to `/__exe.dev/login?redirect=<path>`.
- On success: upserts `AppUser` (creates if new; updates email if changed) and returns the row.
- Tests override via `app.dependency_overrides[get_dashboard_user]`.

---

## HTMX Patterns

### Boosted navigation

`<body hx-boost="true">` — all in-dashboard `<a>` links and form submissions use HTMX fetch automatically (no full page reload). HTMX swaps the `<body>` and updates `<title>`.

### Partial fragment swaps

Server returns a partial HTML fragment with `HX-Reswap: outerHTML` / `HX-Retarget: #target-id` headers when refreshing a sub-section (e.g., the rep-spec assignment table row).

### Flash messages

Server returns `HX-Trigger: {"showFlash": {"level": "success", "body": "Saved."}}` alongside any mutating response. `flash.js` (loaded in `base.html`) injects `.flash--*` divs into `#flash-region`. Auto-dismisses after 6 s. **Note:** `flash.js` must be in the `base.html` script list — if it is dropped, every `showFlash` is silently ignored site-wide (CannObserv/archiver#62).

Levels: `"success"` | `"warning"` | `"error"` | `"info"`.

### Live validation

SourceSpec and RepSpec editors use HTMX to POST to `/api/v1/tools/validate-source-spec` (or `-rep-spec`) on blur and render inline error feedback.

---

## Alpine.js Component Catalogue

All components registered as `Alpine.data('name', factory)` in `main.js` before `Alpine.start()`. No inline `x-data="{ ... }"` blobs in templates.

### `apiKeyCreate`

Create-form toggle for the API Keys settings page.

**State:**
- `showForm: boolean` — whether the create-key panel is expanded.

**Usage:** `x-data="apiKeyCreate"` on the outer `<div class="entity-section">`. A `<button @click="showForm = !showForm">` in the header toggles the form. The form panel uses `x-show="showForm" x-cloak` to hide before Alpine initialises. After a full-page POST response, `showForm` resets to its initial `false` state automatically (form collapses; the new-key reveal panel appears instead).

---

### `apiKeyRow`

Inline edit/view toggle for a single API key table row.

**State:**
- `editing: boolean` — whether the row is in edit mode.

**Methods:**
- `cancelEdit()` — set `editing = false` without a server call.

**Usage:** `x-data="apiKeyRow"` on each `<tr id="key-row-{id}">`. View mode shows the label as text with Edit + Delete buttons. Edit mode reveals a label input and Save + Cancel buttons. Save uses HTMX `hx-patch` with `hx-include="#label-{id}"` to send the updated label; the server returns a fresh `_api_key_row.html` fragment that initialises with `editing: false`. Cancel calls `cancelEdit()`. Edit-mode elements carry `style="display:none;"` as an initial-state hint to prevent FOUC before Alpine runs.

---

### `apiKeyReveal`

Reveal-once panel for a newly created API key.

**State:**
- `rawKey: string` — the one-time raw key value (set via `x-init`).
- `copied: boolean` — clipboard copy feedback.

**Methods:**
- `copy()` — write `rawKey` to clipboard, set `copied = true` for 2 s.

**Usage:** `x-data="apiKeyReveal" x-init="rawKey = '{{ new_raw_key }}'"` on the reveal section returned by `POST /dashboard/settings/api-keys`. `rawKey` is assigned directly in `x-init` (direct property assignment through the Alpine reactive proxy — do not use a method call from `x-init` as `this` is unbound). The raw key is embedded server-side in the one-time render; it is not stored client-side beyond the DOM lifetime.

---

### `infoItemWizard`

Multi-step create form for Information Items.

**State:**
- `step: number` — current step (1 = Basics, 2 = Source, 3 = Review).
- `name: string`, `description: string`, `owner: string` — form field values.
- `repFieldsRaw: string` — raw JSON string for `rep_fields` (written by nested `jsonFieldEditor`).
- `initialUrl: string` — URL for the optional initial InfoSource.
- `initialSourceSpecsRaw: string` — raw JSON array string for `initial_source_specs` (bound via `x-model` on the textarea; not a `jsonFieldEditor` — arrays are not objects).

**Methods:**
- `nextStep()` — advance to next step; step 1 guards that `name` is non-empty.
- `prepareSubmit()` — called on form submit; no-op (editors write into root props on blur; `initialSourceSpecsRaw` stays in sync via `x-model`).

**Usage:** `x-data="infoItemWizard"` on the outer `<div>`. `repFieldsRaw` is written by a nested `jsonFieldEditor`. `initialSourceSpecsRaw` is bound directly via `x-model="initialSourceSpecsRaw"` on the step-2 textarea (which also carries `name="initial_source_specs"` so the form POST captures it directly — no hidden input needed for this field). Step 2 shows `initial_url` text input and `initial_source_specs` JSON array textarea.

---

### `sourceSpecEditor`

*(Retired from InfoSource create form — replaced by plain `<textarea name="source_specs">` with inline error display. Component may still exist in `main.js` for other uses but is no longer used by the InfoSource new/edit forms.)*

---

### `jsonFieldEditor`

Textarea-based JSON object editor with format-on-blur and inline validation.

**Parameters (factory args):**
- `rootProp: string` — name of a property on `$root` to write the formatted JSON string into on each valid blur.
- `_errorKey: string` — reserved for API symmetry; error state is component-local.

**State:**
- `raw: string` — raw textarea value.
- `hasError: boolean` — true when the current value is not a valid JSON object.
- `errorMsg: string` — human-readable parse error.

**Methods:**
- `formatAndValidate()` — called on `@blur`. Parses `raw`, pretty-prints valid objects, writes into `$root[rootProp]`, sets `hasError`/`errorMsg`.

**Usage:** `x-data="jsonFieldEditor('repFieldsRaw', 'rep_fields_error')"` on a wrapper element containing the `<textarea x-model="raw" @blur="formatAndValidate()">`.

---

---

## Page Inventory

### Home (`/dashboard/`)  *(Epic 7 — implemented)*

**GET `/dashboard/`** — summary dashboard. Four count tiles in nav order (Information Items, Information Sources, Information Source Revisions, Replication Specifications), each a link to the respective list page. Service health indicator loaded via `hx-get="/dashboard/health" hx-trigger="load"` (non-blocking, shows "checking…" badge until HTMX fires). Recent Changes table: last 10 SourceRevisions ordered by `captured_at desc`. Columns: Information Source (URL, links to source detail), Source Revision (truncated fingerprint, links to revision detail), Observed (captured_at formatted `%Y-%m-%d %H:%M`).

**GET `/dashboard/health`** — HTMX partial. Returns `<span class="badge badge--success">ok</span>`. Auth-gated; unauthenticated requests redirect 307.

**GET `/dashboard/health/watcher`** — HTMX partial. Calls `WatcherClient.health_check()` (`GET /health` on Watcher); returns one of:
- `badge--success` ("ok") — HTTP 200
- `badge--warning` ("degraded") — Watcher reachable but returned a non-200 status; `title` tooltip contains "Watcher returned {status}"
- `badge--danger` ("error") — network/connect failure; `title` tooltip contains the exception message
- `badge--muted` ("not configured") — `WATCHER_BASE_URL` unset

Logs a warning on degraded/failure. Auth-gated; unauthenticated requests redirect 307.

**GET `/dashboard/health/redis`** — HTMX partial. Calls `redis.ping()`; returns `badge--success` ("ok"), `badge--danger` ("error" with `title` tooltip containing `"{ExcClass}: {message}"`), or `badge--muted` ("not configured") when `ARCHIVER_REDIS_URL` is unset. Logs a warning on failure. Auth-gated; unauthenticated requests redirect 307.

### Information Items (`/dashboard/info-items/`)  *(Epic 3 — implemented)*

**GET `/dashboard/info-items/`** — paginated list with optional `name_contains` search. Filter panel: search input (flex-fill) + Search button (right-aligned via `margin-left:auto`). Columns: name (link to detail), Information Source (primary source URL linked to InfoSource detail; `—` if none), Observed (max `captured_at` of the primary source's revisions formatted `%Y-%m-%d %H:%M`; `—` if none).

**GET `/dashboard/info-items/new`** — 301 redirect to `/dashboard/register`. The old 3-step `infoItemWizard` form was replaced by the registration flow in #49.

**POST `/dashboard/info-items/new`** — legacy direct-create endpoint (still active). Form fields: `name`, `description`, `owner`, `rep_fields` (JSON), `initial_url` (string), `initial_source_specs` (JSON array). Redirects 303 to detail on success. Returns 422 with re-rendered form on validation error. (New registrations should use `/dashboard/register` instead.)

**GET `/dashboard/info-items/{id}`** — 5-section vertical-scroll hub page (template `info_items/detail.html`):

1. **Overview** — `<h1>` name; ULID copy-button (inline Alpine `{copied:false}`; `.btn--secondary .btn--sm` so it reads as a button; label "Copy", flips to "Copied ✓" for 1.5 s on click); domain badge linking to `/dashboard/domains/{name}` (or muted "No primary source" if unbound); `.detail-grid` with description, owner (if set), created_at. Below the grid: **Watcher health strip** — `<div id="watcher-status-strip">` loaded async via `hx-trigger="load"` + `hx-get="…/watcher-status"` + `hx-swap="outerHTML"`. Renders one of five states: `ok`/`error`/`unknown` (watching), `not_watching`, `not_configured`, or `degraded`. Template: `info_items/_watcher_status.html`.
2. **Information Sources** — `x-data="{swapOpen:false}"` Alpine wrapper. `data-table` of active `info_item_sources` bindings (columns: URL, Domain, Bound, Actions); first row gets a brand left-border to mark it as the primary. The Actions cell on the primary row contains a "Swap primary" / "Cancel" toggle button (`@click="swapOpen=!swapOpen"`). When `swapOpen` is true, `<div x-show="swapOpen" x-cloak>` reveals `info_items/_swap_primary.html`. When there are no active bindings, the swap panel renders unconditionally with an "Add primary source" title. The panel has `id="swap-panel"`. The "author new source" form uses `hx-post` + `hx-target-422="#swap-error"` for inline error display; on success it receives 204 + `HX-Redirect`. The "bind by ID" `<details>` sub-form uses the same pattern with `hx-target-422="#swap-by-id-error"`.
3. **Watcher** — `<div id="watcher-section">` loaded async via `hx-trigger="load"` + `hx-get="…/watcher-section"` + `hx-swap="outerHTML"`. Root element also carries `hx-trigger="watcherUpdated from:body"` so the panel self-refreshes whenever `check-now` or `resync-watcher` sends `HX-Trigger: {"watcherUpdated":{}}`. Template: `info_items/_watcher_section.html`. Four states: `not_configured`, `not_watching` (shows "Begin Watching" button), `degraded`, `watching` (shows URL, spec summary, health badge, timestamps, cadence, "Check now", "Re-sync", "View in Watcher ↗" deeplink). Action buttons are `.btn--secondary .btn--sm`. **Begin Watching** provisions a WatchedItem on demand; if Watcher already has one for this InfoItem (Archiver's `watcher_item_id` is NULL — e.g. a pre-#55 item), provisioning 409s and `provision_on_create` adopts the existing WatchedItem's ID rather than failing (CannObserv/archiver#62). When the WatchedItem is paused (`is_active=False`, not archived) a **Paused** `badge--muted` shows next to the health badge, "Check now" is hidden (Watcher 409s on check-now of a paused item), and the toggle reads "Resume"; otherwise it reads "Pause" *(#60)*. Archived WatchedItems (`archived_at` set) show an **Archived** badge instead of "Paused" and hide the pause/resume toggle entirely (Watcher 409s; archive/restore owns activation there).
4. **Replicator** — two sub-sections:
   - *Rep Fields* — `x-data="repFieldsEditor()"` wrapper; HTMX-loaded `sortableChips` suggestions (`hx-trigger="load"`); `<textarea name="rep_fields">` with `PATCH /dashboard/info-items/{id}/rep-fields` inline save; flash target `#rep-fields-flash`.
   - *Replication Specs* — `data-table` of active `info_item_rep_specs` assignments; assign form (`filter-card`, `rep_spec_id` field); HTMX delete per row.
5. **Revision History** — `data-table` of `info_item_source_revisions` ordered by `bound_at desc`; columns: Revision (linked to revision detail), Captured, Cache.

**GET `/dashboard/info-items/{id}/watcher-status`** — HTMX partial (`info_items/_watcher_status.html`). Calls Watcher `get_watched_item`; renders ok/error/unknown/not_watching/not_configured/degraded. Used by `hx-trigger="load"` on the health strip and re-renders after check-now, begin-watching, resync-watcher.

**GET `/dashboard/info-items/{id}/watcher-section`** — HTMX partial (`info_items/_watcher_section.html`). Calls Watcher `get_watched_item`; renders not_configured/not_watching/degraded/watching. The watching state shows URL, spec summary, health badge, timestamps, cadence, and action buttons. Loaded on page init via `hx-trigger="load"`. The "View in Watcher ↗" deeplink base is `WATCHER_PUBLIC_BASE_URL` when set, otherwise falls back to `WATCHER_BASE_URL`.

**POST `/dashboard/info-items/{id}/check-now`** — proxies to Watcher `check-now`; re-renders `_watcher_status.html`; also sets `HX-Trigger: {"watcherUpdated":{}}` so Section 3 (`#watcher-section`) auto-refreshes. If `check_now` fails, re-fetches via `get_watched_item` (shows degraded only if that also fails) **and** adds a `showFlash` error to the `HX-Trigger` so the failure is surfaced rather than swallowed *(#60)*. A `WatcherConflict` (409 — check-now on a paused item) flashes "resume it first"; any other failure flashes "Watcher is unavailable".

**POST `/dashboard/info-items/{id}/begin-watching`** — provisions a WatchedItem on demand (for InfoItems without `watcher_item_id`); calls `provision_on_create`; re-renders `_watcher_status.html`; sets `HX-Trigger: {"watcherUpdated":{}}` so Section 3 auto-refreshes. `provision_on_create` returns a `WatcherSyncOutcome`; on `FAILED` (provisioning attempted but Watcher unavailable) the response adds a `showFlash` error so the failure is surfaced rather than swallowed. When the item has no active primary source to watch, flashes "No primary source to watch — bind one first." A `SKIPPED` outcome (no Watcher configured) flashes nothing *(#61)*.

**POST `/dashboard/info-items/{id}/resync-watcher`** — PATCHes the WatchedItem with the current primary URL and specs via `sync_on_source_swap`; re-renders `_watcher_status.html`; also sets `HX-Trigger: {"watcherUpdated":{}}` so Section 3 auto-refreshes. `sync_on_source_swap` returns a `WatcherSyncOutcome`; on `FAILED` the response adds a `showFlash` error ("Couldn't re-sync with Watcher — it's unavailable"). When the watched item has no active primary source, flashes "No primary source to re-sync — bind one first." *(#61)*

**POST `/dashboard/info-items/{id}/toggle-watch-active`** *(#60)* — pauses or resumes the WatchedItem via `patch_watched_item(is_active=…)`. Form field `active` is the desired target state ("true" → resume, anything else → pause); the button submits the opposite of the current state. Re-renders `_watcher_status.html` and sets `HX-Trigger: {"watcherUpdated":{}}` so Section 3 auto-refreshes. On failure the response adds a `showFlash` error to the `HX-Trigger`: a Watcher 409 (`WatcherConflict`, e.g. pause/resume on an archived item) flashes "the item may be archived"; any other failure flashes "Watcher is unavailable". The partial still re-renders rather than 500ing. No-op (no patch) when the InfoItem has no `watcher_item_id`.

**POST `/dashboard/info-items/{id}/swap-primary-source`** — inline primary-source swap: creates a new InfoSource (form fields: `url`, `source_specs` JSON array), deactivates the old active binding, binds the new source, best-effort `patch_watched_item` post-commit. Returns 204 + `HX-Redirect` to detail on success; returns 422 with an `<div id="swap-error">` fragment on validation error (targeted by `hx-target-422="#swap-error"` on the form). Template: `info_items/_swap_primary.html`.

**POST `/dashboard/info-items/{id}/swap-primary-by-id`** — same swap flow for an existing InfoSource (form field: `info_source_id` ULID). Deactivates old binding, binds new source, best-effort Watcher patch. Returns 204 + `HX-Redirect`; ULID validation error returns 422 with `<div id="swap-by-id-error">` fragment.

**POST `/dashboard/info-items/{id}/bind-source`** — binds an existing InfoSource (form field: `info_source_id`). Redirects 303 to detail. Returns 409 if an active binding already exists. *(No longer linked from the dashboard UI; use swap-primary-by-id for interactive use.)*

**DELETE `/dashboard/info-items/{id}/info-sources/{source_id}`** — HTMX delete (form POST + route handler); sets `deactivated_at = now()`. Response triggers HTMX redirect to detail.

**POST `/dashboard/info-items/{id}/assign-rep-spec`** — assigns a RepSpec (form field: `rep_spec_id`). Redirects 303 to detail.

**DELETE `/dashboard/info-items/{id}/rep-spec-assignments/{aid}`** — HTMX delete; sets `deactivated_at = now()`. Removes `<tr id="rs-row-{aid}">`.

**PATCH `/dashboard/info-items/{id}/rep-spec-assignments/{aid}/public-url`** — sets `public_url` on an assignment (form field: `public_url`). Returns `info_items/_rep_spec_row.html` fragment replacing the row.

**PATCH `/dashboard/info-items/{id}/rep-fields`** — inline save for rep_fields JSONB (form field: `rep_fields` JSON string). Returns flash fragment into `#rep-fields-flash`.

**POST `/dashboard/info-items/{id}/bind-revision`** — binds a SourceRevision (form field: `source_revision_id`). Redirects 303 to detail.

Partial templates:
- `info_items/_rep_spec_row.html` — reusable `<tr>` fragment for rep-spec assignment rows.
- `info_items/_watcher_status.html` — Watcher health strip; replaces `#watcher-status-strip` via `hx-swap="outerHTML"`. Root element carries the `id` so it survives each swap. Five states: `not_configured`, `not_watching`, `degraded`, `watching` (ok/error/unknown). In the watching state it shows a **Paused** `badge--muted` and hides "Check now" when `watched_item.is_active` is false (an **Archived** badge replaces "Paused" when `watched_item.archived_at` is set), and offers a Pause/Resume toggle (hidden when archived) *(#60)*. Context keys: `state`, `item_id`, `watched_item`, `last_checked_ago`, `last_changed_ago`, `cadence`, `error_message`.
- `info_items/_swap_primary.html` — inline swap-primary panel included inside the `x-data="{swapOpen:false}"` wrapper in Section 2. Renders either "Swap primary source" or "Add primary source" depending on whether `iis_rows` is non-empty. Contains: URL input (`id="swap-url"`), source_specs textarea (`id="swap-specs"`), Preview HTMX button (`hx-include="#swap-url,#swap-specs"`), preview target `#swap-preview`, submit to `swap-primary-source`, and an advanced `<details>` for `swap-primary-by-id`.
- `info_items/_watcher_section.html` — Section 3 Watcher panel; replaces `#watcher-section` via `hx-swap="outerHTML"`. Root element carries both the `id` and `hx-trigger="watcherUpdated from:body"` for event-driven auto-refresh. Four states: `not_configured`, `not_watching`, `degraded`, `watching`. Context keys (watching): `state`, `item_id`, `watched_item`, `spec_summary`, `last_checked_ago`, `last_changed_ago`, `cadence`, `watcher_url`, `error_message`.

### Information Sources (`/dashboard/info-sources/`)  *(Epic 4 — implemented)*

**GET `/dashboard/info-sources/`** — paginated list. Query params: `url_contains` (ilike filter on `url` column), `limit`, `offset`. Shape/fragment filters removed.

**GET `/dashboard/info-sources/new`** — create form. Fields: `url` (text input) + `source_specs` (JSON array textarea, validates JSON on blur).

**POST `/dashboard/info-sources/new`** — form fields: `url` (string), `source_specs` (JSON array string). Calls `create_info_source` tool. Redirects 303 to detail on success. Re-renders form with `errors` dict on `InvalidUrlError`, `InvalidSourceSpecError`, `MixedAlgorithmFamilyError`.

**GET `/dashboard/info-sources/{id}`** — detail page. Sections:
- Header: `info_source_id`, `url`, created_at. No parent link (fragments removed).
- Source Specs JSON array — displayed in `<pre class="code-block">`.
- Edit Specs form — `PATCH /dashboard/info-sources/{id}/source-specs` textarea replaces the specs list. URL is immutable.
- Bound Information Items — table of active `info_item_sources` bindings (item name link, bound date). Role column removed.
- Revision History — last 50 `source_revisions` ordered by `captured_at desc` (fingerprint truncated, captured date, cache status pill).

**POST `/dashboard/info-sources/{id}/source-specs`** — replaces `source_specs` list on an existing InfoSource (form field: `source_specs` JSON array). Redirects 303 to detail on success. Re-renders detail page with `specs_error` inline error on JSON parse failure, schema validation failure, or mixed-family error (422).

### Information Source Revisions (`/dashboard/source-revisions/`)  *(Epic 5 — implemented)*

**GET `/dashboard/source-revisions/`** — paginated list ordered by `captured_at desc`. Optional `info_source_id` filter (ULID). Columns: truncated fingerprint (link to detail), source URL (link to InfoSource detail), captured date, cache status pill (`.status-pill--cached` / `.status-pill--expired` / `.status-pill--missing`).

**GET `/dashboard/source-revisions/{id}`** — detail page. Shows full fingerprint, source link, captured_at, size, media type, cache status + URI + expiry. Danger-zone form for cache clearing (shown only when `content_cache_uri` is set). Bound Information Items table.

**POST `/dashboard/source-revisions/{id}/clear-cache`** — sets `content_cache_uri = NULL` and `content_cache_expires_at = NULL`. Redirects 303 to detail. No request body required.

### Replication Specifications (`/dashboard/rep-specs/`)  *(Epic 6 — implemented)*

**GET `/dashboard/rep-specs/`** — paginated list. Optional `provider` filter (enum: `gcs` / `gdrive` / `ia`). Columns: name (link to detail), provider badge, created_at.

**GET `/dashboard/rep-specs/new`** — create form. Provider `<select>`, name text input, document JSON textarea (`repSpecEditor` Alpine component with validate-on-blur). Returns 200 with errors dict on validation failure.

**POST `/dashboard/rep-specs/new`** — form fields: `provider`, `name`, `document` (JSON string). Calls `create_rep_spec` tool. Redirects 303 to detail on success. Re-renders form with errors on missing provider, missing name, invalid JSON, or `InvalidRepSpecError`.

**GET `/dashboard/rep-specs/{id}`** — detail page. Header: name, provider badge, rep_spec_id, created_at. Document JSON in `<pre class="code-block">`. Active assignments table (item name link, activated_at, public_url).

### `repSpecEditor` Alpine Component

Single-field document editor with client-side JSON parse validation on blur.

**Parameters (factory args):**
- `initialValue: string` — initial document JSON string (pass `{{ document_raw | tojson }}`).
- `initialProvider: string` — initially selected provider (pass `{{ (selected_provider or "") | tojson }}`).

**State:** `provider: string`, `raw: string`, `hasError: boolean`, `errorMsg: string`.

**Methods:** `validate()` — called on `@blur`; attempts `JSON.parse(raw)`, sets `hasError`/`errorMsg`.

**Usage:** `x-data='repSpecEditor({{ document_raw | tojson }}, {{ (selected_provider or "") | tojson }})'` on the create form wrapper, passing server-rendered initial values so Alpine's `x-model` initialises correctly on re-render. Provider `<select x-model="provider">` drives `provider` state for optional template reactions.

### `sortableChips` Alpine Component  *(#49 — implemented)*

Chip strip for selector/rep-field suggestions with client-side re-sort.

Uses the **JSON data island** pattern: chip data is placed in a `<script type="application/json">` child element so JSON never appears inside an HTML attribute (which would require escaping `"` and is fragile). `init()` reads and parses the script element on startup.

**Parameters (factory args):**
- `defaultSort: string` — initial sort mode: `'frequency'` (default), `'asc'`, or `'desc'`.

**State:** `sort: string`, `chips: Array<{label, frequency, value?}>` (reactive, re-sorted on sort change).

**Chip shape:** `{label: string, frequency: number, value?: string}`. The optional `value` field is the dispatch payload when it differs from the display `label` (e.g. a full spec JSON array string vs a human-readable `"algorithm: selector"` label).

**Methods:**
- `setSort(mode)` — sets `sort` and re-sorts `chips` in place.
- `insertChip(label, value?)` — dispatches a `chip-insert` `CustomEvent` on `window` with `{ detail: { label: value ?? label } }`. Parent scopes listen via `@chip-insert.window`.
- `init()` — parses chip data from `<script type="application/json">` inside `$el`; falls back to reading `[data-label]`/`[data-frequency]` DOM attributes.

**Sort controls:** Three pill buttons — `[Frequency ▾]`, `[A → Z]`, `[Z → A]`. Active button gets `.btn--active .btn--sm`; others get `.btn--secondary .btn--sm`. Sort is purely client-side; no server round-trip.

**Usage:**
```html
<!-- Parent listens for chip-insert events -->
<div @chip-insert.window="myProp = $event.detail.label">
  <div x-data="sortableChips('frequency')">
    <script type="application/json">{{ suggestions | tojson }}</script>
    <div style="display:flex;gap:var(--space-1);margin-bottom:var(--space-2);">
      <button type="button" :class="sort==='frequency'?'btn btn--active btn--sm':'btn btn--secondary btn--sm'" @click="setSort('frequency')">Frequency ▾</button>
      <button type="button" :class="sort==='asc'?'btn btn--active btn--sm':'btn btn--secondary btn--sm'" @click="setSort('asc')">A → Z</button>
      <button type="button" :class="sort==='desc'?'btn btn--active btn--sm':'btn btn--secondary btn--sm'" @click="setSort('desc')">Z → A</button>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:var(--space-1);">
      <template x-for="chip in chips" :key="chip.label">
        <button type="button" class="btn btn--secondary btn--sm" @click="insertChip(chip.label, chip.value)">
          <span x-text="chip.label"></span>&nbsp;<span class="text-muted" x-text="'×' + chip.frequency"></span>
        </button>
      </template>
    </div>
  </div>
</div>
```

JS tests in `tests/js/sortable-chips.test.js` (Vitest).

### `registerWizard` Alpine Component  *(#49 — implemented)*

Multi-step Information Item registration wizard. Manages step navigation and form state across the 4-step URL → Selector → Metadata → Review flow. Used on `GET /dashboard/register`.

**Factory args:**
- `initialStep: number` — starting step (1–4; defaults to `1`). The server passes a non-1 value on validation re-renders to re-open at the failing step.

**State:** `step: number`, `url: string`, `sourceSpecs: string`, `itemName: string`, `description: string`, `cadence: string` (Watcher fetch-cadence interval, default `"1d"`), `watchActive: boolean` (default `true`; "Watch active immediately" — false provisions paused).

**Getters:**
- `cadenceLabel` — returns the human-readable label for the selected cadence by reading the text of the matching `<option>` in `$refs.cadenceInput` (no hardcoded map; the server-rendered options are the single source). Shown in the Step 4 review row.
- `watchActiveLabel` — returns "Active immediately" / "Paused" for the Step 4 review row.

**Methods:**
- `init()` — copies `$refs.urlInput.value` into `url`, `$refs.nameInput.value` into `itemName`, `$refs.cadenceInput.value` into `cadence`, and `$refs.watchActiveInput.checked` into `watchActive` so server-rendered field values (e.g. on validation error re-render) populate Alpine state.
- `loadSuggestions()` — fires an HTMX GET to `/dashboard/register/suggest-specs?url=<encoded>`, targeting `#spec-suggestions-panel`. Called by the step-1 "Next" button.
- `prepareSubmit()` — no-op; `x-model` keeps the textarea in sync without a manual step.

**Events:**
- `@chip-insert.window` — receives chip inserts from `sortableChips` and writes the chip value into `sourceSpecs`. Wired on the root element.
- `@preview-name` — receives bubbled `preview-name` events from `previewNameDispatch` children. Pre-fills `itemName` if still blank: `if (!itemName.trim()) itemName = $event.detail.name`. Wired on the root element.

**Usage:**
```html
<div class="entity-section"
     x-data="registerWizard({{ initial_step|default(1) }})"
     @chip-insert.window="sourceSpecs = $event.detail.label"
     @preview-name="if (!itemName.trim()) itemName = $event.detail.name">
  ...
  <input x-ref="urlInput" x-model="url" ...>
  <input x-ref="nameInput" x-model="itemName" ...>
</div>
```

### `previewNameDispatch` Alpine Component  *(#49 — implemented)*

One-shot event dispatcher that reads a suggested page title from a JSON data island child element and fires a bubbling `preview-name` custom event. Used inside the `_preview_result.html` HTMX partial so that a successful preview auto-fills the Name field on step 3.

Uses the **JSON data island** pattern (see CSS doc) — the title is placed in a `<script type="application/json">` child rather than an HTML attribute, avoiding double-quote escaping hazards from `tojson`.

**Events dispatched:** `preview-name` (bubbles) with payload `{ name: string }`.

**Usage:**
```html
{# Inside _preview_result.html, swapped into step 2 via HTMX #}
{% if suggested_name %}
<div x-data="previewNameDispatch">
  <script type="application/json">{{ suggested_name | tojson }}</script>
</div>
{% endif %}
```

The parent `registerWizard` root element catches the event:
```html
@preview-name="if (!itemName.trim()) itemName = $event.detail.name"
```

**Note:** `init()` fires synchronously during Alpine component initialisation (triggered by the MutationObserver on HTMX swap). The event bubbles up the live DOM tree to the `registerWizard` listener. No listener is needed on `previewNameDispatch` itself.

### `repFieldsEditor` Alpine Component  *(#49 — implemented)*

Wrapper for the `rep_fields` textarea + sortableChips suggestion strip on the InfoItem detail hub page. Handles `chip-insert` window events by merging the clicked key into the existing JSON object (preserving other keys) rather than replacing the whole textarea value.

**Methods:**
- `insertKey(key)` — finds `[name=rep_fields]` within `$el`, parses its current value as JSON, adds `key: ""` if absent, and writes back pretty-printed JSON. Falls back gracefully on parse errors.

**Usage:**
```html
<div x-data="repFieldsEditor()" @chip-insert.window="insertKey($event.detail.label)">
  <!-- sortableChips suggestion strip (HTMX-loaded) -->
  <div id="rep-fields-suggestions" hx-get="..." hx-trigger="load" hx-swap="innerHTML"></div>
  <!-- rep_fields form -->
  <form hx-patch="...">
    <textarea name="rep_fields" ...></textarea>
  </form>
</div>
```

### Settings — API Keys (`/dashboard/settings/api-keys`)  *(Epic 2 — implemented)*

**GET** — list current user's keys. Table columns: Label, Prefix, Last Used, Actions. Create form is collapsed; click "+ Add key" (header button) to expand.

**POST** — create new key (`label` form field required). Returns the full page with `new_raw_key` in template context so the `apiKeyReveal` component shows the raw key once. The create form collapses (Alpine `showForm` resets to false) and the new-key reveal panel appears above the table. After navigation, the raw key is gone.

**DELETE `/dashboard/settings/api-keys/{id}`** — HTMX delete; response replaces `<tr id="key-row-{id}">` with empty string (removes row). Returns 404 if key belongs to a different user.

**PATCH `/dashboard/settings/api-keys/{id}`** — rename label (`label` form field, submitted via `hx-include`). Returns `settings/_api_key_row.html` fragment replacing the row in view mode. Returns 404 if key belongs to a different user.

Partial template: `settings/_api_key_row.html` — reusable `<tr x-data="apiKeyRow">` fragment used both in list render and as PATCH response. Starts in view mode (`editing: false`). Edit button switches to edit mode; Save sends the PATCH; Cancel reverts without a server call.
