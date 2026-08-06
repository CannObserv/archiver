# Archiver Dashboard — Page Inventory

**What each dashboard screen renders, and the routes behind it.**

Shared mechanics live in [UI.md](UI.md) — the URL map, the proxy-header auth
gate, HTMX swap patterns (flash messages, `hx-target-422`), and the
detail-screen conventions this file refers to by name. Alpine components are
catalogued in [COMPONENTS.md](COMPONENTS.md).

Every route below is auth-gated; see UI.md § Authentication. The entries do not
repeat it.

> **AGENTS.md enforcement:** update this file in the same commit as any Jinja2
> template change or new/changed dashboard route.

---

## Home (`/dashboard/`)

**GET `/dashboard/`** — summary dashboard. Four count tiles in nav order (Information Items, Information Sources, Information Source Revisions, Replication Specifications), each linking to its list page. Service health indicator loads via `hx-get="/dashboard/health" hx-trigger="load"` — non-blocking, showing a "checking…" badge until HTMX fires. Recent Changes table: last 10 SourceRevisions ordered by `captured_at desc`; columns Information Source (URL, links to source detail), Source Revision (truncated fingerprint, links to revision detail), Observed (captured_at as `%Y-%m-%d %H:%M`).

**GET `/dashboard/health`** — HTMX partial. Returns `<span class="badge badge--success">ok</span>`.

**GET `/dashboard/health/watcher`** — HTMX partial calling `WatcherClient.health_check()` (`GET /health` on Watcher). **GET `/dashboard/health/redis`** — HTMX partial calling `redis.ping()`. Both log a warning on `degraded` and `error`; `not configured` returns before any logging:

| Badge | `…/health/watcher` | `…/health/redis` |
|---|---|---|
| `badge--success` "ok" | HTTP 200 | ping succeeded |
| `badge--warning` "degraded" | reachable, non-200 status; `title` contains "Watcher returned {status}" | — |
| `badge--danger` "error" | network/connect failure; `title` contains the exception message | `title` contains the exception message |
| `badge--muted` "not configured" | `WATCHER_BASE_URL` unset | `ARCHIVER_REDIS_URL` unset |

## Domain pages (`/dashboard/domains/`)

**GET `/dashboard/domains/`** — paginated list. Columns: Domain (linked to detail), Sources (count), Status badge, Created. Filter bar: `?is_active=true|false|` (all). Source counts come from a GROUP BY query.

