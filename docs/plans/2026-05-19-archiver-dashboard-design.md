# Archiver Admin Dashboard — Design

**Date:** 2026-05-19
**Status:** Approved
**Companion issues:** #27 (tracking epic) and children #28–#34

---

## Goal

Deliver a server-rendered administrative dashboard for the Archiver service, enabling human operators to carry out the same registry and authoring tasks currently performed via the SDK/API. The dashboard is integrated into the existing FastAPI service (no separate process), follows the exe.xyz authentication pattern established by Power Map and Watcher, and establishes the UI/style foundation for future Archiver front-end work.

---

## Approved Approach

**FastAPI + Jinja2 + HTMX 2.0.8 + Alpine.js 3.x.** Server-rendered fragments for navigation and data mutations (HTMX); client-side reactive state for multi-step forms, JSON editors, and modals (Alpine.js). No build step. Bespoke CSS design token system ported from Power Map. Vitest + happy-dom for JS unit tests.

---

## Key Decisions

### Authentication

**Dashboard:** exe.dev proxy header trust. Every dashboard request passes through `get_dashboard_user`, which reads `X-ExeDev-UserID` and `X-ExeDev-Email` from the request headers. If either is absent, the user is redirected to `/__exe.dev/login?redirect=<original path>`. No session cookies, no JWT — stateless per-request, proxy owns the session.

**API keys:** `require_api_key` in `src/api/deps.py` migrates from `os.environ["ARCHIVER_API_KEY"]` to a SHA-256 hash lookup against the `api_keys` table. This is a **hard cut** — no env-var fallback. Existing Watcher integrations, SDK callers, and smoke scripts must issue new keys via the Settings page before the migration deploys.

**Logout:** `<form method="POST" action="/__exe.dev/logout">` button in the topbar.

### Data Model

Two new tables in the `information` schema:

**`information.app_users`**

| Column | Type | Notes |
|---|---|---|
| `id` | ULID PK | Internal identifier; FK target for `api_keys` |
| `external_id` | TEXT UNIQUE | Opaque auth-proxy user token (`X-ExeDev-UserID`); indexed for upsert lookup; provider-agnostic name |
| `email` | TEXT UNIQUE | `X-ExeDev-Email`; login identifier and public surface |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

`external_id` is the upsert key on login. `email` can change on the proxy side; `external_id` is stable. `id` (ULID) is the stable internal FK anchor — a deliberate divergence from the Watcher pattern (which uses the proxy string directly as PK).

**`information.api_keys`**

| Column | Type | Notes |
|---|---|---|
| `id` | ULID PK | |
| `user_id` | ULID → `app_users.id` | |
| `label` | TEXT NOT NULL | Operator-chosen display name |
| `key_prefix` | CHAR(8) | First 8 chars of raw key; shown in list view for identification |
| `key_hash` | TEXT NOT NULL | `SHA-256(raw_key)`; only hash stored, raw key never persisted |
| `created_at` | TIMESTAMPTZ | |
| `last_used_at` | TIMESTAMPTZ NULL | Updated on each successful API request |

Key format: `co_` + 32 lowercase hex chars (128-bit random). Raw key is displayed once in a modal on creation and never retrievable again.

### URL Structure

Dashboard at `/dashboard/*`. API stays at `/api/v1/*`. Health and OpenAPI endpoints unchanged. The explicit `/dashboard/` prefix avoids collision with future public-facing routes.

### Display Names (UI only)

Dashboard surfaces use fully qualified domain names. Code, API, and documentation continue to use the terse forms.

| Terse (internal) | Display (UI) |
|---|---|
| InfoItem | Information Item |
| InfoSource | Information Source |
| RepSpec | Replication Specification |
| SourceRevision | Information Source Revision |

### JS Patterns

- **HTMX** handles all server-fragment interactions: boosted navigation (`hx-boost` on `.admin-layout`), form submissions, list refreshes, inline partial re-renders.
- **Alpine.js** handles client-side state: multi-step InfoItem create wizard, SourceSpec/RepSpec JSON editors (format-on-blur, invalid-JSON guard), modal show/hide, tri-theme toggle, API key reveal modal.
- Alpine components are registered as `Alpine.data('componentName', () => ({ ... }))` in `main.js` before `Alpine.start()`. No inline `x-data="{...}"` blobs in templates.
- `dark-mode.js` and `flash.js` are IIFEs with document-level event delegation so they survive HTMX body swaps.
- All files carry `/*jslint browser, module */` headers and JSDoc on every exported function/component factory.
- JS tests use Vitest + happy-dom; test files in `tests/js/`.

