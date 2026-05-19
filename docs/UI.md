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

*(Sections for infoItemWizard, jsonFieldEditor, sourceSpecEditor, repSpecEditor will be added in Epics 3–6.)*

---

## Page Inventory

### Home (`/dashboard/`)  *(Epic 7)*
Summary counts (InfoItems, InfoSources, RepSpecs, SourceRevisions). Recent SourceRevision captures (last 10). Service health indicator.

### Information Items (`/dashboard/info-items/`)  *(Epic 3)*
- **List:** paginated; `name_contains` search; columns: name, primary source URL, active rep spec count, created_at.
- **Detail:** header + three tabs — Sources (bind/deactivate), Replication Specs (assign/deactivate/set-public-url), Revision History.
- **Create:** multi-step form (name/description/owner/rep_fields → optional SourceSpec → optional RepSpec assignments).

### Information Sources (`/dashboard/info-sources/`)  *(Epic 4)*
- **List:** paginated; filter by shape (root/fragment); URL search.
- **Detail:** SourceSpec JSON display; parent link if fragment; bound Information Items; revision list.
- **Create:** SourceSpec editor with live validate-on-blur.

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