**GET `/dashboard/domains/{name}`** — detail. `.entity-card` header (canonical detail-screen pattern, #82): `.eyebrow` "Domain" kicker → `<h1 class="entity-card__title" id="domain-heading" tabindex="-1">` with the copyable domain name → `.detail-grid` (Status badge, created_at UTC). Operator notes (HTMX inline edit); linked Information Sources table, its heading count from a route `COUNT` so it stays accurate across pagination (#82), source URLs carrying `open_button`. `has_more` stays on its own `limit+1` probe (see UI.md § **Related-collection tables**). Two empty states: an overshot `offset` (stale bookmark, or rows removed mid-session) renders "No sources on this page" with a link back to `?offset=0`, a genuinely empty collection "No Information Sources registered for this domain yet" — the heading count would otherwise contradict the "none registered" copy. **Archive** lives in a `.danger-zone` block at the bottom, shown only while the domain is active (`.btn--danger` + static confirm). **Restore** is recovery, not destruction, so it sits in the header Status field inline next to the "archived" badge (`.btn--secondary`); once archived the danger zone is hidden entirely. Both stay full-page POST→303 by design — see the *allowed variant* note under UI.md § **HTMX mutations**.

**POST `/dashboard/domains/{name}/notes`** — HTMX partial; replaces `#notes-section` with `domains/_notes_partial.html`. Saves notes inline.

**POST `/dashboard/domains/{name}/archive`** — sets `archived_at`, redirects 303 to detail. Triggered from the danger-zone Archive button.

**POST `/dashboard/domains/{name}/restore`** — clears `archived_at`, redirects 303 to detail. Triggered from the header Restore button.

Templates: `domains/list.html`, `domains/detail.html`, `domains/_notes_partial.html`.

## Registration flow (`/dashboard/register`)

4-step flow (#49): URL → Selector → Metadata → Review & Submit. Full spec:
`docs/plans/2026-06-04-dashboard-ux-redesign-design.md`. State lives in the
`registerWizard` component ([COMPONENTS.md](COMPONENTS.md)).

**Rolling step-summary bar**: `#wizard-summary` (`role="group"`,
`aria-label="Completed steps"`), rendered between the step-indicator badges and
the form, visible from step 2 on (`x-show="step>=2"`). Completed steps show as
clickable chips (`.btn.btn--secondary.btn--sm`) that jump back to their step —
same semantics as the step-4 Edit buttons:

- **URL chip** (step ≥ 2) — the entered URL (CSS-truncated at 20rem, full value
  in `title`) plus a parenthesised domain note: `(known domain: <host>)` /
  `(new domain: <host>)` when a url-check result has landed for the current
  hostname (`domainSummary`), else just `(<host>)` (`urlHostname`).
- **Selector chip** (step ≥ 3) — `selectorSummary`, also reused for the step-4
  review Selector row.
- **Name chip** (step ≥ 4) — `itemName`.

**Step 3 (Metadata) — Watcher settings (advanced)**: a collapsed `<details>`
block exposes two controls.

A **Fetch cadence** `<select.form-select>` (`name="cadence"`,
`x-model="cadence"`, `x-ref="cadenceInput"`). Options and default are rendered
server-side from the shared cadence vocabulary (`src/dashboard/cadence.py`:
Hourly `1h` / Every 6 hours `6h` / Daily `1d` (default) / Weekly `7d`), injected
as the `cadence_labels` / `default_cadence` Jinja globals. The value is a Watcher
interval string; on submit the server forwards `{"interval": <value>}` as the
WatchedItem `default_schedule_config` during provisioning (best-effort,
post-commit) **only when the value is a recognised option**, otherwise `None` so
Watcher applies its own default — the handler never fabricates a cadence. The
selection is sticky across validation re-renders (`cadence_value` → `selected`
attribute). Step 4 review shows the label via `cadenceLabel`. The same vocabulary
backs `_format_cadence` on the InfoItem Watcher section, so recognised cadences
display with the same friendly labels in both places.

A **Watch active immediately** checkbox (`<input type="checkbox"
id="reg-watch-active" name="watch_active" value="on"`, `x-model="watchActive"`,
`x-ref="watchActiveInput"`), checked by default. Checked → the server omits
`is_active` so Watcher provisions the WatchedItem active; unchecked (the checkbox
sends nothing) → the server forwards `is_active=False` to provision it **paused**.
Sticky across validation re-renders (`watch_active_value` → `checked` attribute,
defaulting to checked via `|default(true)`). Step 4 review shows "Active
immediately" / "Paused" via `watchActiveLabel`.

---

## Information Items (`/dashboard/info-items/`)

**GET `/dashboard/info-items/`** — paginated list with optional `name_contains` search. Filter panel: search input (flex-fill) + Search button (right-aligned via `margin-left:auto`). Columns: name (link to detail), Information Source (primary source URL linked to InfoSource detail; `—` if none), Observed (max `captured_at` of the primary source's revisions, `%Y-%m-%d %H:%M`; `—` if none).

**GET `/dashboard/info-items/new`** — 301 redirect to `/dashboard/register`.

**POST `/dashboard/info-items/new`** — legacy direct-create, still live. Form fields: `name`, `description`, `owner`, `rep_fields` (JSON), `initial_url` (string), `initial_source_specs` (JSON array). 303 to detail on success; 422 re-rendering `info_items/new.html` on validation error. Interactive registration goes through `/dashboard/register`.

**GET `/dashboard/info-items/{id}`** — 5-section vertical-scroll hub page (`info_items/detail.html`):

1. **Overview** — `.entity-card` header (canonical detail-screen pattern, #81): `.eyebrow` "Information Item" kicker → `<h1 class="entity-card__title" id="info-item-heading" tabindex="-1">` name → copyable ULID (shared `copyable` macro) → domain badge linking to `/dashboard/domains/{name}`, or a muted "No primary source" when unbound; `.detail-grid` with description, owner (if set), created_at. Watcher status is deliberately absent here — the status and its controls live in section 3 (#62).

2. **Information Sources** — `x-data="{swapOpen:false}"` wrapper around a `data-table` of active `info_item_sources` bindings (columns: URL, Domain, Spec, Bound, Actions); the first row carries a brand left-border marking it primary. The **Spec** column summarises the InfoSource's primary `source_specs` entry (`_format_spec_summary`, e.g. `css · 2 specs`) out of `spec_summary_by_source_id`, computed by the detail route — the spec belongs here, not in the Watcher section (#62). The Actions cell on the primary row holds a "Swap primary" / "Cancel" toggle (`@click="swapOpen=!swapOpen"`) that reveals `info_items/_swap_primary.html` inside `<div x-show="swapOpen" x-cloak>`; with no active bindings that panel (`id="swap-panel"`) renders unconditionally, titled "Add primary source". Its "author new source" form posts with `hx-target-422="#swap-error"` and succeeds with 204 + `HX-Redirect`; the "bind by ID" `<details>` sub-form does the same against `#swap-by-id-error`.

3. **Watcher** — the `<h2>` is itself the Watcher deeplink ("Watcher ↗", `target=_blank`) when the item is watched: the detail route computes `watcher_deeplink` from `WATCHER_PUBLIC_BASE_URL` (falling back to `WATCHER_BASE_URL`) + `item.watcher_item_id`, and renders a plain "Watcher" header when unwatched (#62). Body: `<div id="watcher-section">` loaded async via `hx-trigger="load"` + `hx-get="…/watcher-section"` + `hx-swap="outerHTML"`; the root element also carries `hx-trigger="watcherUpdated from:body"` so the panel self-refreshes whenever an action fires that event. Template `info_items/_watcher_section.html`, four states: `not_configured`, `not_watching` ("Begin Watching" button), `degraded`, `watching` (health badge, timestamps, cadence, "Check now", "Re-sync"). It carries no URL or spec summary — both are reachable from section 2 — and no "View in Watcher" link, because the deeplink is the section header. Action buttons are `.btn--secondary .btn--sm`.

   **Begin Watching** provisions a WatchedItem on demand. When Watcher already has one for this InfoItem (Archiver's `watcher_item_id` is NULL — e.g. a pre-#55 item), provisioning 409s and `provision_on_create` adopts the existing WatchedItem's ID rather than failing. A paused WatchedItem (`watched_item.is_active` false, not archived) shows a **Paused** `badge--muted` beside the health badge, hides "Check now" (Watcher 409s on check-now of a paused item), and reads "Resume" on the toggle; otherwise the toggle reads "Pause". An archived WatchedItem (`watched_item.archived_at` set) shows an **Archived** badge instead of "Paused" and hides the toggle entirely, since Watcher 409s there and archive/restore owns activation.

4. **Revision History** — `data-table` of the last 50 `source_revisions` captured across the item's InfoSource **bindings** — the active primary **plus** previous primaries (deactivated `info_item_sources` rows, preserved as succession history) — ordered `captured_at desc`, count in the heading. Columns: Fingerprint (linked to revision detail), Source (the InfoSource URL, linked to source detail — present because an item accumulates successive sources over its life), Captured (UTC), Cache (`.status-pill--cached/expired/missing`). The timeline is a query over bindings, **not** over the `info_item_source_revisions` pin table, which was dropped in archiver#101. The route computes `revisions` + `rev_sources_by_id`, the latter covering deactivated previous primaries that the active-only `sources_by_id` misses.

5. **Replicator** — two sub-sections:
   - *Rep Fields* — `x-data="repFieldsEditor()"` wrapper; HTMX-loaded `sortableChips` suggestions (`hx-trigger="load"`); `<textarea name="rep_fields">` with `PATCH /dashboard/info-items/{id}/rep-fields` inline save; flash target `#rep-fields-flash`.
   - *Replication Specs* — `info_items/_rep_spec_assignments.html` (wrapper `#ii-rep-spec-assignments`, heading `#ii-rep-spec-heading`): `data-table` of active `info_item_rep_specs` assignments plus an assign form (`filter-card`, `rep_spec_id` field). Rows (`_rep_spec_row.html`) show `activated_at` UTC and an `open_button` next to the `public_url` input when a value is set. HTMX deactivate re-renders the whole section (table + empty state) and focuses the heading; per-row public-url edits swap the individual row.

**The four Watcher action POSTs share a contract.** `begin-watching`, `check-now`,
`toggle-watch-active`, and `resync-watcher` each re-render
`info_items/_watcher_status.html` and set `HX-Trigger: {"watcherUpdated":{}}`.
Their forms use `hx-swap="none"`, so the rendered body is discarded and the
trigger is what refreshes `#watcher-section`. On failure each adds a `showFlash`
error to that trigger rather than 500ing, so a Watcher outage is surfaced instead
of swallowed (#60, #61). A `WatcherNotFound` (404 — the WatchedItem was permanently deleted
in Watcher) NULLs the stale `watcher_item_id`, commits, and flashes "no longer
watched — it was removed in Watcher" so the re-render falls back to
`not_watching` and "Begin Watching" reappears; **only a confirmed 404 clears the
link** — transient failures (network/5xx) render `degraded` and retain it
(CannObserv/archiver#63). Any other failure flashes "Watcher is unavailable". The
entries below name only what each route adds.

**GET `/dashboard/info-items/{id}/watcher-status`** — HTMX partial calling Watcher `get_watched_item`; renders ok/error/unknown/not_watching/not_configured/degraded. No page embeds it: it is reachable directly, and is the (discarded) response body of the four action POSTs.

**GET `/dashboard/info-items/{id}/watcher-section`** — HTMX partial calling Watcher `get_watched_item`; renders not_configured/not_watching/degraded/watching. Loaded on page init via `hx-trigger="load"` and re-fetched on the `watcherUpdated` body event. The Watcher deeplink lives on the section's `<h2>`, rendered by the detail page rather than by this partial.

**POST `/dashboard/info-items/{id}/check-now`** — proxies to Watcher `check-now`. If `check_now` fails, re-fetches via `get_watched_item` and shows `degraded` only if that also fails. A `WatcherConflict` (409 — check-now on a paused item) flashes "resume it first".

**POST `/dashboard/info-items/{id}/begin-watching`** — provisions a WatchedItem for an InfoItem that has no `watcher_item_id`, via `provision_on_create`, which returns a `WatcherSyncOutcome`. `FAILED` (provisioning attempted, Watcher unavailable) flashes an error; `SKIPPED` (no Watcher configured) flashes nothing. With no active primary source to watch, flashes "No primary source to watch — bind one first."

**POST `/dashboard/info-items/{id}/resync-watcher`** — PATCHes the WatchedItem with the current primary URL and specs via `sync_on_source_swap`, which returns a `WatcherSyncOutcome`; `FAILED` flashes "Couldn't re-sync with Watcher — it's unavailable". With no active primary source, flashes "No primary source to re-sync — bind one first." A deleted WatchedItem 404s inside `sync_on_source_swap` and is swallowed to `FAILED`, but the trailing `_watcher_status.html` re-render re-fetches, 404s, and reconciles to `not_watching` — so a deleted item still recovers, even though the flash stays the generic "unavailable" (the 404 is opaque to the shared core helper).

**POST `/dashboard/info-items/{id}/toggle-watch-active`** — pauses or resumes the WatchedItem via `patch_watched_item(is_active=…)`. Form field `active` is the desired target state ("true" → resume, anything else → pause); the button submits the opposite of the current state. A `WatcherConflict` (409 — e.g. pause/resume on an archived item) flashes "the item may be archived". No-op, with no patch, when the InfoItem has no `watcher_item_id`.

**POST `/dashboard/info-items/{id}/swap-primary-source`** — inline primary-source swap: creates a new InfoSource (form fields: `url`, `source_specs` JSON array), deactivates the old active binding, binds the new source, best-effort `patch_watched_item` post-commit. 204 + `HX-Redirect` to detail on success; 422 with a `<div id="swap-error">` fragment on validation error. Template: `info_items/_swap_primary.html`.

**POST `/dashboard/info-items/{id}/swap-primary-by-id`** — the same swap flow for an existing InfoSource (form field: `info_source_id` ULID). Deactivates the old binding, binds the new source, best-effort Watcher patch. 204 + `HX-Redirect`; a ULID validation error returns 422 with a `<div id="swap-by-id-error">` fragment.

**POST `/dashboard/info-items/{id}/bind-source`** — binds an existing InfoSource (form field: `info_source_id`). 303 to detail; 409 if an active binding already exists. Not linked from the dashboard UI — interactive use goes through swap-primary-by-id.

**DELETE `/dashboard/info-items/{id}/info-sources/{source_id}`** — HTMX delete (form POST + route handler); sets `deactivated_at = now()`. Response triggers an HTMX redirect to detail.

**POST `/dashboard/info-items/{id}/assign-rep-spec`** — assigns a RepSpec (form field: `rep_spec_id`). 303 to detail.

**DELETE `/dashboard/info-items/{id}/rep-spec-assignments/{aid}`** — HTMX delete; sets `deactivated_at = now()`, idempotent (skipped if already deactivated). Returns the re-rendered `info_items/_rep_spec_assignments.html` fragment (targets `#ii-rep-spec-assignments`), which updates the table/empty-state and moves focus to the section heading.

**PATCH `/dashboard/info-items/{id}/rep-spec-assignments/{aid}/public-url`** — sets `public_url` on an assignment (form field: `public_url`). Returns the `info_items/_rep_spec_row.html` fragment replacing the row.

**PATCH `/dashboard/info-items/{id}/rep-fields`** — inline save for `rep_fields` JSONB (form field: `rep_fields` JSON string). Returns a flash fragment into `#rep-fields-flash`.

Partial templates under `info_items/`:

| Template | Swap target (`outerHTML`) | States |
|---|---|---|
| `_rep_spec_row.html` | its own `<tr>` | — |
| `_swap_primary.html` | `#swap-panel` | — |
| `_watcher_status.html` | `#watcher-status-strip` | `not_configured`, `not_watching`, `degraded`, `watching` (ok/error/unknown) |
| `_watcher_section.html` | `#watcher-section` | `not_configured`, `not_watching`, `degraded`, `watching` |

Each root element carries its own `id`, so it survives the swap that replaces it;
`_watcher_section.html`'s root additionally carries `hx-trigger="watcherUpdated
from:body"` for the event-driven auto-refresh. Both Watcher partials take the
context keys `state`, `item_id`, `watched_item`, `last_checked_ago`,
`last_changed_ago`, `cadence`, `error_message`, and both render the Paused /
Archived badge and toggle described in section 3.

`_swap_primary.html` is a full-width card — no max-width, so it spans the
bindings table — titled "Swap primary source" or "Add primary source" depending
on whether `iis_rows` is non-empty. It holds a URL input (`id="swap-url"`,
`.form-input`), a source_specs textarea (`id="swap-specs"`, `.form-textarea`), a
Preview HTMX button (`.btn--secondary`, `hx-include="#swap-url,#swap-specs"`)
targeting `#swap-preview`, the submit to `swap-primary-source` (`.btn--primary`),
and an advanced `<details>` for `swap-primary-by-id` (`.form-input` field +
`.btn--secondary` Bind button).

## Information Sources (`/dashboard/info-sources/`)

**GET `/dashboard/info-sources/`** — paginated list. Query params: `url_contains` (ilike filter on the `url` column), `limit`, `offset`.

**GET `/dashboard/info-sources/new`** — create form. Fields: `url` (text input) + `source_specs` (JSON array textarea, validates JSON on blur).

**POST `/dashboard/info-sources/new`** — form fields: `url` (string), `source_specs` (JSON array string). Calls `create_info_source`. 303 to detail on success; re-renders the form with an `errors` dict on `InvalidUrlError`, `InvalidSourceSpecError`, `MixedAlgorithmFamilyError`.

**GET `/dashboard/info-sources/{id}`** — detail page. Sections:

- Header: `.entity-card` (canonical pattern, #79) — `.eyebrow` "Information Source" → `<h1 class="entity-card__title" id="info-source-heading" tabindex="-1">` with the `url` in `<code>` → an `open_button` to the URL → copyable `info_source_id` → `.detail-grid` (created_at UTC).
- Source Specification editor — the `info_sources/_source_specs_card.html` partial, extracted so the update-specs action can swap it in place (root `#source-specs-card`, heading `#source-specs-heading`, titled "Source Specification"). The `sourceSpecsCard(startEditing)` component (`main.js`; not in the COMPONENTS.md catalogue — it exists only for this card) gates it: **view mode** (`x-show="!editing"`) shows the current `source_specs` array in `<pre class="code-block">` with an **Edit** button; Edit reveals the textarea form (`x-show="editing"`) with **Cancel** (`btn--secondary`, for border parity with the `apiKeyRow` Cancel; `@click="cancel()"` resets the textarea to the stored specs and returns to view mode with no server call) and **Save** (submits the `POST .../source-specs` replace). The editor has no visible `<label>` — the card heading already names the control, and a label appearing only on Edit caused layout jank — so `aria-label="Source Specification (JSON Array)"` keeps the textarea named for assistive tech, matching the create-form label wording. The canonical stored specs ride in a `<script type="application/json">` data island read by `init()`, never in an HTML attribute: `tojson` output embedded in a double-quoted attribute breaks out of the quotes (the `sortableChips` convention; #100). The card opens in edit mode when `specs_error` is set (`sourceSpecsCard(true)`) so the error and the operator's submitted text stay visible. No `x-cloak` — without JS both view and editor render and Save posts normally (progressive enhancement). The URL is immutable.
- Other Sources at This URL — shown only when other InfoSources share this `url` (the model allows several sources per URL, #79 #8); count in the heading, capped at 50 via a `limit+1` probe and rendered "50+" beyond that, each linked by `info_source_id` with its created date UTC.
- Bound Information Items — table of active `info_item_sources` bindings (count in heading; item name link, bound date UTC).
- Revision History — last 50 `source_revisions` ordered by `captured_at desc` (count in heading; fingerprint truncated, captured date UTC, cache status pill).

**POST `/dashboard/info-sources/{id}/source-specs`** — replaces the `source_specs` list on an existing InfoSource (form field: `source_specs` JSON array). An **editor card** (UI.md § **Editor cards**) against `#source-specs-card`, error key `specs_error` (#79 #7). Rejections: JSON parse failure, schema validation, mixed algorithm family.

## Information Source Revisions (`/dashboard/source-revisions/`)

**GET `/dashboard/source-revisions/`** — paginated list ordered by `captured_at desc`. Optional `info_source_id` filter (ULID). Columns: truncated fingerprint (link to detail), source URL (link to InfoSource detail), captured date, cache status pill (`.status-pill--cached` / `.status-pill--expired` / `.status-pill--missing`).

**GET `/dashboard/source-revisions/{id}`** — detail page, and the reference implementation of the UI.md detail-screen conventions. The header lives in `source_revisions/_detail_card.html`, extracted so clear-cache can swap it in place (root `#revision-card`): `.eyebrow` "Information Source Revision" above an `<h1>` whose title is the copyable `source_revision_id`. `.detail-grid` carries the copyable full fingerprint and the Information Source, both on `.detail-grid__item--full` rows so long values extend horizontally; the Information Source value holds the internal source-detail link plus an `open_button` to the target URL. Then captured_at (UTC), size (if set), media type (if set), and cache status. The Cache value shows a status pill plus the `content_cache_uri` — with an `open_button` when `http(s)`, otherwise copyable — and an expiry line. "View all revisions for this source →" deeplinks the list as `?info_source_id=`. A danger-zone clear-cache form shows only when `content_cache_uri` is set.

**POST `/dashboard/source-revisions/{id}/clear-cache`** — sets `content_cache_uri = NULL` and `content_cache_expires_at = NULL`. HTMX requests (`hx-post`, `hx-target="#revision-card"`, `hx-confirm`) get the re-rendered `_detail_card.html` swapped in place plus an `HX-Trigger: showFlash` success toast; non-HTMX requests fall back to a 303 to detail. No request body required.

## Replication Specifications (`/dashboard/rep-specs/`)

**GET `/dashboard/rep-specs/`** — paginated list. Optional `provider` filter (enum: `gcs` / `gdrive` / `ia`). Columns: name (link to detail), provider badge, created_at.

**GET `/dashboard/rep-specs/new`** — create form. Provider `<select>`, name text input, document JSON textarea (the `repSpecEditor` component, validate-on-blur). Returns 200 with an errors dict on validation failure.

**POST `/dashboard/rep-specs/new`** — form fields: `provider`, `name`, `document` (JSON string). Calls `create_rep_spec`. 303 to detail on success; re-renders the form with errors on missing provider, missing name, invalid JSON, or `InvalidRepSpecError`.

**GET `/dashboard/rep-specs/{id}`** — detail page.

- Header: `.entity-card` (canonical pattern, #80) — `.eyebrow` "Replication Specification" → `<h1 class="entity-card__title" id="rep-spec-heading" tabindex="-1">` name → copyable `rep_spec_id` → `.detail-grid` (provider badge, created_at UTC, plus **Updated** UTC *only when* `updated_at` is non-null — a null means "never edited", and rendering `created_at` there would blur that distinction, #83).
- Document card — the `rep_specs/_document_card.html` partial, extracted so the update-document action can swap it in place (root `#rep-spec-document-card`, heading `#rep-spec-document-heading`). Shows the stored document JSON in `<pre class="code-block">`, then **conditionally** an edit form: the textarea renders only while the RepSpec is a *draft*, meaning zero `info_item_rep_specs` rows, active **or** deactivated. That count comes from `assignment_count()`, deliberately not `_load_active_assignments`, because a deactivated assignment still means a replication run happened under that document. A non-draft renders an `.alert--info` "frozen" notice with the assignment count instead of the form (#83; clone + migrate is #95).
- Active assignments — `rep_specs/_assignments.html` (wrapper `#rep-spec-assignments`): count in heading; item name link, activated_at UTC, `public_url` with an `open_button`, and a **Deactivate** action. Deactivate is `hx-delete` to the RepSpec-scoped route below, targeting `#rep-spec-assignments` (`outerHTML`) so the row set, count, and empty-state re-render together. Assignments are manageable from either the RepSpec or the InfoItem screen (#80).

**POST `/dashboard/rep-specs/{id}/document`** — replaces the `document` on a **draft** RepSpec (form field: `document`, a JSON object string). An **editor card** (UI.md § **Editor cards**) against `#rep-spec-document-card`, error key `doc_error` — the same shape as the InfoSource source-specs editor. Whole-document replace, not merge (#83). Rejections: JSON parse failure, schema/sub-schema validation, an attempted `provider` change (immutable), and `RepSpecNotDraftError` — the last re-checked server-side, because a rendered editor goes stale if the spec acquires an assignment mid-edit.

**DELETE `/dashboard/rep-specs/{id}/assignments/{aid}`** — deactivates a RepSpec assignment (sets `deactivated_at`); the assignment must belong to `{id}` (404 otherwise). Returns the re-rendered `rep_specs/_assignments.html` fragment.

## Settings — API Keys (`/dashboard/settings/api-keys`)

**GET** — lists the current user's keys. Table columns: Label, Prefix, Last Used, Actions. The create form starts collapsed; "+ Add key" in the header expands it.

**POST** — creates a key (`label` form field required). Returns the full page with `new_raw_key` in the template context so `apiKeyReveal` shows the raw key once; the create form collapses (`showForm` resets to false) and the reveal panel appears above the table. After navigation the raw key is gone.

**DELETE `/dashboard/settings/api-keys/{id}`** — HTMX delete; the response replaces `<tr id="key-row-{id}">` with an empty string, removing the row. 404 if the key belongs to a different user.

**PATCH `/dashboard/settings/api-keys/{id}`** — renames the label (`label` form field, submitted via `hx-include`). Returns the `settings/_api_key_row.html` fragment replacing the row in view mode. 404 if the key belongs to a different user.

Partial template: `settings/_api_key_row.html` — reusable `<tr x-data="apiKeyRow">` used both in the list render and as the PATCH response. Starts in view mode (`editing: false`); Edit switches to edit mode, Save sends the PATCH, Cancel reverts with no server call.
