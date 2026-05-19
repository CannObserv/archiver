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

### `apiKeyReveal`

Reveal-once modal for newly created API keys.

**State:**
- `rawKey: string` — the one-time raw key value.
- `copied: boolean` — clipboard copy feedback.

**Methods:**
- `open(key)` — set `rawKey`, open the modal, focus the first focusable element.
- `copy()` — write `rawKey` to clipboard, set `copied = true` for 2 s.

**Usage:** Included via `x-data="apiKeyReveal" x-init="open('{{ new_raw_key }}')"` on the reveal section returned by `POST /dashboard/settings/api-keys`. The raw key is embedded server-side in the one-time render; it is not stored client-side beyond the DOM lifetime.

---

### `infoItemWizard`

Multi-step create form for Information Items.

**State:**
- `step: number` — current step (1 = Basics, 2 = Source, 3 = Review).
- `name: string`, `description: string`, `owner: string` — form field values.
- `repFieldsRaw: string` — raw JSON string for `rep_fields` (written by nested `jsonFieldEditor`).
- `sourceSpecRaw: string` — raw JSON string for `source_spec` (written by nested `jsonFieldEditor`).

**Methods:**
- `nextStep()` — advance to next step; step 1 guards that `name` is non-empty.
- `prepareSubmit()` — called on form submit; no-op (jsonFieldEditor writes directly into root props on blur).

**Usage:** `x-data="infoItemWizard"` on the outer `<div>`. Nested `jsonFieldEditor` components read/write `$root.repFieldsRaw` and `$root.sourceSpecRaw`. Hidden `<input>` elements bind via `:value` to these root properties so the standard form POST captures the current JSON.

---

### `sourceSpecEditor`

Single-field SourceSpec JSON editor with client-side JSON parse validation on blur.

**State:**
- `raw: string` — raw textarea value (bound via `x-model`).
- `hasError: boolean` — true when the current value is not valid JSON.
- `errorMsg: string` — human-readable parse error.

**Methods:**
- `validate()` — called on `@blur`. Attempts `JSON.parse(raw)`; sets `hasError`/`errorMsg`.

**Usage:** `x-data="sourceSpecEditor"` on the outer `<div>` wrapping the create form. The `<textarea name="source_spec" x-model="raw" @blur="validate()">` submits directly as a form field — no hidden input needed.

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

### Home (`/dashboard/`)  *(Epic 7)*
Summary counts (InfoItems, InfoSources, RepSpecs, SourceRevisions). Recent SourceRevision captures (last 10). Service health indicator.

### Information Items (`/dashboard/info-items/`)  *(Epic 3 — implemented)*

**GET `/dashboard/info-items/`** — paginated list with optional `name_contains` search. Columns: name (link to detail), primary source URL, active rep spec count, created_at.

**GET `/dashboard/info-items/new`** — three-step `infoItemWizard` form. Step 1: name/description/owner/rep_fields (`jsonFieldEditor`). Step 2: optional SourceSpec JSON (`jsonFieldEditor`). Step 3: review and submit.

**POST `/dashboard/info-items/new`** — creates InfoItem (and optionally an initial InfoSource binding). Redirects 303 to detail on success. Returns 422 with re-rendered form on validation error.

**GET `/dashboard/info-items/{id}`** — detail page. Header shows name, description, owner, rep_fields. Three Alpine.js tabs (client-side state):
- *Sources* — table of active `info_item_sources` bindings + bind-source form.
- *Replication Specs* — table of active `info_item_rep_specs` assignments + assign form.
- *Revision History* — last 50 `info_item_source_revisions` ordered by `bound_at desc`.

**POST `/dashboard/info-items/{id}/bind-source`** — binds an existing InfoSource (form fields: `info_source_id`, `role`). Redirects 303 to detail `?tab=sources`.

