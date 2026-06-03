# Archiver Dashboard — UI Reference

**Page inventory, HTMX swap patterns, Alpine.js component catalogue, flash/modal usage guide.**

> **AGENTS.md enforcement:** This file must be updated in the same commit as any Jinja2 template change, new route, or new Alpine.js component.

---

## URL Structure

```
/dashboard/                      Home (Epic 7)
/dashboard/info-items/           Information Items list
/dashboard/info-items/{id}       Information Item detail
/dashboard/info-items/new        Create Information Item (multi-step wizard)
/dashboard/info-sources/         Information Sources list
/dashboard/info-sources/{id}     Information Source detail
/dashboard/info-sources/new      Create Information Source
/dashboard/source-revisions/     Information Source Revisions list
/dashboard/source-revisions/{id} Information Source Revision detail
/dashboard/rep-specs/            Replication Specifications list
/dashboard/rep-specs/{id}        Replication Specification detail
/dashboard/rep-specs/new         Create Replication Specification
/dashboard/settings/api-keys     API Keys management
```

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

Server returns `HX-Trigger: {"showFlash": {"level": "success", "body": "Saved."}}` alongside any mutating response. `flash.js` injects `.flash--*` divs into `#flash-region`. Auto-dismisses after 6 s.

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

### Information Items (`/dashboard/info-items/`)  *(Epic 3 — implemented)*

**GET `/dashboard/info-items/`** — paginated list with optional `name_contains` search. Filter panel: search input (flex-fill) + Search button (right-aligned via `margin-left:auto`). Columns: name (link to detail), Information Source (primary source URL linked to InfoSource detail; `—` if none), Observed (max `captured_at` of the primary source's revisions formatted `%Y-%m-%d %H:%M`; `—` if none).

**GET `/dashboard/info-items/new`** — three-step `infoItemWizard` form. Step 1: name/description/owner/rep_fields (`jsonFieldEditor`). Step 2: optional `initial_url` text input + `initial_source_specs` JSON array (`jsonFieldEditor`). Step 3: review and submit.

**POST `/dashboard/info-items/new`** — creates InfoItem (and optionally an initial InfoSource binding). Form fields: `initial_url` (string) + `initial_source_specs` (JSON array). Redirects 303 to detail on success. Returns 422 with re-rendered form on validation error.

**GET `/dashboard/info-items/{id}`** — detail page. Header uses `.detail-grid` with `.detail-grid__item` / `.detail-grid__label` / `.detail-grid__value` divs (not `dl`/`dt`/`dd`) to show name, description, owner, rep_fields (shows `—` when empty), created_at. Three Alpine.js tabs rendered with `.tabs` / `.tabs__list` / `.tabs__btn` / `.tabs__btn--active` (not `btn--ghost`, which is topbar-only):
- *Sources* — table of active `info_item_sources` bindings; URL column shows InfoSource detail link + external `↗` link; bind-source form uses `filter-card filter-card--stacked` (multi-field vertical form).
- *Replication Specs* — table of active `info_item_rep_specs` assignments + assign form (`filter-card`, single-field).
- *Revision History* — last 50 `info_item_source_revisions` ordered by `bound_at desc`.

**POST `/dashboard/info-items/{id}/bind-source`** — binds an existing InfoSource (form field: `info_source_id`). Redirects 303 to detail `?tab=sources`. Returns 409 if an active binding already exists.

**DELETE `/dashboard/info-items/{id}/info-sources/{source_id}`** — HTMX delete; sets `deactivated_at = now()`. Response replaces `<tr id="source-row-{source_id}">` with empty (removes row).

**POST `/dashboard/info-items/{id}/assign-rep-spec`** — assigns a RepSpec (form field: `rep_spec_id`). Redirects 303 to detail `?tab=repspecs`.

**DELETE `/dashboard/info-items/{id}/rep-spec-assignments/{aid}`** — HTMX delete; sets `deactivated_at = now()`. Removes `<tr id="rs-row-{aid}">`.

**PATCH `/dashboard/info-items/{id}/rep-spec-assignments/{aid}/public-url`** — sets `public_url` on an assignment (form field: `public_url`). Returns `info_items/_rep_spec_row.html` fragment replacing the row.

**POST `/dashboard/info-items/{id}/bind-revision`** — binds a SourceRevision (form field: `source_revision_id`). Redirects 303 to detail `?tab=revisions`.

Partial template: `info_items/_rep_spec_row.html` — reusable `<tr>` fragment used in detail list and as PATCH public-url response.

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

### Settings — API Keys (`/dashboard/settings/api-keys`)  *(Epic 2 — implemented)*

**GET** — list current user's keys. Table columns: Label, Prefix, Last Used, Actions. Create form is collapsed; click "+ Add key" (header button) to expand.

**POST** — create new key (`label` form field required). Returns the full page with `new_raw_key` in template context so the `apiKeyReveal` component shows the raw key once. The create form collapses (Alpine `showForm` resets to false) and the new-key reveal panel appears above the table. After navigation, the raw key is gone.

**DELETE `/dashboard/settings/api-keys/{id}`** — HTMX delete; response replaces `<tr id="key-row-{id}">` with empty string (removes row). Returns 404 if key belongs to a different user.

**PATCH `/dashboard/settings/api-keys/{id}`** — rename label (`label` form field, submitted via `hx-include`). Returns `settings/_api_key_row.html` fragment replacing the row in view mode. Returns 404 if key belongs to a different user.

Partial template: `settings/_api_key_row.html` — reusable `<tr x-data="apiKeyRow">` fragment used both in list render and as PATCH response. Starts in view mode (`editing: false`). Edit button switches to edit mode; Save sends the PATCH; Cancel reverts without a server call.
