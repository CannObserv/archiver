# Archiver Dashboard — UI Reference

**Page inventory, HTMX swap patterns, Alpine.js component catalogue, flash/modal usage guide.**

> **AGENTS.md enforcement:** This file must be updated in the same commit as any Jinja2 template change, new route, or new Alpine.js component.

---

## URL Structure

```
/dashboard/                          Home — CTA, health strip, Recent Activity, domain overview
/dashboard/domains/                  Domains list
/dashboard/domains/{name}            Domain detail — notes, status, linked sources
/dashboard/register                  Register Information Item — 4-step flow
/dashboard/info-items/               Information Items list
/dashboard/info-items/{id}           Information Item detail (hub page — 5-section scroll)
/dashboard/info-items/new            → 301 redirect to /dashboard/register
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

### Domain pages (`/dashboard/domains/`)

**GET `/dashboard/domains/`** — paginated list. Columns: Domain (linked to detail), Sources (count), Status badge, Created. Filter bar: `?is_active=true|false|` (all). Source counts come from a GROUP BY query.

**GET `/dashboard/domains/{name}`** — detail. `.entity-card` header (canonical detail-screen pattern, #82): `.eyebrow` "Domain" kicker → `<h1 class="entity-card__title" id="domain-heading" tabindex="-1">` with the copyable domain name → `.detail-grid` (Status badge, created_at UTC). Operator notes (HTMX inline edit); linked Information Sources table, its heading count from a route `COUNT` so it stays accurate across pagination (#82), source URLs carrying `open_button`. `has_more` stays on its own `limit+1` probe (see **Related-collection tables**). Two empty states: an overshot `offset` (stale bookmark, or rows removed mid-session) renders "No sources on this page" with a link back to `?offset=0`, a genuinely empty collection "No Information Sources registered for this domain yet" — the heading count would otherwise contradict the "none registered" copy. **Archive** lives in a `.danger-zone` block at the bottom, shown only while the domain is active (`.btn--danger` + static confirm). **Restore** is recovery, not destruction, so it sits in the header Status field inline next to the "archived" badge (`.btn--secondary`); once archived the danger zone is hidden entirely. Both stay full-page POST→303 by design — see the *allowed variant* note under **HTMX mutations**.

**POST `/dashboard/domains/{name}/notes`** — HTMX partial; replaces `#notes-section` with `domains/_notes_partial.html`. Saves notes inline.

**POST `/dashboard/domains/{name}/archive`** — sets `archived_at`, redirects 303 to detail. Triggered from the danger-zone Archive button.

**POST `/dashboard/domains/{name}/restore`** — clears `archived_at`, redirects 303 to detail. Triggered from the header Restore button.

Templates: `domains/list.html`, `domains/detail.html`, `domains/_notes_partial.html`.

### Registration flow (`/dashboard/register`)