### Theming

Three-layer system (identical to Power Map):
1. `:root { ... }` — light-mode defaults
2. `@media (prefers-color-scheme: dark) { :root { ... } }` — OS preference fallback (no JS required)
3. `html.dark { ... }` / `html.light { ... }` — explicit user choice (wins by specificity)

FOUC prevention: inline `<script>` in `<head>` **before** `<link rel="stylesheet">` reads `localStorage.getItem('co-color-scheme')` and sets `html.dark`/`html.light` before first paint.

Tri-toggle button cycles: `light → system → dark`. `localStorage` key: `co-color-scheme`. Brand color: `--color-brand: #6d4488` (light) / `#a78bc4` (dark).

### Archiver-Specific CSS Components

Ported from Power Map: `.btn`, `.badge--*`, `.alert--*`, `.flash--*`, `.data-table`, `.entity-card`, `.entity-section`, `.detail-grid`, `.filter-card`, `.pagination`, `.modal-*`, `.danger-zone`, `.typeahead-results`.

New components not in Power Map:
- `.code-block` — monospace card for SourceSpec/RepSpec JSON display; client-side syntax highlighting via a small inline JS function (no external library).
- `.status-pill--cached`, `.status-pill--expired`, `.status-pill--missing` — Information Source Revision cache state indicators.

### Accessibility Target

WCAG 2.1 AA. `aria-live="polite" aria-atomic="false"` on all HTMX swap targets. `aria-current="page"` on active sidebar link. `:focus-visible` rings. 44×44px minimum touch targets. Skip link. Modal focus trapping and restore. `@media (prefers-reduced-motion: reduce)` collapses all transitions.

### Tooling

| Tool | Version | Purpose |
|---|---|---|
| HTMX | 2.0.8 | Server-fragment swaps; vendored |
| Alpine.js | 3.x (latest) | Client-side reactive state; vendored |
| Vitest | latest | JS unit tests |
| happy-dom | latest | DOM environment for Vitest |
| ESLint | latest (`@eslint/js`) | JS lint |
| JSLint pragma | in-file header | Stricter JS style enforcement |

### Test / Prod DB Separation

Already established: `TEST_DATABASE_URL` is required at pytest import time (hard `RuntimeError` if unset); the session-scoped test engine creates and drops the `information` schema around the full test run; per-test SAVEPOINT isolation prevents cross-test bleed. New `app_users`/`api_keys` ORM models inherit this automatically by joining `Base.metadata`. Dashboard-specific tests override `get_dashboard_user` via `app.dependency_overrides` (same pattern as existing `get_db_session` override in the `client` fixture).

### Living Documentation

`docs/STYLE.md` — authoritative reference for all CSS design tokens, component classes, theming approach, naming conventions, and accessibility requirements.

`docs/UI.md` — page inventory, HTMX swap patterns, Alpine.js component catalogue, flash/modal usage guide.

**AGENTS.md enforcement:** both files must be updated in the same commit as any change to `dashboard.css`, a JS module, a Jinja2 template, or a new route. This requirement is added to the Conventions section of AGENTS.md.

### Out of Scope

