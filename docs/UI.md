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

**GET `/dashboard/domains/{name}`** — detail. `.entity-card` header (converged on the canonical detail-screen pattern, #82): `.eyebrow` "Domain" kicker → `<h1 class="entity-card__title" id="domain-heading" tabindex="-1">` with the copyable domain name → `.detail-grid` (Status badge, created_at UTC). Operator notes (HTMX inline edit); linked Information Sources table (count in heading from a route `COUNT`, so it stays accurate across pagination — #82; source URLs carry the `open_button` affordance). `has_more` stays on its own `limit+1` probe (see **Related-collection tables**). Two distinct empty states: an overshot `offset` (stale bookmark, or rows removed mid-session) renders "No sources on this page" with a link back to `?offset=0`, while a genuinely empty collection keeps "No Information Sources registered for this domain yet" — the count in the heading would otherwise contradict the "none registered" copy. **Archive** lives in a `.danger-zone` block at the bottom, shown only while the domain is active (`.btn--danger` + static confirm). **Restore** is recovery, not destructive, so it's hoisted into the header Status field inline next to the "archived" badge (`.btn--secondary`); once archived the danger zone is hidden entirely. Archive and Restore both stay full-page POST→303 by design — see the *allowed variant* note under **HTMX mutations**.

**POST `/dashboard/domains/{name}/notes`** — HTMX partial; replaces `#notes-section` with `domains/_notes_partial.html`. Saves notes inline.

**POST `/dashboard/domains/{name}/archive`** — sets `archived_at`, redirects to detail (303). Triggered from the danger-zone Archive button.

**POST `/dashboard/domains/{name}/restore`** — clears `archived_at`, redirects to detail (303). Triggered from the danger-zone Restore button.

Templates: `domains/list.html`, `domains/detail.html`, `domains/_notes_partial.html`.

### Registration flow (`/dashboard/register`)  *(#49 — implemented)*

4-step flow: URL → Selector → Metadata → Review & Submit. Replaces `/dashboard/info-items/new`.
See design doc `docs/plans/2026-06-04-dashboard-ux-redesign-design.md` for full spec.

**Rolling step-summary bar** *(#53)*: `#wizard-summary` (`role="group"`,
`aria-label="Completed steps"`), rendered between the step-indicator badges and
the form, visible from step 2 on (`x-show="step>=2"`).
Shows the values of completed steps as clickable chips (`.btn.btn--secondary.btn--sm`)
that jump back to their step — same semantics as the step-4 Edit buttons:

- **URL chip** (step ≥ 2) — the entered URL (CSS-truncated at 20rem, full value
  in `title`) plus a parenthesised domain note: `(known domain: <host>)` /
  `(new domain: <host>)` when a url-check result has landed for the current
  hostname (`domainSummary` getter), else just `(<host>)` (`urlHostname` getter).
- **Selector chip** (step ≥ 3) — `selectorSummary` getter: compact form of the
  source_specs JSON (`css: .rule-title`, `full_page`, `2 specs (css + regex)`).
  Also reused for the step-4 review Selector row.
- **Name chip** (step ≥ 4) — `itemName`.

Domain data reaches the wizard via the `urlCheckDispatch` data island inside the
`_url_check.html` fragment (see component docs below); the root element listens
with `@url-check.window="onUrlCheck($event.detail)"`.

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

Server returns `HX-Trigger: {"showFlash": {"level": "success", "body": "Saved."}}` alongside any mutating response. `flash.js` (loaded in `base.html`) injects `.flash--*` divs into `#flash-region` — a `position: fixed` viewport overlay (a direct `<body>` child, outside `<main>`, so HTMX content swaps can't wipe live toasts) anchored top-right on desktop and full-width top on narrow viewports, so toasts stay visible at any scroll position (archiver#65). **Note:** `flash.js` must be in the `base.html` script list — if it is dropped, every `showFlash` is silently ignored site-wide (CannObserv/archiver#62).

Dismissal is severity-based: `success`/`info` auto-dismiss after 6 s; `error`/`warning` persist until the operator clicks `.flash__close` (failures must not vanish unseen). The visible overlay caps at 4 slots, with two overflow affordances (archiver#73):

- **Transient overflow.** A `success`/`info` that arrives while 4 persistent toasts fill the cap is *not* dropped — it shows as a single overflow lane below them (momentarily 5 visible) for the full 6 s, then auto-dismisses. Only the newest transient occupies the lane (last-write-wins); older surplus transients are evicted oldest-first.
- **Persistent overflow.** A 5th `error`/`warning` no longer evicts the oldest (which silently lost failures before #73). Instead the 4th slot becomes a `+N more` counter button: the newest 3 stay visible and older ones collapse behind it. Activating the counter (click/Enter) expands the overlay to show all and removes the counter — there is no re-collapse affordance; once engaged the operator dismisses each. The counter counts hidden *persistent* toasts only, and because it occupies a slot the smallest N is 2 (first seen at the 5th persistent toast). A fresh pile (after all toasts clear) starts collapsed again.

Accessibility: announcement is decoupled from the visible overlay (archiver#73). Two visually-hidden live regions declared in `base.html` — `#flash-announcer-assertive` (`aria-live="assertive"`, errors) and `#flash-announcer-polite` (`aria-live="polite"`, all other levels) — receive *every* message, so assistive tech hears it even when the visible cap suppresses or collapses the toast. Visible toasts therefore carry no live role. The `+N more` counter is a real `<button>` (`aria-expanded`, `aria-controls="flash-region"`, `aria-label="Show N more notifications"`); expanding moves focus to the first revealed toast's dismiss button. The `flash-in` animation is suppressed under `prefers-reduced-motion` via the global reduced-motion block in `dashboard.css`.

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

## Detail Screen Conventions

Canonical patterns for entity **detail** pages. The Source Revision detail
(`source_revisions/detail.html` + `_detail_card.html`) is the reference
implementation (archiver#78); other detail screens should converge on these.

**Header.** An `.entity-card` whose `.entity-card__header` contains, in order:
1. An `.eyebrow` kicker naming the entity kind, singular (e.g. "Information
   Source Revision"). Non-interactive — replaces the older breadcrumb `<nav>`.
2. An `<h1 class="entity-card__title" id="…-heading" tabindex="-1">` whose
   content is the entity's identity — for ULID-keyed entities, the copyable
   ULID (see `copyable`). The `id`+`tabindex="-1"` make it a focus target for
   post-swap focus moves (see HTMX mutations).

**Detail grid.** `.detail-grid` with `.detail-grid__item` → `.detail-grid__label`
+ `.detail-grid__value` children (never bare `<dl><dt><dd>` — those misalign
against the CSS grid). Long single-line values (fingerprints, URLs) go on a
full-width row via `.detail-grid__item--full` so they extend horizontally
instead of cramping into one ~200px track. Timestamps are UTC-suffixed
(`%Y-%m-%d %H:%M UTC`) everywhere, including table cells.

**Copy affordance.** `copyable(value)` from `_macros.html` — a monospace value
plus a `.btn--secondary
.btn--sm` "Copy" button ("Copy"→"Copied ✓" for 1.5 s). The value is bound via
`|tojson` to an Alpine data prop and copied through it — never spliced into the
handler's JS source — so arbitrary DB strings cannot break out of the JS
context.

**External-open affordance.** `open_button(url, label="Open")` from
`_macros.html` — a link styled as a `.btn--secondary .btn--sm` button ("Open
↗"), `target=_blank rel=noopener noreferrer`, modeled on the Copy button so
opening a URL reads as a distinct action separated from the displayed value.
Used for every external URL (source URLs, RepSpec `public_url`, http(s)
`content_cache_uri`). Section-header deeplinks styled as headings (e.g. the
InfoItem "Watcher ↗" `<h2>`) are intentionally exempt.

**HTMX mutations.** A mutating action on a detail page re-renders the affected
region in place rather than full-page reloading: extract the region to a
partial with a stable `id`, post via `hx-post`/`hx-patch` with
`hx-target="#…" hx-swap="outerHTML"` (+ `hx-confirm` for destructive ones), and
return the re-rendered partial with `HX-Trigger: {"showFlash": {...}}` for a
success toast (see **Flash messages**). Keep a `method`/`action` fallback on the
form so it still works as a plain POST→303 without JS (progressive
enhancement). Emit a focus-move `<script>` in the swap response only (gated on a
`swapped` flag) so keyboard focus lands on the region heading rather than
`<body>`.

*Allowed variant — full-page POST→303.* HTMX partial-swap applies to mutations
whose visible effect is **contained within a single card or section**. When a
mutation changes page-level state across **disjoint regions**, a plain
POST→303 is the correct implementation, not a shortfall to be migrated later.
Domain archive/restore is the reference case (#82): it moves the header Status
badge, the inline Restore button beside it, *and* the presence of the
`.danger-zone` block — three separate DOM regions, which HTMX would need
`hx-swap-oob` or a body-spanning partial to cover. Contrast SourceRevision
clear-cache, which swaps the one contiguous `#revision-card` partial. The 303
also preserves correct back-button semantics for a state transition.

**Related-collection tables.** `.data-table` under an `<h2 class="section-heading">`
carrying the row count (e.g. "Bound Information Items (3)"). When the table is **paginated**,
the count must come from a route-level `COUNT` over the full result set, never
a template `|length` — that would report only the current page. Domain detail
(`source_total`) is the reference; InfoSource detail's "Other Sources at This
URL" uses the capped `limit+1` "50+" probe instead, appropriate where the
section is truncated rather than paged. Keep `has_more` on its own `limit+1`
probe even when a `COUNT` is already being run — the probe is self-consistent
by construction (one statement, one snapshot), whereas deriving `has_more` from
the `COUNT` compares two statements under READ COMMITTED and lets a concurrent
delete render a Next link into an empty page. The apparent redundancy is
deliberate: the two values answer different questions. A section heading with a
count needs **two** empty
states: "nothing here at all" and "nothing on *this page*" (overshot offset);
collapsing them makes the heading contradict the body. Cache state uses the
`.status-pill--cached/expired/missing` pills, not `.badge` variants. A
succession/currency status (e.g. a revision being an item's "current pin" vs
"superseded") is a `.badge--primary`/`.badge--muted` column.

**Pagination params are clamped, not validated.** Every paginated dashboard
route takes `page: Pagination = Depends(pagination)`
(`src/dashboard/pagination.py`) rather than declaring bare `limit`/`offset`
ints. `limit` is clamped to `[1, 200]`, `offset` to `[0, 2**63 - 1]` —
out-of-range values render a sensible page instead of erroring (#84). That
upper offset bound is a storage limit rather than a product judgement: the query
binds offset to `OFFSET $2::BIGINT`, and asyncpg rejects anything wider with
`DataError: value out of int64 range`, which surfaced as a 500 until it was
capped. Capping changes nothing else, since any offset that large already yields
an empty page. This is a **deliberate
divergence from the API layer**, which uses `Query(ge=…, le=…)` and returns 422:
the API is a contract surface where a bad `limit` is a client bug worth
surfacing loudly, while the dashboard is a human surface reached by hand-edited
URLs and stale bookmarks. The dashboard also has no HTML rendering path for
validation errors — `RequestValidationError` falls through to the app-wide
handler in `src/api/errors.py`, which always returns JSON, and HTMX does not
swap non-2xx responses, so a 422 on a partial silently does nothing. Clamping
removes the error path rather than styling it.

**The params are declared `str`, not `int`, and parsed in the dependency**
(#86). Under `int` annotations FastAPI coerced *before* the dependency ran, so
`?limit=abc` still raised `RequestValidationError` and answered a browser with
a raw JSON envelope — clamping had removed the out-of-range triggers but not
the type-coercion one. Parsing inside `clamp_pagination` closes it: unparseable
input falls back to the default (`int()`'s tolerance of surrounding whitespace
is kept, so `?limit=%2025%20` still means 25), and each param is handled
independently so one bad value doesn't discard the other. Since `limit` and
`offset` are the only non-`str` request params on any dashboard route — every
form field is `str`, path params are `str` ULIDs — this leaves no
`RequestValidationError` reachable from a dashboard URL. Form-level validation
errors are a separate mechanism and keep using `hx-target-422` (see the
InfoSource specs route below).

That completeness claim is enforced, not just asserted:
`test_pagination.py::test_no_dashboard_route_declares_a_coercible_param` walks
every `/dashboard` route's flattened dependant and fails if any query, path, or
body param is annotated as anything but `str` (`str | None` is fine —
optionality is absence, not coercion). **A new dashboard route must take its
params as `str`**; declaring `page: int` or `after: date` reopens the raw-JSON
422 that #86 closed, because coercion happens during dependency solving before
any dashboard code runs.

None of this reaches OpenAPI. Dashboard routers are included with
`include_in_schema=False` (#87): `clients/python/scripts/regen.sh` generates
the public SDK from `app.openapi()`, so any dashboard path in the schema is one
routine regen away from shipping as `archiver_client` API surface — HTML
responses under proxy-header auth, useless as client methods.
`test_openapi_exclusion.py` pins the exclusion, and **a ninth dashboard router
must be added to the loop in `register_dashboard`** rather than via its own
`app.include_router(...)` call, so it cannot forget the flag. (Before #87 the
clamp bounds were published via `json_schema_extra`; that machinery is gone —
each param's `description` still documents the clamp-don't-reject behaviour
for readers of the code.)

The dependency is `async` so FastAPI resolves it inline rather than paying a
`run_in_threadpool` hop for two comparisons; the parse and arithmetic live in a
sync `clamp_pagination()` helper so they stay unit-testable without reaching
through `Query` defaults. New paginated routes must use the dependency; do not
reintroduce bare `limit: int = 50`.

If a dashboard route ever needs a typed param that *cannot* be clamped into
something sensible — a date filter, say — this approach runs out, and the HTML
error-page work sketched in #86 (a `_422.html` plus a dashboard-owned
`RequestValidationError` handler registered from `register_dashboard`) becomes
the answer.

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

1. **Overview** — `.entity-card` header (converged on the canonical detail-screen pattern, #81): `.eyebrow` "Information Item" kicker → `<h1 class="entity-card__title" id="info-item-heading" tabindex="-1">` name → copyable ULID (shared `copyable` macro) → domain badge linking to `/dashboard/domains/{name}` (or muted "No primary source" if unbound); `.detail-grid` with description, owner (if set), created_at. (The former Watcher health strip here was removed in #62 — the same status/controls live in the Watcher section below. The `GET …/watcher-status` route + `_watcher_status.html` partial still exist but are no longer rendered on the page.)
2. **Information Sources** — `x-data="{swapOpen:false}"` Alpine wrapper. `data-table` of active `info_item_sources` bindings (columns: URL, Domain, Spec, Bound, Actions); first row gets a brand left-border to mark it as the primary. The **Spec** column shows a brief summary of the InfoSource's primary `source_specs` entry (`_format_spec_summary`, e.g. `css · 2 specs`), computed by the detail route into `spec_summary_by_source_id` — this is where the spec lives, not the Watcher section (#62). The Actions cell on the primary row contains a "Swap primary" / "Cancel" toggle button (`@click="swapOpen=!swapOpen"`). When `swapOpen` is true, `<div x-show="swapOpen" x-cloak>` reveals `info_items/_swap_primary.html`. When there are no active bindings, the swap panel renders unconditionally with an "Add primary source" title. The panel has `id="swap-panel"`. The "author new source" form uses `hx-post` + `hx-target-422="#swap-error"` for inline error display; on success it receives 204 + `HX-Redirect`. The "bind by ID" `<details>` sub-form uses the same pattern with `hx-target-422="#swap-by-id-error"`.
3. **Watcher** — the `<h2>` section header is itself the Watcher deeplink ("Watcher ↗", `target=_blank`) when the item is watched; the detail route computes `watcher_deeplink` from `WATCHER_PUBLIC_BASE_URL` (falling back to `WATCHER_BASE_URL`) + `item.watcher_item_id`, and renders a plain "Watcher" header when unwatched (#62). Body: `<div id="watcher-section">` loaded async via `hx-trigger="load"` + `hx-get="…/watcher-section"` + `hx-swap="outerHTML"`. Root element also carries `hx-trigger="watcherUpdated from:body"` so the panel self-refreshes whenever an action sends `HX-Trigger: {"watcherUpdated":{}}`. The action forms (begin-watching / check-now / toggle / resync) use `hx-swap="none"` — they don't swap anything directly; they rely on the `watcherUpdated` trigger to re-fetch this section. Template: `info_items/_watcher_section.html`. Four states: `not_configured`, `not_watching` (shows "Begin Watching" button), `degraded`, `watching` (shows health badge, timestamps, cadence, "Check now", "Re-sync"). The URL, spec summary, and "View in Watcher" link were removed in #62 — the URL and spec are reachable from the Information Sources section, and the deeplink is now the section header. Action buttons are `.btn--secondary .btn--sm`. **Begin Watching** provisions a WatchedItem on demand; if Watcher already has one for this InfoItem (Archiver's `watcher_item_id` is NULL — e.g. a pre-#55 item), provisioning 409s and `provision_on_create` adopts the existing WatchedItem's ID rather than failing (CannObserv/archiver#62). When the WatchedItem is paused (`is_active=False`, not archived) a **Paused** `badge--muted` shows next to the health badge, "Check now" is hidden (Watcher 409s on check-now of a paused item), and the toggle reads "Resume"; otherwise it reads "Pause" *(#60)*. Archived WatchedItems (`archived_at` set) show an **Archived** badge instead of "Paused" and hide the pause/resume toggle entirely (Watcher 409s; archive/restore owns activation there).
4. **Revision History** — `data-table` of `info_item_source_revisions` ordered by `bound_at desc`; columns: Revision (linked to revision detail), Captured (UTC), Cache (`.status-pill--cached/expired/missing`, matching the rest of the app — was a `.badge--success`/`—`). Replicator assignment rows (`_rep_spec_row.html`) show `activated_at` UTC and an `open_button` next to the `public_url` input when a value is set.
5. **Replicator** — two sub-sections:
   - *Rep Fields* — `x-data="repFieldsEditor()"` wrapper; HTMX-loaded `sortableChips` suggestions (`hx-trigger="load"`); `<textarea name="rep_fields">` with `PATCH /dashboard/info-items/{id}/rep-fields` inline save; flash target `#rep-fields-flash`.
   - *Replication Specs* — `info_items/_rep_spec_assignments.html` section (wrapper `#ii-rep-spec-assignments`, heading `#ii-rep-spec-heading`): `data-table` of active `info_item_rep_specs` assignments; assign form (`filter-card`, `rep_spec_id` field). HTMX deactivate re-renders the whole section (table + empty-state) and focuses the heading; per-row public-url edits still swap the individual row.

**GET `/dashboard/info-items/{id}/watcher-status`** — HTMX partial (`info_items/_watcher_status.html`). Calls Watcher `get_watched_item`; renders ok/error/unknown/not_watching/not_configured/degraded. Used by `hx-trigger="load"` on the health strip and re-renders after check-now, begin-watching, resync-watcher. **Self-heal on 404:** a `WatcherNotFound` (the WatchedItem was permanently deleted in Watcher) NULLs the stale `watcher_item_id` (commits) and renders `not_watching` so "Begin Watching" reappears — only a confirmed 404 clears the link; transient failures (network/5xx) still render `degraded` and retain it (CannObserv/archiver#63).

**GET `/dashboard/info-items/{id}/watcher-section`** — HTMX partial (`info_items/_watcher_section.html`). Calls Watcher `get_watched_item`; renders not_configured/not_watching/degraded/watching. The watching state shows health badge, timestamps, cadence, and action buttons (no URL or spec — those live in the Information Sources section). Loaded on page init via `hx-trigger="load"` and re-fetched on the `watcherUpdated` body event. The Watcher deeplink lives on the section's `<h2>` header (rendered by the detail page, not this partial). Same 404 self-heal as `/watcher-status` (CannObserv/archiver#63).

**POST `/dashboard/info-items/{id}/check-now`** — proxies to Watcher `check-now`; re-renders `_watcher_status.html`; also sets `HX-Trigger: {"watcherUpdated":{}}` so Section 3 (`#watcher-section`) auto-refreshes. If `check_now` fails, re-fetches via `get_watched_item` (shows degraded only if that also fails) **and** adds a `showFlash` error to the `HX-Trigger` so the failure is surfaced rather than swallowed *(#60)*. A `WatcherConflict` (409 — check-now on a paused item) flashes "resume it first"; a `WatcherNotFound` (404 — the WatchedItem was deleted in Watcher) clears the stale `watcher_item_id` and flashes "no longer watched — it was removed in Watcher" so the re-render falls back to `not_watching` (CannObserv/archiver#63); any other failure flashes "Watcher is unavailable".

**POST `/dashboard/info-items/{id}/begin-watching`** — provisions a WatchedItem on demand (for InfoItems without `watcher_item_id`); calls `provision_on_create`; re-renders `_watcher_status.html`; sets `HX-Trigger: {"watcherUpdated":{}}` so Section 3 auto-refreshes. `provision_on_create` returns a `WatcherSyncOutcome`; on `FAILED` (provisioning attempted but Watcher unavailable) the response adds a `showFlash` error so the failure is surfaced rather than swallowed. When the item has no active primary source to watch, flashes "No primary source to watch — bind one first." A `SKIPPED` outcome (no Watcher configured) flashes nothing *(#61)*.

**POST `/dashboard/info-items/{id}/resync-watcher`** — PATCHes the WatchedItem with the current primary URL and specs via `sync_on_source_swap`; re-renders `_watcher_status.html`; also sets `HX-Trigger: {"watcherUpdated":{}}` so Section 3 auto-refreshes. `sync_on_source_swap` returns a `WatcherSyncOutcome`; on `FAILED` the response adds a `showFlash` error ("Couldn't re-sync with Watcher — it's unavailable"). When the watched item has no active primary source, flashes "No primary source to re-sync — bind one first." *(#61)* **404 self-heal:** a deleted WatchedItem 404s inside `sync_on_source_swap` (swallowed to `FAILED`), but the trailing `_watcher_status.html` re-render re-fetches via `get_watched_item`, 404s, clears the stale `watcher_item_id`, and reconciles to `not_watching` — so a deleted item recovers even though the flash stays the generic "unavailable" (the 404 is opaque to the shared core helper; CannObserv/archiver#63).

**POST `/dashboard/info-items/{id}/toggle-watch-active`** *(#60)* — pauses or resumes the WatchedItem via `patch_watched_item(is_active=…)`. Form field `active` is the desired target state ("true" → resume, anything else → pause); the button submits the opposite of the current state. Re-renders `_watcher_status.html` and sets `HX-Trigger: {"watcherUpdated":{}}` so Section 3 auto-refreshes. On failure the response adds a `showFlash` error to the `HX-Trigger`: a Watcher 409 (`WatcherConflict`, e.g. pause/resume on an archived item) flashes "the item may be archived"; a `WatcherNotFound` (404 — the WatchedItem was deleted in Watcher) clears the stale `watcher_item_id` and flashes "no longer watched — it was removed in Watcher" so the re-render falls back to `not_watching` (CannObserv/archiver#63); any other failure flashes "Watcher is unavailable". The partial still re-renders rather than 500ing. No-op (no patch) when the InfoItem has no `watcher_item_id`.

**POST `/dashboard/info-items/{id}/swap-primary-source`** — inline primary-source swap: creates a new InfoSource (form fields: `url`, `source_specs` JSON array), deactivates the old active binding, binds the new source, best-effort `patch_watched_item` post-commit. Returns 204 + `HX-Redirect` to detail on success; returns 422 with an `<div id="swap-error">` fragment on validation error (targeted by `hx-target-422="#swap-error"` on the form). Template: `info_items/_swap_primary.html`.

**POST `/dashboard/info-items/{id}/swap-primary-by-id`** — same swap flow for an existing InfoSource (form field: `info_source_id` ULID). Deactivates old binding, binds new source, best-effort Watcher patch. Returns 204 + `HX-Redirect`; ULID validation error returns 422 with `<div id="swap-by-id-error">` fragment.

**POST `/dashboard/info-items/{id}/bind-source`** — binds an existing InfoSource (form field: `info_source_id`). Redirects 303 to detail. Returns 409 if an active binding already exists. *(No longer linked from the dashboard UI; use swap-primary-by-id for interactive use.)*

**DELETE `/dashboard/info-items/{id}/info-sources/{source_id}`** — HTMX delete (form POST + route handler); sets `deactivated_at = now()`. Response triggers HTMX redirect to detail.

**POST `/dashboard/info-items/{id}/assign-rep-spec`** — assigns a RepSpec (form field: `rep_spec_id`). Redirects 303 to detail.

**DELETE `/dashboard/info-items/{id}/rep-spec-assignments/{aid}`** — HTMX delete; sets `deactivated_at = now()` (idempotent — skipped if already deactivated). Returns the re-rendered `info_items/_rep_spec_assignments.html` section fragment (targets `#ii-rep-spec-assignments`), which updates the table/empty-state and moves focus to the section heading.

**PATCH `/dashboard/info-items/{id}/rep-spec-assignments/{aid}/public-url`** — sets `public_url` on an assignment (form field: `public_url`). Returns `info_items/_rep_spec_row.html` fragment replacing the row.

**PATCH `/dashboard/info-items/{id}/rep-fields`** — inline save for rep_fields JSONB (form field: `rep_fields` JSON string). Returns flash fragment into `#rep-fields-flash`.

**POST `/dashboard/info-items/{id}/bind-revision`** — binds a SourceRevision (form field: `source_revision_id`). Redirects 303 to detail.

Partial templates:
- `info_items/_rep_spec_row.html` — reusable `<tr>` fragment for rep-spec assignment rows.
- `info_items/_watcher_status.html` — Watcher health strip; replaces `#watcher-status-strip` via `hx-swap="outerHTML"`. Root element carries the `id` so it survives each swap. Five states: `not_configured`, `not_watching`, `degraded`, `watching` (ok/error/unknown). In the watching state it shows a **Paused** `badge--muted` and hides "Check now" when `watched_item.is_active` is false (an **Archived** badge replaces "Paused" when `watched_item.archived_at` is set), and offers a Pause/Resume toggle (hidden when archived) *(#60)*. Context keys: `state`, `item_id`, `watched_item`, `last_checked_ago`, `last_changed_ago`, `cadence`, `error_message`.
- `info_items/_swap_primary.html` — inline swap-primary panel included inside the `x-data="{swapOpen:false}"` wrapper in Section 2. Full-width card (`#swap-panel`, no max-width — spans the bindings table). Renders either "Swap primary source" or "Add primary source" depending on whether `iis_rows` is non-empty. Contains: URL input (`id="swap-url"`, `.form-input`), source_specs textarea (`id="swap-specs"`, `.form-textarea`), Preview HTMX button (`.btn--secondary`, `hx-include="#swap-url,#swap-specs"`), preview target `#swap-preview`, submit to `swap-primary-source` (`.btn--primary`), and an advanced `<details>` for `swap-primary-by-id` (`.form-input` field + `.btn--secondary` Bind button).
- `info_items/_watcher_section.html` — Section 3 Watcher panel; replaces `#watcher-section` via `hx-swap="outerHTML"`. Root element carries both the `id` and `hx-trigger="watcherUpdated from:body"` for event-driven auto-refresh. Four states: `not_configured`, `not_watching`, `degraded`, `watching`. Action forms use `hx-swap="none"` and self-refresh the panel via the `watcherUpdated` trigger. Context keys (watching): `state`, `item_id`, `watched_item`, `last_checked_ago`, `last_changed_ago`, `cadence`, `error_message`.

### Information Sources (`/dashboard/info-sources/`)  *(Epic 4 — implemented)*

**GET `/dashboard/info-sources/`** — paginated list. Query params: `url_contains` (ilike filter on `url` column), `limit`, `offset`. Shape/fragment filters removed.

**GET `/dashboard/info-sources/new`** — create form. Fields: `url` (text input) + `source_specs` (JSON array textarea, validates JSON on blur).

**POST `/dashboard/info-sources/new`** — form fields: `url` (string), `source_specs` (JSON array string). Calls `create_info_source` tool. Redirects 303 to detail on success. Re-renders form with `errors` dict on `InvalidUrlError`, `InvalidSourceSpecError`, `MixedAlgorithmFamilyError`.

**GET `/dashboard/info-sources/{id}`** — detail page. Sections:
- Header: `.entity-card` (canonical pattern, #79) — `.eyebrow` "Information Source" → `<h1 class="entity-card__title" id="info-source-heading" tabindex="-1">` with the `url` in `<code>` → an `open_button` to the URL → copyable `info_source_id` → `.detail-grid` (created_at UTC). Grid uses `.detail-grid__item` (was bare `<dl><dt><dd>`, which misaligned).
- Source Specification editor — the `info_sources/_source_specs_card.html` partial (extracted so the update-specs action can swap it in place — root `#source-specs-card`, heading `#source-specs-heading`; titled "Source Specification"). An Alpine `x-data="{ editing }"` toggle gates the editor (issue #100): **view mode** (`x-show="!editing"`) shows the current `source_specs` JSON array in `<pre class="code-block">` with an **Edit** button; clicking Edit reveals the textarea form (`x-show="editing"`) with **Cancel** (resets the textarea to the stored specs via `$refs.specsBox` and returns to view mode, no server call) and **Save** (submits the `POST .../source-specs` replace). Opens in edit mode when `specs_error` is set so the error and the operator's submitted text stay visible (mirrors `settings/_api_key_row.html`). No `x-cloak` — without JS both view and editor render and Save posts normally (progressive enhancement). URL is immutable.
- Other Sources at This URL — shown only when other InfoSources share this `url` (the model allows multiple sources per URL, #79 #8); count in heading (capped at 50 via a limit+1 probe, rendered "50+" when more exist), each linked by `info_source_id` with created date UTC.
- Bound Information Items — table of active `info_item_sources` bindings (count in heading; item name link, bound date UTC). Role column removed.
- Revision History — last 50 `source_revisions` ordered by `captured_at desc` (count in heading; fingerprint truncated, captured date UTC, cache status pill).

**POST `/dashboard/info-sources/{id}/source-specs`** — replaces `source_specs` list on an existing InfoSource (form field: `source_specs` JSON array). HTMX requests (`hx-post`, `hx-target="#source-specs-card"`, `hx-swap="outerHTML"`) get the re-rendered `_source_specs_card.html` partial swapped in place: success carries an `HX-Trigger: showFlash` toast and moves focus to the section heading (#79 #7); a validation error swaps the card back with the inline `specs_error` (`role="alert"`) visible, moves focus to the heading, and echoes the submitted text back into the textarea so the edit isn't discarded (status 200 so htmx performs the swap). Non-HTMX requests fall back to a 303 redirect on success / full-page 422 re-render (also preserving submitted text) on JSON parse, schema validation, or mixed-family failure (progressive enhancement).

### Information Source Revisions (`/dashboard/source-revisions/`)  *(Epic 5 — implemented)*

**GET `/dashboard/source-revisions/`** — paginated list ordered by `captured_at desc`. Optional `info_source_id` filter (ULID). Columns: truncated fingerprint (link to detail), source URL (link to InfoSource detail), captured date, cache status pill (`.status-pill--cached` / `.status-pill--expired` / `.status-pill--missing`).

**GET `/dashboard/source-revisions/{id}`** — detail page. The header lives in the `source_revisions/_detail_card.html` partial (extracted so clear-cache can swap it in place — root `#revision-card`): an `.eyebrow` kicker ("Information Source Revision") above the `<h1>`, whose title is the copyable `source_revision_id` (shared Alpine copy idiom — `.btn--secondary .btn--sm`, "Copy"→"Copied ✓" for 1.5 s; value bound via `|tojson`, never spliced into the handler's JS). `.detail-grid` (normalized to the InfoItem convention — `.detail-grid__item/__label/__value`, not bare `<dl><dt><dd>`) with copyable full fingerprint and Information Source both on full-width rows (`.detail-grid__item--full`) so long values extend horizontally; the Information Source value carries the internal source-detail link plus an **"Open ↗" button** (shared `open_button` macro from `_macros.html`) to the target URL. Then captured_at (UTC-suffixed), size (if set), media type (if set), and cache status. Cache value shows a status pill plus the `content_cache_uri` — displayed text with an **"Open ↗" button** when `http(s)`, otherwise copyable — and an expiry line. "View all revisions for this source →" deeplinks the list `?info_source_id=`. Danger-zone clear-cache form (shown only when `content_cache_uri` is set). Bound Information Items table (count in heading; `bound_at` UTC-suffixed) has a **Status** column: `.badge--primary` "current pin" when this revision is the item's most-recent `info_item_source_revisions` binding, else `.badge--muted` "superseded".

**POST `/dashboard/source-revisions/{id}/clear-cache`** — sets `content_cache_uri = NULL` and `content_cache_expires_at = NULL`. HTMX requests (`hx-post`, `hx-target="#revision-card"`, `hx-confirm`) get the re-rendered `_detail_card.html` partial swapped in place plus an `HX-Trigger: showFlash` success toast; non-HTMX requests fall back to a 303 redirect to detail (progressive enhancement). No request body required.

### Replication Specifications (`/dashboard/rep-specs/`)  *(Epic 6 — implemented)*

**GET `/dashboard/rep-specs/`** — paginated list. Optional `provider` filter (enum: `gcs` / `gdrive` / `ia`). Columns: name (link to detail), provider badge, created_at.

**GET `/dashboard/rep-specs/new`** — create form. Provider `<select>`, name text input, document JSON textarea (`repSpecEditor` Alpine component with validate-on-blur). Returns 200 with errors dict on validation failure.

**POST `/dashboard/rep-specs/new`** — form fields: `provider`, `name`, `document` (JSON string). Calls `create_rep_spec` tool. Redirects 303 to detail on success. Re-renders form with errors on missing provider, missing name, invalid JSON, or `InvalidRepSpecError`.

**GET `/dashboard/rep-specs/{id}`** — detail page. Header: `.entity-card` (canonical pattern, #80) — `.eyebrow` "Replication Specification" → `<h1 class="entity-card__title" id="rep-spec-heading" tabindex="-1">` name → copyable `rep_spec_id` → `.detail-grid` (provider badge, created_at UTC, plus **Updated** UTC *only when* `updated_at` is non-null — a null means "never edited" and rendering `created_at` there would blur that distinction, #83). Grid uses `.detail-grid__item` (was bare `<dl><dt><dd>`). Document card — the `rep_specs/_document_card.html` partial (extracted so the update-document action can swap it in place — root `#rep-spec-document-card`, heading `#rep-spec-document-heading`). Shows the stored document JSON in `<pre class="code-block">`, then **conditionally** an edit form: the textarea renders only when the RepSpec is a *draft* (zero `info_item_rep_specs` rows, active **or** deactivated — the count comes from `assignment_count()`, deliberately not `_load_active_assignments`, since a deactivated assignment still means a replication run happened under that document). A non-draft renders a `.alert--info` "frozen" notice with the assignment count instead of the form (#83; clone + migrate is #95). Active assignments section (`rep_specs/_assignments.html`, wrapper `#rep-spec-assignments`): count in heading; item name link, activated_at UTC, `public_url` shown with an `open_button`, and a **Deactivate** action. Deactivate is `hx-delete` to the RepSpec-scoped route below, targeting `#rep-spec-assignments` (`outerHTML`) so the row set, count, and empty-state re-render together; assignments are manageable from either the RepSpec or the InfoItem screen (#80).

**POST `/dashboard/rep-specs/{id}/document`** — replaces the `document` on a **draft** RepSpec (form field: `document`, a JSON object string). Mirrors the InfoSource source-specs editor exactly: HTMX requests (`hx-post`, `hx-target="#rep-spec-document-card"`, `hx-swap="outerHTML"`) get the re-rendered `_document_card.html` partial swapped in place — success carries an `HX-Trigger: showFlash` toast and moves focus to `#rep-spec-document-heading`; any rejection swaps the card back with the inline `doc_error` (`role="alert"`) visible, moves focus to the heading, and echoes the submitted text back into the textarea (status 200 so htmx performs the swap). Non-HTMX requests fall back to 303 on success / full-page 422 re-render on error (progressive enhancement). Rejections: JSON parse failure, schema/sub-schema validation, attempted `provider` change (immutable), and `RepSpecNotDraftError` — the last is re-checked server-side because a rendered editor can go stale if the spec acquires an assignment mid-edit. Whole-document replace, not merge (#83).

**DELETE `/dashboard/rep-specs/{id}/assignments/{aid}`** — deactivates a RepSpec assignment (sets `deactivated_at`); the assignment must belong to `{id}` (404 otherwise). Returns the re-rendered `rep_specs/_assignments.html` section fragment.

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

**State:** `step: number`, `url: string`, `sourceSpecs: string`, `itemName: string`, `description: string`, `cadence: string` (Watcher fetch-cadence interval, default `"1d"`), `watchActive: boolean` (default `true`; "Watch active immediately" — false provisions paused), `checkHostname: string` / `checkDomainKnown: boolean|null` (last url-check result, fed by `urlCheckDispatch`; `null` = no check landed yet; the payload's `case` field is intentionally not stored — only the domain fact feeds the summary bar) *(#53)*.

**Getters:**
- `cadenceLabel` — returns the human-readable label for the selected cadence by reading the text of the matching `<option>` in `$refs.cadenceInput` (no hardcoded map; the server-rendered options are the single source). Shown in the Step 4 review row.
- `watchActiveLabel` — returns "Active immediately" / "Paused" for the Step 4 review row.
- `urlHostname` *(#53)* — hostname parsed client-side from `url` via `new URL()`; `""` when the URL doesn't parse.
- `domainSummary` *(#53)* — `"known domain"` / `"new domain"` when the last url-check result matches the *current* `urlHostname` (guards against stale checks after the user edits the URL), else `""`.
- `selectorSummary` *(#53)* — compact human summary of the `sourceSpecs` JSON: `css: .rule-title` (single spec), `full_page` (no selector), `2 specs (css + regex)` (multiple). Falls back to the raw text truncated to 80 chars + `…` while the JSON doesn't parse (operator mid-edit). Used by the summary bar and the Step 4 review Selector row (where `:title="sourceSpecs"` keeps the full JSON inspectable as a tooltip).

**Methods:**
- `init()` — copies **all** server-rendered field values into Alpine state via `$refs`: `urlInput` → `url`, `sourceSpecsInput` → `sourceSpecs`, `nameInput` → `itemName`, `descriptionInput` → `description`, `cadenceInput` → `cadence`, `watchActiveInput.checked` → `watchActive`. **Every `x-model`-bound field must be synced here** — `x-model` is data-authoritative at bind time, so any unsynced server-rendered value is wiped to `""` on validation-error re-renders (#53 regression; pinned by `tests/js/register-wizard-alpine.test.js` against the real Alpine build).
- `onUrlCheck(detail)` *(#53)* — stores a bubbled url-check result (`{hostname, case, domain_known}`) into `checkHostname` / `checkDomainKnown`.
- `loadSuggestions()` — fires an HTMX GET to `/dashboard/register/suggest-specs?url=<encoded>`, targeting `#spec-suggestions-panel`. Called by the step-1 "Next" button.
- `prepareSubmit()` — no-op; `x-model` keeps the textarea in sync without a manual step.

**Events:**
- `@chip-insert.window` — receives chip inserts from `sortableChips` and writes the chip value into `sourceSpecs`. Wired on the root element.
- `@preview-name` — receives bubbled `preview-name` events from `previewNameDispatch` children. Pre-fills `itemName` if still blank: `if (!itemName.trim()) itemName = $event.detail.name`. Wired on the root element.
- `@url-check.window` *(#53)* — receives bubbled `url-check` events from `urlCheckDispatch` islands: `onUrlCheck($event.detail)`. Wired on the root element.

**Usage:**
```html
<div class="entity-section"
     x-data="registerWizard({{ initial_step|default(1) }})"
     @chip-insert.window="sourceSpecs = $event.detail.label"
     @preview-name="if (!itemName.trim()) itemName = $event.detail.name"
     @url-check.window="onUrlCheck($event.detail)">
  ...
  <input x-ref="urlInput" x-model="url" ...>
  <textarea x-ref="sourceSpecsInput" x-model="sourceSpecs" ...></textarea>
  <input x-ref="nameInput" x-model="itemName" ...>
  <textarea x-ref="descriptionInput" x-model="description" ...></textarea>
</div>
```

JS tests: `tests/js/register-wizard.test.js` (unit, stub Alpine) and `tests/js/register-wizard-alpine.test.js` (init-sync regression against the real vendored Alpine).

### `urlCheckDispatch` Alpine Component  *(#53 — implemented)*

One-shot event dispatcher, identical in shape to `previewNameDispatch`: reads the url-check result from a JSON data island child element and fires a bubbling `url-check` custom event. Emitted by the `_url_check.html` HTMX partial (all non-error branches) so the wizard's rolling summary bar can show `known domain` / `new domain` beside the URL after step 1.

**Events dispatched:** `url-check` (bubbles) with payload `{ hostname: string, case: "A"|"B"|"new", domain_known: boolean }`.

**Usage:**
```html
{# Top of _url_check.html, before the case cards #}
{% if not error and hostname %}
<div x-data="urlCheckDispatch"><script type="application/json">{{ {"hostname": hostname, "case": case, "domain_known": domain is not none} | tojson }}</script></div>
{% endif %}
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