4-step flow (#49): URL → Selector → Metadata → Review & Submit. Full spec:
`docs/plans/2026-06-04-dashboard-ux-redesign-design.md`. State lives in the
`registerWizard` component (see catalogue).

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

## Authentication

Every dashboard request — full pages and HTMX partials alike — passes through
`get_dashboard_user` (`src/dashboard/deps.py`). It reads the `X-ExeDev-UserID`
and `X-ExeDev-Email` request headers, upserts `AppUser` (creates if new, updates
the email if changed) and returns the row; absent headers → 307 redirect to
`/__exe.dev/login?redirect=<path>`. Tests override via
`app.dependency_overrides[get_dashboard_user]`.

The gate is universal, so the route entries elsewhere in this doc do not repeat
it: assume any dashboard route redirects 307 when unauthenticated.

---

## HTMX Patterns

### Boosted navigation

`<body hx-boost="true">` — all in-dashboard `<a>` links and form submissions use HTMX fetch automatically (no full page reload). HTMX swaps the `<body>` and updates `<title>`.

### Partial fragment swaps

Server returns a partial HTML fragment with `HX-Reswap: outerHTML` / `HX-Retarget: #target-id` headers when refreshing a sub-section (e.g., the rep-spec assignment table row).

### Inline validation errors (`hx-target-422`)

`<body hx-ext="response-targets">` enables the vendored
`htmx-ext-response-targets` extension, which lets a form send a failure response
somewhere other than its success target. A form that can 422 carries
`hx-target-422="#some-error"` and the route returns just that error `<div>`, so
the message lands beside the field instead of replacing the whole form. Both
forms in `info_items/_swap_primary.html` use it; route entries elsewhere name
only their target id.

This is the form-level counterpart to the pagination clamp (see **Pagination
params are clamped, not validated**) — query-param errors are removed by
clamping, form-field errors are rendered.

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

### `apiKeyRow`

Inline edit/view toggle for a single API key table row.

**State:**
- `editing: boolean` — whether the row is in edit mode.

**Methods:**
- `cancelEdit()` — set `editing = false` without a server call, and reset the label input to its server-rendered value via `$refs.labelInput.defaultValue` so an abandoned edit is discarded rather than lingering in the hidden input.

**Usage:** `x-data="apiKeyRow"` on each `<tr id="key-row-{id}">`. View mode shows the label as text with Edit + Delete buttons. Edit mode reveals a label input (`x-ref="labelInput"`) and Save + Cancel buttons. Save uses HTMX `hx-patch` with `hx-include="#label-{id}"` to send the updated label; the server returns a fresh `_api_key_row.html` fragment that initialises with `editing: false`. Cancel calls `cancelEdit()`. Edit-mode elements carry `style="display:none;"` as an initial-state hint to prevent FOUC before Alpine runs.

### `apiKeyReveal`

Reveal-once panel for a newly created API key.

**State:**
- `rawKey: string` — the one-time raw key value (set via `x-init`).
- `copied: boolean` — clipboard copy feedback.

**Methods:**
- `copy()` — write `rawKey` to clipboard, set `copied = true` for 2 s.

**Usage:** `x-data="apiKeyReveal" x-init="rawKey = '{{ new_raw_key }}'"` on the reveal section returned by `POST /dashboard/settings/api-keys`. `rawKey` is assigned directly in `x-init` (direct property assignment through the Alpine reactive proxy — do not use a method call from `x-init` as `this` is unbound). The raw key is embedded server-side in the one-time render; it is not stored client-side beyond the DOM lifetime.

### `infoItemWizard`

3-step create form for Information Items, on `info_items/new.html`. Interactive
registration goes through `/dashboard/register` instead; this template is reached
only as the 422 re-render of the legacy `POST /dashboard/info-items/new`.

**State:**
- `step: number` — current step (1 = Basics, 2 = Source, 3 = Review).
- `name: string`, `description: string`, `owner: string` — form field values.
- `repFieldsRaw: string` — raw JSON string for `rep_fields`, written by a nested `jsonFieldEditor`.
- `initialUrl: string` — URL for the optional initial InfoSource.
- `initialSourceSpecsRaw: string` — raw JSON array string for `initial_source_specs`, bound via `x-model="initialSourceSpecsRaw"` on the step-2 textarea rather than a `jsonFieldEditor` (arrays are not objects). That textarea also carries `name="initial_source_specs"`, so the form POST captures it without a hidden input.

**Methods:**
- `nextStep()` — advance a step; step 1 guards that `name` is non-empty.
- `prepareSubmit()` — form-submit hook; a no-op, since editors write into root props on blur and `initialSourceSpecsRaw` stays in sync via `x-model`.

**Usage:** `x-data="infoItemWizard"` on the outer `<div>`. Step 2 shows the
`initial_url` text input and the `initial_source_specs` JSON array textarea.

### `sourceSpecEditor`

Registered in `main.js` but bound by no template: the InfoSource new/edit forms
use a plain `<textarea name="source_specs">` with inline error display.

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
### `repSpecEditor`

Single-field document editor with client-side JSON parse validation on blur.

**Parameters (factory args):**
- `initialValue: string` — initial document JSON string (pass `{{ document_raw | tojson }}`).
- `initialProvider: string` — initially selected provider (pass `{{ (selected_provider or "") | tojson }}`).

**State:** `provider: string`, `raw: string`, `hasError: boolean`, `errorMsg: string`.

**Methods:** `validate()` — called on `@blur`; attempts `JSON.parse(raw)`, sets `hasError`/`errorMsg`.

**Usage:** `x-data='repSpecEditor({{ document_raw | tojson }}, {{ (selected_provider or "") | tojson }})'` on the create form wrapper, passing server-rendered initial values so Alpine's `x-model` initialises correctly on re-render. Provider `<select x-model="provider">` drives `provider` state for optional template reactions.

### `sortableChips`

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

### `registerWizard`

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

### `urlCheckDispatch`

One-shot event dispatcher, identical in shape to `previewNameDispatch`: reads the url-check result from a JSON data island child element and fires a bubbling `url-check` custom event. Emitted by the `_url_check.html` HTMX partial (all non-error branches) so the wizard's rolling summary bar can show `known domain` / `new domain` beside the URL after step 1.

**Events dispatched:** `url-check` (bubbles) with payload `{ hostname: string, case: "A"|"B"|"new", domain_known: boolean }`.

**Usage:**
```html
{# Top of _url_check.html, before the case cards #}
{% if not error and hostname %}
<div x-data="urlCheckDispatch"><script type="application/json">{{ {"hostname": hostname, "case": case, "domain_known": domain is not none} | tojson }}</script></div>
{% endif %}
```

### `previewNameDispatch`

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

### `repFieldsEditor`

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


## Detail Screen Conventions

Canonical patterns for entity **detail** pages. The Source Revision detail
(`source_revisions/detail.html` + `_detail_card.html`) is the reference
implementation (archiver#78); other detail screens should converge on these.

**Header.** An `.entity-card` whose `.entity-card__header` contains, in order:
1. An `.eyebrow` kicker naming the entity kind, singular (e.g. "Information
   Source Revision"). Non-interactive; detail screens carry no breadcrumb `<nav>`.
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

*Editor cards.* A card whose body is an inline editor — InfoSource **Source
Specification**, RepSpec **Document** — follows one shape. Extract the card to a
partial with stable root and heading `id`s and `hx-post` with
`hx-target="#…-card" hx-swap="outerHTML"`. Success returns the re-rendered card
with `HX-Trigger: showFlash` and moves focus to the heading. **A rejection
returns status 200, not 422**, so htmx still performs the swap: the card comes
back with its inline `*_error` (`role="alert"`) visible, focus on the heading,
and the operator's submitted text echoed into the textarea so the edit is not
discarded. Non-HTMX requests fall back to a 303 on success and a full-page 422
re-render — text still preserved — on failure, so the editor works without JS.

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
carrying the row count (e.g. "Revision History (12)"). When the table is **paginated**,
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
succession/currency status column uses `.badge--primary`/`.badge--muted`.

**Pagination params are clamped, not validated.** Every paginated dashboard
route takes `page: Pagination = Depends(pagination)`
(`src/dashboard/pagination.py`) rather than bare `limit`/`offset` ints. `limit`
clamps to `[1, 200]`, `offset` to `[0, 2**63 - 1]`, so out-of-range values render
a sensible page instead of erroring (#84). The upper offset bound is a storage
limit rather than a product judgement: the query binds offset to
`OFFSET $2::BIGINT` and asyncpg rejects anything wider with `DataError: value out
of int64 range`, which surfaced as a 500 until it was capped — and capping costs
nothing else, since any offset that large already yields an empty page.

This is a **deliberate divergence from the API layer**, which uses
`Query(ge=…, le=…)` and returns 422. The API is a contract surface where a bad
`limit` is a client bug worth surfacing loudly; the dashboard is a human surface
reached by hand-edited URLs and stale bookmarks. It also has no HTML rendering
path for validation errors — `RequestValidationError` falls through to the
app-wide handler in `src/api/errors.py`, which always returns JSON, and HTMX does
not swap non-2xx responses, so a 422 on a partial silently does nothing. Clamping
removes the error path rather than styling it.

**The params are declared `str`, not `int`, and parsed in the dependency** (#86).
Under `int` annotations FastAPI coerces *before* the dependency runs, so
`?limit=abc` answers a browser with a raw JSON envelope. Parsing inside
`clamp_pagination` closes that: unparseable input falls back to the default
(`int()`'s tolerance of surrounding whitespace is kept, so `?limit=%2025%20`
still means 25), and each param is handled independently so one bad value doesn't
discard the other. Since `limit` and `offset` are the only non-`str` request
params on any dashboard route — every form field is `str`, path params are `str`
ULIDs — no `RequestValidationError` is reachable from a dashboard URL. Form-field
validation is a separate mechanism; see **Inline validation errors**.

That completeness claim is enforced, not just asserted:
`test_pagination.py::test_no_dashboard_route_declares_a_coercible_param` walks
every `/dashboard` route's flattened dependant and fails if any query, path, or
body param is annotated as anything but `str` (`str | None` is fine —
optionality is absence, not coercion). **A new dashboard route must take its
params as `str`**; declaring `page: int` or `after: date` reopens the raw-JSON
422, because coercion happens during dependency solving before any dashboard
code runs.

The dependency is `async` so FastAPI resolves it inline rather than paying a
`run_in_threadpool` hop for two comparisons; the parse and arithmetic live in a
sync `clamp_pagination()` helper so they stay unit-testable without reaching
through `Query` defaults. Each param's `description` documents the
clamp-don't-reject behaviour for readers of the code. New paginated routes must
use the dependency; do not reintroduce bare `limit: int = 50`.

None of this reaches OpenAPI: dashboard routers are included with
`include_in_schema=False` (#87), because `clients/python/scripts/regen.sh`
generates the public SDK from `app.openapi()`, so any dashboard path in the
schema is one routine regen away from shipping as `archiver_client` API surface
— HTML responses under proxy-header auth, useless as client methods.
`test_openapi_exclusion.py` pins the exclusion, and **a ninth dashboard router
must be added to the loop in `register_dashboard`** rather than via its own
`app.include_router(...)` call, so it cannot forget the flag.

If a dashboard route ever needs a typed param that *cannot* be clamped into
something sensible — a date filter, say — this approach runs out, and the HTML
error-page work sketched in #86 (a `_422.html` plus a dashboard-owned
`RequestValidationError` handler registered from `register_dashboard`) becomes
the answer.

## Page Inventory

### Home (`/dashboard/`)

**GET `/dashboard/`** — summary dashboard. Four count tiles in nav order (Information Items, Information Sources, Information Source Revisions, Replication Specifications), each linking to its list page. Service health indicator loads via `hx-get="/dashboard/health" hx-trigger="load"` — non-blocking, showing a "checking…" badge until HTMX fires. Recent Changes table: last 10 SourceRevisions ordered by `captured_at desc`; columns Information Source (URL, links to source detail), Source Revision (truncated fingerprint, links to revision detail), Observed (captured_at as `%Y-%m-%d %H:%M`).

**GET `/dashboard/health`** — HTMX partial. Returns `<span class="badge badge--success">ok</span>`.

**GET `/dashboard/health/watcher`** — HTMX partial calling `WatcherClient.health_check()` (`GET /health` on Watcher). **GET `/dashboard/health/redis`** — HTMX partial calling `redis.ping()`. Both log a warning on anything but ok:

| Badge | `…/health/watcher` | `…/health/redis` |
|---|---|---|
| `badge--success` "ok" | HTTP 200 | ping succeeded |
| `badge--warning` "degraded" | reachable, non-200 status; `title` contains "Watcher returned {status}" | — |
| `badge--danger` "error" | network/connect failure; `title` contains the exception message | `title` contains `"{ExcClass}: {message}"` |
| `badge--muted` "not configured" | `WATCHER_BASE_URL` unset | `ARCHIVER_REDIS_URL` unset |

### Information Items (`/dashboard/info-items/`)

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

### Information Sources (`/dashboard/info-sources/`)

**GET `/dashboard/info-sources/`** — paginated list. Query params: `url_contains` (ilike filter on the `url` column), `limit`, `offset`.

**GET `/dashboard/info-sources/new`** — create form. Fields: `url` (text input) + `source_specs` (JSON array textarea, validates JSON on blur).

**POST `/dashboard/info-sources/new`** — form fields: `url` (string), `source_specs` (JSON array string). Calls `create_info_source`. 303 to detail on success; re-renders the form with an `errors` dict on `InvalidUrlError`, `InvalidSourceSpecError`, `MixedAlgorithmFamilyError`.

**GET `/dashboard/info-sources/{id}`** — detail page. Sections:

- Header: `.entity-card` (canonical pattern, #79) — `.eyebrow` "Information Source" → `<h1 class="entity-card__title" id="info-source-heading" tabindex="-1">` with the `url` in `<code>` → an `open_button` to the URL → copyable `info_source_id` → `.detail-grid` (created_at UTC).
- Source Specification editor — the `info_sources/_source_specs_card.html` partial, extracted so the update-specs action can swap it in place (root `#source-specs-card`, heading `#source-specs-heading`, titled "Source Specification"). The `sourceSpecsCard(startEditing)` component (`main.js`) gates it: **view mode** (`x-show="!editing"`) shows the current `source_specs` array in `<pre class="code-block">` with an **Edit** button; Edit reveals the textarea form (`x-show="editing"`) with **Cancel** (`btn--secondary`, for border parity with the `apiKeyRow` Cancel; `@click="cancel()"` resets the textarea to the stored specs and returns to view mode with no server call) and **Save** (submits the `POST .../source-specs` replace). The editor has no visible `<label>` — the card heading already names the control, and a label appearing only on Edit caused layout jank — so `aria-label="Source Specification (JSON Array)"` keeps the textarea named for assistive tech, matching the create-form label wording. The canonical stored specs ride in a `<script type="application/json">` data island read by `init()`, never in an HTML attribute: `tojson` output embedded in a double-quoted attribute breaks out of the quotes (the `sortableChips` convention; #100). The card opens in edit mode when `specs_error` is set (`sourceSpecsCard(true)`) so the error and the operator's submitted text stay visible. No `x-cloak` — without JS both view and editor render and Save posts normally (progressive enhancement). The URL is immutable.
- Other Sources at This URL — shown only when other InfoSources share this `url` (the model allows several sources per URL, #79 #8); count in the heading, capped at 50 via a `limit+1` probe and rendered "50+" beyond that, each linked by `info_source_id` with its created date UTC.
- Bound Information Items — table of active `info_item_sources` bindings (count in heading; item name link, bound date UTC).
- Revision History — last 50 `source_revisions` ordered by `captured_at desc` (count in heading; fingerprint truncated, captured date UTC, cache status pill).

**POST `/dashboard/info-sources/{id}/source-specs`** — replaces the `source_specs` list on an existing InfoSource (form field: `source_specs` JSON array). An **editor card** (see the detail-screen conventions) against `#source-specs-card`, error key `specs_error` (#79 #7). Rejections: JSON parse failure, schema validation, mixed algorithm family.

### Information Source Revisions (`/dashboard/source-revisions/`)

**GET `/dashboard/source-revisions/`** — paginated list ordered by `captured_at desc`. Optional `info_source_id` filter (ULID). Columns: truncated fingerprint (link to detail), source URL (link to InfoSource detail), captured date, cache status pill (`.status-pill--cached` / `.status-pill--expired` / `.status-pill--missing`).

**GET `/dashboard/source-revisions/{id}`** — detail page, and the reference implementation of the detail-screen conventions above. The header lives in `source_revisions/_detail_card.html`, extracted so clear-cache can swap it in place (root `#revision-card`): `.eyebrow` "Information Source Revision" above an `<h1>` whose title is the copyable `source_revision_id`. `.detail-grid` carries the copyable full fingerprint and the Information Source, both on `.detail-grid__item--full` rows so long values extend horizontally; the Information Source value holds the internal source-detail link plus an `open_button` to the target URL. Then captured_at (UTC), size (if set), media type (if set), and cache status. The Cache value shows a status pill plus the `content_cache_uri` — with an `open_button` when `http(s)`, otherwise copyable — and an expiry line. "View all revisions for this source →" deeplinks the list as `?info_source_id=`. A danger-zone clear-cache form shows only when `content_cache_uri` is set.

**POST `/dashboard/source-revisions/{id}/clear-cache`** — sets `content_cache_uri = NULL` and `content_cache_expires_at = NULL`. HTMX requests (`hx-post`, `hx-target="#revision-card"`, `hx-confirm`) get the re-rendered `_detail_card.html` swapped in place plus an `HX-Trigger: showFlash` success toast; non-HTMX requests fall back to a 303 to detail. No request body required.

### Replication Specifications (`/dashboard/rep-specs/`)

**GET `/dashboard/rep-specs/`** — paginated list. Optional `provider` filter (enum: `gcs` / `gdrive` / `ia`). Columns: name (link to detail), provider badge, created_at.

**GET `/dashboard/rep-specs/new`** — create form. Provider `<select>`, name text input, document JSON textarea (the `repSpecEditor` component, validate-on-blur). Returns 200 with an errors dict on validation failure.

**POST `/dashboard/rep-specs/new`** — form fields: `provider`, `name`, `document` (JSON string). Calls `create_rep_spec`. 303 to detail on success; re-renders the form with errors on missing provider, missing name, invalid JSON, or `InvalidRepSpecError`.

**GET `/dashboard/rep-specs/{id}`** — detail page.

- Header: `.entity-card` (canonical pattern, #80) — `.eyebrow` "Replication Specification" → `<h1 class="entity-card__title" id="rep-spec-heading" tabindex="-1">` name → copyable `rep_spec_id` → `.detail-grid` (provider badge, created_at UTC, plus **Updated** UTC *only when* `updated_at` is non-null — a null means "never edited", and rendering `created_at` there would blur that distinction, #83).
- Document card — the `rep_specs/_document_card.html` partial, extracted so the update-document action can swap it in place (root `#rep-spec-document-card`, heading `#rep-spec-document-heading`). Shows the stored document JSON in `<pre class="code-block">`, then **conditionally** an edit form: the textarea renders only while the RepSpec is a *draft*, meaning zero `info_item_rep_specs` rows, active **or** deactivated. That count comes from `assignment_count()`, deliberately not `_load_active_assignments`, because a deactivated assignment still means a replication run happened under that document. A non-draft renders an `.alert--info` "frozen" notice with the assignment count instead of the form (#83; clone + migrate is #95).
- Active assignments — `rep_specs/_assignments.html` (wrapper `#rep-spec-assignments`): count in heading; item name link, activated_at UTC, `public_url` with an `open_button`, and a **Deactivate** action. Deactivate is `hx-delete` to the RepSpec-scoped route below, targeting `#rep-spec-assignments` (`outerHTML`) so the row set, count, and empty-state re-render together. Assignments are manageable from either the RepSpec or the InfoItem screen (#80).

**POST `/dashboard/rep-specs/{id}/document`** — replaces the `document` on a **draft** RepSpec (form field: `document`, a JSON object string). An **editor card** against `#rep-spec-document-card`, error key `doc_error` — the same shape as the InfoSource source-specs editor. Whole-document replace, not merge (#83). Rejections: JSON parse failure, schema/sub-schema validation, an attempted `provider` change (immutable), and `RepSpecNotDraftError` — the last re-checked server-side, because a rendered editor goes stale if the spec acquires an assignment mid-edit.

**DELETE `/dashboard/rep-specs/{id}/assignments/{aid}`** — deactivates a RepSpec assignment (sets `deactivated_at`); the assignment must belong to `{id}` (404 otherwise). Returns the re-rendered `rep_specs/_assignments.html` fragment.

### Settings — API Keys (`/dashboard/settings/api-keys`)

**GET** — lists the current user's keys. Table columns: Label, Prefix, Last Used, Actions. The create form starts collapsed; "+ Add key" in the header expands it.

**POST** — creates a key (`label` form field required). Returns the full page with `new_raw_key` in the template context so `apiKeyReveal` shows the raw key once; the create form collapses (`showForm` resets to false) and the reveal panel appears above the table. After navigation the raw key is gone.

**DELETE `/dashboard/settings/api-keys/{id}`** — HTMX delete; the response replaces `<tr id="key-row-{id}">` with an empty string, removing the row. 404 if the key belongs to a different user.

**PATCH `/dashboard/settings/api-keys/{id}`** — renames the label (`label` form field, submitted via `hx-include`). Returns the `settings/_api_key_row.html` fragment replacing the row in view mode. 404 if the key belongs to a different user.

Partial template: `settings/_api_key_row.html` — reusable `<tr x-data="apiKeyRow">` used both in the list render and as the PATCH response. Starts in view mode (`editing: false`); Edit switches to edit mode, Save sends the PATCH, Cancel reverts with no server call.