**DELETE `/dashboard/info-items/{id}/info-sources/{source_id}`** — HTMX delete; sets `deactivated_at = now()`. Response replaces `<tr id="source-row-{source_id}">` with empty (removes row).

**POST `/dashboard/info-items/{id}/assign-rep-spec`** — assigns a RepSpec (form field: `rep_spec_id`). Redirects 303 to detail `?tab=repspecs`.

**DELETE `/dashboard/info-items/{id}/rep-spec-assignments/{aid}`** — HTMX delete; sets `deactivated_at = now()`. Removes `<tr id="rs-row-{aid}">`.

**PATCH `/dashboard/info-items/{id}/rep-spec-assignments/{aid}/public-url`** — sets `public_url` on an assignment (form field: `public_url`). Returns `info_items/_rep_spec_row.html` fragment replacing the row.

**POST `/dashboard/info-items/{id}/bind-revision`** — binds a SourceRevision (form field: `source_revision_id`). Redirects 303 to detail `?tab=revisions`.

Partial template: `info_items/_rep_spec_row.html` — reusable `<tr>` fragment used in detail list and as PATCH public-url response.

### Information Sources (`/dashboard/info-sources/`)  *(Epic 4 — implemented)*

**GET `/dashboard/info-sources/`** — paginated list. Query params: `shape` (`root` / `fragment` / omit for all), `url_contains` (ilike filter on `url` column), `limit`, `offset`.

**GET `/dashboard/info-sources/new`** — create form. `sourceSpecEditor` Alpine component wraps the SourceSpec JSON textarea: validates JSON on blur, shows inline error. Also accepts optional `parent_info_source_id` field for fragments.

**POST `/dashboard/info-sources/new`** — form fields: `source_spec` (JSON string), `parent_info_source_id` (ULID, optional). Calls `create_info_source` tool. Redirects 303 to detail on success. Re-renders form with `errors` dict on `InvalidSourceSpecError`, `ParentNotFoundError`, `ParentMustBeRootError`. Shows conflict alert + link to existing source on `DuplicateUrlError`.

**GET `/dashboard/info-sources/{id}`** — detail page. Sections:
- Header: shape badge (`root` / `fragment`), `info_source_id`, created_at. Parent link if fragment (links to parent's detail).
- SourceSpec JSON — displayed in `<pre class="code-block">`.
- Bound Information Items — table of active `info_item_sources` bindings (item name link, role badge, bound date).
- Revision History — last 50 `source_revisions` ordered by `captured_at desc` (fingerprint truncated, captured date, cache status pill).

### Information Source Revisions (`/dashboard/source-revisions/`)  *(Epic 5)*
- **List:** filter by Information Source; columns: fingerprint (truncated), captured_at, cache status (`.status-pill--*`).
- **Detail:** full fingerprint, captured_at, `content_cache_uri` + expiry, bound Information Items. PATCH form for cache field clearing.

### Replication Specifications (`/dashboard/rep-specs/`)  *(Epic 6)*
- **List:** paginated; filter by provider.
- **Detail:** document JSON display; active assignments (with public_url writeback status).
- **Create:** provider selector + document editor + live validation.

### Settings — API Keys (`/dashboard/settings/api-keys`)  *(Epic 2 — implemented)*

**GET** — list current user's keys (prefix, label, last_used_at columns); create form.

**POST** — create new key (`label` form field required). Returns the full page with `new_raw_key` in template context so the `apiKeyReveal` component shows the raw key once. After navigation, the raw key is gone.

**DELETE `/dashboard/settings/api-keys/{id}`** — HTMX delete; response replaces the `<tr id="key-row-{id}">` with empty (removes row). Returns 404 if key belongs to a different user.

**PATCH `/dashboard/settings/api-keys/{id}`** — rename label (`label` form field). Returns `settings/_api_key_row.html` fragment replacing the existing row. Returns 404 if key belongs to a different user.

Partial template: `settings/_api_key_row.html` — reusable `<tr>` fragment used both in list and as PATCH response.