- **Authoring tools UI** (`/tools/*` endpoints) — reserved for a future MCP server and agent plugin (GH #3). No tools page in this work.
- **Multi-user roles / permissions** — single-operator service; all authenticated dashboard users have full access.
- **Public-facing routes** — dashboard is admin-only behind exe.dev proxy auth.
- **Build step / bundling** — deferred; all JS served as plain modules or classic scripts.
- **Replicator / Watcher management** — Archiver dashboard covers only the Archiver registry.

---

## Page Inventory

### Home (`/dashboard/`)
Summary counts (Information Items, Information Sources, Replication Specifications, Information Source Revisions). Recent Information Source Revision captures (last 10). Service health indicator (calls `/health` inline).

### Registry — Information Items (`/dashboard/info-items/`)
- **List:** paginated table; `name_contains` search; columns: name, primary source URL, active rep spec count, created_at.
- **Detail:** header (name, description, owner, rep_fields); three tabs — Sources (active bindings + bind/deactivate), Replication Specs (assignments + assign/deactivate/set-public-url), Revision History.
- **Create:** multi-step form — (1) name/description/owner/rep_fields; (2) optional initial SourceSpec; (3) optional Replication Specification assignments.

### Registry — Information Sources (`/dashboard/info-sources/`)
- **List:** paginated; filter by shape (root / fragment); URL search.
- **Detail:** SourceSpec JSON display (`.code-block`); parent link if fragment; bound Information Items; revision list.
- **Create:** SourceSpec editor with live validate-on-type (HTMX posts to `/api/v1/tools/validate-source-spec` on blur).

### Registry — Information Source Revisions (`/dashboard/source-revisions/`)
- **List:** filter by Information Source; columns: fingerprint (truncated), captured_at, cache status (`.status-pill--*`).
- **Detail:** full fingerprint, captured_at, `content_cache_uri` + expiry, bound Information Items. PATCH form for cache field clearing.

### Registry — Replication Specifications (`/dashboard/rep-specs/`)
- **List:** paginated; filter by provider.
- **Detail:** document JSON display; active assignments (with public_url writeback status).
- **Create:** provider selector + document editor + live validation (HTMX posts to `/api/v1/tools/validate-rep-spec` on blur).

### Settings — API Keys (`/dashboard/settings/api-keys`)
List user's keys (prefix, label, last_used_at); create (raw key shown once in Alpine.js reveal modal); rename; delete.

---

## Phased Delivery

Epics 3–6 are independent of each other and can be executed in parallel by separate agents after Epic 2 ships.

### Epic 1 — Foundation
- `app_users` + `api_keys` ORM models + Alembic migration
- `get_dashboard_user` dep; `generate_api_key()` helper; `require_api_key` updated to DB hash lookup (env var retired)
- `register_dashboard(app)` scaffold — mounts static, includes routers, empty index route
- `dashboard.css` (full token system + all components)
- `dark-mode.js` (tri-toggle), `flash.js`, `main.js` (HTMX config + Alpine bootstrap)
- `base.html` (topbar, sidebar with nav stubs, flash region)
- `package.json`, `vitest.config.js`, `eslint.config.js`; CI lint job extended with `npm run lint && npm test`
- `docs/STYLE.md` + `docs/UI.md` stubs; AGENTS.md updated
- **CR checkpoint:** shell renders at `/dashboard/`, auth redirects unauthenticated users, CI green

### Epic 2 — Settings / API Key Management
- `GET/POST /dashboard/settings/api-keys` routes + templates
- Alpine.js `apiKeyReveal` component
- Tests: `tests/dashboard/test_auth.py`, `tests/dashboard/test_settings.py`
- **CR checkpoint:** operators can issue, rename, and delete keys; old env-var auth retired

### Epic 3 — Information Items
- List, detail (tabbed), create (multi-step wizard) routes + templates
- Sub-resource actions: bind InfoSource, assign/deactivate RepSpec, set public_url, bind SourceRevision
- Alpine.js: `infoItemWizard`, `jsonFieldEditor` components
- Tests: `tests/dashboard/test_info_items.py`
- **CR checkpoint:** full InfoItem lifecycle operable from the UI

### Epic 4 — Information Sources
- List, detail, create routes + templates
- Alpine.js: `sourceSpecEditor` component (live validation on blur)
- Tests: `tests/dashboard/test_info_sources.py`
- **CR checkpoint:** InfoSources browsable and creatable from the UI

### Epic 5 — Information Source Revisions
- List (with InfoSource filter), detail, cache PATCH routes + templates
- `.status-pill--*` component wired in templates
- Tests: `tests/dashboard/test_source_revisions.py`
- **CR checkpoint:** revision history browsable; cache fields patchable from the UI

### Epic 6 — Replication Specifications
- List, detail, create routes + templates
- Alpine.js: `repSpecEditor` component (provider selector + live validation on blur)
- Tests: `tests/dashboard/test_rep_specs.py`
- **CR checkpoint:** RepSpecs browsable and creatable from the UI

### Epic 7 — Home
- Summary count queries (COUNT per entity table)
- Recent revisions query (last 10 SourceRevisions across all sources)
- Health indicator (inline `/health` fetch on page load via HTMX)
- `docs/UI.md` fully populated
- **CR checkpoint:** dashboard home is informative; all docs current
