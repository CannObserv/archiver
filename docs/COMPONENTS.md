# Archiver Dashboard - Alpine.js Component Catalogue

**Every `Alpine.data` component the dashboard registers, its state, its methods,
and how templates wire it up.**

Where each component is used is in [PAGES.md](PAGES.md); the HTMX patterns they
sit alongside are in [UI.md](UI.md). The one-line summary table below is
the index into them; `docs/STYLE.md` carries the CSS classes they toggle.

> **AGENTS.md enforcement:** update this file in the same commit as any change
> to a JS module under `src/dashboard/static/`.

---

All components registered as `Alpine.data('name', factory)` in `main.js` before `Alpine.start()`. No inline `x-data="{ ... }"` blobs in templates.

Three JS modules under `src/dashboard/static/` register **no** Alpine component
and are catalogued at the foot of this file instead: `flash.js`,
`dark-mode.js`, and `htmx-errors.js`. They attach document-level listeners at
load and are wired only by their `<script>` tag in `base.html`.

## Catalogue index

| Component | File | Description |
|---|---|---|
| `sortableChips` | `main.js` | Chip strip for selector/rep-field suggestions with client-side sort. Uses JSON data island: `x-data="sortableChips('frequency')"` with `<script type="application/json">{{ chips \| tojson }}</script>` inside. Optional `value` field on each chip overrides the dispatch payload. Clicking dispatches `chip-insert` window event; caller listens with `@chip-insert.window`. |
| `repFieldsEditor` | `main.js` | Wrapper for the rep_fields textarea + suggestion strip. Listens for `chip-insert` window events and merges the key into the existing JSON object. Usage: `x-data="repFieldsEditor()" @chip-insert.window="insertKey($event.detail.label)"`. |
| `repSpecEditor` | `main.js` | JSON editor for RepSpec documents on the create form. |
| `apiKeyReveal` | `main.js` | One-time raw key display after API key creation. |
| `domainNotes` | `main.js` | Edit/view toggle for the notes row in the domain detail header panel (#176). Cancel resets the textarea to its `defaultValue`. |
| `editableField` | `main.js` | Row-level edit/view toggle for a single field, agnostic about the control it wraps (#181). The Watcher panel's editable rows use it. Cancel restores the server-rendered value through `$refs.field`. |
| `registerWizard` | `main.js` | 4-step registration wizard state: step navigation, field state synced from server-rendered values in `init()` (every `x-model` field must be synced there or validation re-renders wipe it - #53), rolling step-summary bar getters (`urlHostname`, `domainSummary`, `selectorSummary`). |
| `previewNameDispatch` | `main.js` | One-shot dispatcher: bubbles a `preview-name` event from a JSON data island inside the preview-result fragment. |
| `urlCheckDispatch` | `main.js` | One-shot dispatcher (#53): bubbles a `url-check` event (`{hostname, case, domain_known}`) from a JSON data island inside the `_url_check.html` fragment; feeds the wizard's rolling summary bar. |

---

## `apiKeyCreate`

Create-form toggle for the API Keys settings page.

**State:**
- `showForm: boolean` - whether the create-key panel is expanded.

**Usage:** `x-data="apiKeyCreate"` on the outer `<div class="entity-section">`. A `<button @click="showForm = !showForm">` in the header toggles the form. The form panel uses `x-show="showForm" x-cloak` to hide before Alpine initialises. After a full-page POST response, `showForm` resets to its initial `false` state automatically (form collapses; the new-key reveal panel appears instead).

## `apiKeyRow`

Inline edit/view toggle for a single API key table row.

**State:**
- `editing: boolean` - whether the row is in edit mode.

**Methods:**
- `cancelEdit()` - set `editing = false` without a server call, and reset the label input to its server-rendered value via `$refs.labelInput.defaultValue` so an abandoned edit is discarded rather than lingering in the hidden input.

**Usage:** `x-data="apiKeyRow"` on each `<tr id="key-row-{id}">`. View mode shows the label as text with Edit + Delete buttons. Edit mode reveals a label input (`x-ref="labelInput"`) and Save + Cancel buttons. Save uses HTMX `hx-patch` with `hx-include="#label-{id}"` to send the updated label; the server returns a fresh `_api_key_row.html` fragment that initialises with `editing: false`. Cancel calls `cancelEdit()`. Edit-mode elements carry `style="display:none;"` as an initial-state hint to prevent FOUC before Alpine runs.

## `domainNotes`

Edit/view toggle for the operator-notes row in the Domain detail header panel.

**State:**
- `editing: boolean` - whether the row shows the textarea instead of the read-only readout.

**Methods:**
- `cancelEdit()` - set `editing = false` without a server call, and reset the textarea to its server-rendered value via `$refs.notesBox.defaultValue` so an abandoned edit is discarded rather than lingering in the next Save.

**Usage:** `x-data="domainNotes"` on `#notes-section` in `domains/_notes_partial.html`. View mode (`x-show="!editing"`) renders the stored notes in a `.notes-readout` beside an Edit button; edit mode (`x-show="editing"`) reveals `<textarea x-ref="notesBox">` beside Cancel + Save. Save posts via HTMX (`hx-target="#notes-section" hx-swap="outerHTML"`), and the returned partial re-initialises with `editing: false` - so a saved edit lands back in view mode without any client-side bookkeeping. The edit form deliberately carries **no** inline `display:none` FOUC hint - unlike `apiKeyRow`, whose row has no no-JS edit path to lose. Hiding it inline would also hide it when Alpine never runs, stranding the `method`/`action` fallback; both halves rendering for a frame is the price of Save still working without JS, and the route answers a non-HTMX POST with a 303 rather than a bare fragment.

`defaultValue` is the right canonical source here, where `sourceSpecsCard` needs a JSON data island: notes have no validation-error re-render path, so the server-rendered value is always the stored one.

## `editableField`

Row-level edit/view toggle for a single editable field. The generalisation of
`domainNotes`: same `editing` flag and same discard-on-cancel, but with no
opinion about the control it wraps, so several fields on one panel can share it.

**State:**
- `editing: boolean` - whether the row shows the control instead of the read-only readout.

**Methods:**
- `cancelEdit()` - set `editing = false` without a server call and restore the server-rendered value through `$refs.field`. A `<select>` has no `defaultValue`, so it restores each option's `defaultSelected` instead; anything else falls back to `el.value = el.defaultValue`.

**Usage:** `x-data="editableField"` on the `.field-row-group` wrapper in
`info_items/_cadence_editor.html`. View mode (`x-show="!editing"`) renders the
current cadence label in a `.field-row__readout` beside Edit; edit mode
(`x-show="editing"`) reveals `<select x-ref="field">` beside Cancel + Save. Save
posts over HTMX with `hx-swap="none"`, and the response's
`HX-Trigger: {"watcherUpdated":{}}` re-renders `#watcher-section` once - so a
saved edit lands back in view mode because the whole panel is replaced, not
because the component reset itself.

Unlike `domainNotes`, the edit half **does** carry the inline `display:none`
FOUC hint - the `apiKeyRow` trade. There is no no-JS save path to strand:
`watch-cadence` answers with a bare fragment rather than a 303, and the form
only ever posted over HTMX.

## `apiKeyReveal`

Reveal-once panel for a newly created API key.

**State:**
- `rawKey: string` - the one-time raw key value (set via `x-init`).
- `copied: boolean` - clipboard copy feedback.

**Methods:**
- `copy()` - write `rawKey` to clipboard, set `copied = true` for 2 s.

**Usage:** `x-data="apiKeyReveal" x-init="rawKey = '{{ new_raw_key }}'"` on the reveal section returned by `POST /dashboard/settings/api-keys`. `rawKey` is assigned directly in `x-init` (direct property assignment through the Alpine reactive proxy - do not use a method call from `x-init` as `this` is unbound). The raw key is embedded server-side in the one-time render; it is not stored client-side beyond the DOM lifetime.

## `infoItemWizard`

3-step create form for Information Items, on `info_items/new.html`. Interactive
registration goes through `/dashboard/register` instead; this template is reached
only as the 422 re-render of the legacy `POST /dashboard/info-items/new`.

**State:**
- `step: number` - current step (1 = Basics, 2 = Source, 3 = Review).
- `name: string`, `description: string`, `owner: string` - form field values.
- `repFieldsRaw: string` - raw JSON string for `rep_fields`, written by a nested `jsonFieldEditor`.
- `initialUrl: string` - URL for the optional initial InfoSource.
- `initialSourceSpecsRaw: string` - raw JSON array string for `initial_source_specs`, bound via `x-model="initialSourceSpecsRaw"` on the step-2 textarea rather than a `jsonFieldEditor` (arrays are not objects). That textarea also carries `name="initial_source_specs"`, so the form POST captures it without a hidden input.

**Methods:**
- `nextStep()` - advance a step; step 1 guards that `name` is non-empty.
- `prepareSubmit()` - form-submit hook; a no-op, since editors write into root props on blur and `initialSourceSpecsRaw` stays in sync via `x-model`.

**Usage:** `x-data="infoItemWizard"` on the outer `<div>`. Step 2 shows the
`initial_url` text input and the `initial_source_specs` JSON array textarea.

## `sourceSpecEditor`

Registered in `main.js` but bound by no template: the InfoSource new/edit forms
use a plain `<textarea name="source_specs">` with inline error display, and the
detail-page editor is `sourceSpecsCard`. Slated for removal - archiver#135.

## `jsonFieldEditor`

Textarea-based JSON object editor with format-on-blur and inline validation.

**Parameters (factory args):**
- `rootProp: string` - name of a property on `$root` to write the formatted JSON string into on each valid blur.
- `_errorKey: string` - reserved for API symmetry; error state is component-local.

**State:**
- `raw: string` - raw textarea value.
- `hasError: boolean` - true when the current value is not a valid JSON object.
- `errorMsg: string` - human-readable parse error.

**Methods:**
- `formatAndValidate()` - called on `@blur`. Parses `raw`, pretty-prints valid objects, writes into `$root[rootProp]`, sets `hasError`/`errorMsg`.

**Usage:** `x-data="jsonFieldEditor('repFieldsRaw', 'rep_fields_error')"` on a wrapper element containing the `<textarea x-model="raw" @blur="formatAndValidate()">`.

---
## `repSpecEditor`

Single-field document editor with client-side JSON parse validation on blur.

**Parameters (factory args):**
- `initialValue: string` - initial document JSON string (pass `{{ document_raw | tojson }}`).
- `initialProvider: string` - initially selected provider (pass `{{ (selected_provider or "") | tojson }}`).

**State:** `provider: string`, `raw: string`, `hasError: boolean`, `errorMsg: string`.

**Methods:** `validate()` - called on `@blur`; attempts `JSON.parse(raw)`, sets `hasError`/`errorMsg`.

**Usage:** `x-data='repSpecEditor({{ document_raw | tojson }}, {{ (selected_provider or "") | tojson }})'` on the create form wrapper, passing server-rendered initial values so Alpine's `x-model` initialises correctly on re-render. Provider `<select x-model="provider">` drives `provider` state for optional template reactions.

## `sortableChips`

Chip strip for selector/rep-field suggestions with client-side re-sort.

Uses the **JSON data island** pattern: chip data is placed in a `<script type="application/json">` child element so JSON never appears inside an HTML attribute (which would require escaping `"` and is fragile). `init()` reads and parses the script element on startup.

**Parameters (factory args):**
- `defaultSort: string` - initial sort mode: `'frequency'` (default), `'asc'`, or `'desc'`.

**State:** `sort: string`, `chips: Array<{label, frequency, value?}>` (reactive, re-sorted on sort change).

**Chip shape:** `{label: string, frequency: number, value?: string}`. The optional `value` field is the dispatch payload when it differs from the display `label` (e.g. a full spec JSON array string vs a human-readable `"algorithm: selector"` label).

**Methods:**
- `setSort(mode)` - sets `sort` and re-sorts `chips` in place.
- `insertChip(label, value?)` - dispatches a `chip-insert` `CustomEvent` on `window` with `{ detail: { label: value ?? label } }`. Parent scopes listen via `@chip-insert.window`.
- `init()` - parses chip data from `<script type="application/json">` inside `$el`; falls back to reading `[data-label]`/`[data-frequency]` DOM attributes.

**Sort controls:** Three pill buttons - `[Frequency ▾]`, `[A → Z]`, `[Z → A]`. Active button gets `.btn--active .btn--sm`; others get `.btn--secondary .btn--sm`. Sort is purely client-side; no server round-trip.

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

## `registerWizard`

Multi-step Information Item registration wizard. Manages step navigation and form state across the 4-step URL → Selector → Metadata → Review flow. Used on `GET /dashboard/register` (see PAGES.md § **Registration flow**).

**Factory args:**
- `initialStep: number` - starting step (1-4; defaults to `1`). The server passes a non-1 value on validation re-renders to re-open at the failing step.

**State:** `step: number`, `url: string`, `sourceSpecs: string`, `itemName: string`, `description: string`, `cadence: string` (the announced `watch_spec` interval, default `"1d"` - Archiver's own policy as of archiver#158, written locally at registration rather than forwarded to Watcher; editable afterwards from the InfoItem detail panel), `watchActive: boolean` (default `true`; "Watch active immediately" - false provisions paused), `checkHostname: string` / `checkDomainKnown: boolean|null` (last url-check result, fed by `urlCheckDispatch`; `null` = no check landed yet; the payload's `case` field is intentionally not stored - only the domain fact feeds the summary bar) *(#53)*.

**Getters:**
- `cadenceLabel` - returns the human-readable label for the selected cadence by reading the text of the matching `<option>` in `$refs.cadenceInput` (no hardcoded map; the server-rendered options are the single source). Shown in the Step 4 review row.
- `watchActiveLabel` - returns "Active immediately" / "Paused" for the Step 4 review row.
- `urlHostname` *(#53)* - hostname parsed client-side from `url` via `new URL()`; `""` when the URL doesn't parse.
- `domainSummary` *(#53)* - `"known domain"` / `"new domain"` when the last url-check result matches the *current* `urlHostname` (guards against stale checks after the user edits the URL), else `""`.
- `selectorSummary` *(#53)* - compact human summary of the `sourceSpecs` JSON: `css: .rule-title` (single spec), `full_page` (no selector), `2 specs (css + regex)` (multiple). Falls back to the raw text truncated to 80 chars + `…` while the JSON doesn't parse (operator mid-edit). Used by the summary bar and the Step 4 review Selector row (where `:title="sourceSpecs"` keeps the full JSON inspectable as a tooltip).

**Methods:**
- `init()` - copies **all** server-rendered field values into Alpine state via `$refs`: `urlInput` → `url`, `sourceSpecsInput` → `sourceSpecs`, `nameInput` → `itemName`, `descriptionInput` → `description`, `cadenceInput` → `cadence`, `watchActiveInput.checked` → `watchActive`. **Every `x-model`-bound field must be synced here** - `x-model` is data-authoritative at bind time, so any unsynced server-rendered value is wiped to `""` on validation-error re-renders (#53 regression; pinned by `tests/js/register-wizard-alpine.test.js` against the real Alpine build).
- `onUrlCheck(detail)` *(#53)* - stores a bubbled url-check result (`{hostname, case, domain_known}`) into `checkHostname` / `checkDomainKnown`.
- `loadSuggestions()` - fires an HTMX GET to `/dashboard/register/suggest-specs?url=<encoded>`, targeting `#spec-suggestions-panel`. Called by the step-1 "Next" button.
- `prepareSubmit()` - no-op; `x-model` keeps the textarea in sync without a manual step.

**Events:**
- `@chip-insert.window` - receives chip inserts from `sortableChips` and writes the chip value into `sourceSpecs`. Wired on the root element.
- `@preview-name` - receives bubbled `preview-name` events from `previewNameDispatch` children. Pre-fills `itemName` if still blank: `if (!itemName.trim()) itemName = $event.detail.name`. Wired on the root element.
- `@url-check.window` *(#53)* - receives bubbled `url-check` events from `urlCheckDispatch` islands: `onUrlCheck($event.detail)`. Wired on the root element.

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

## `urlCheckDispatch`

One-shot event dispatcher, identical in shape to `previewNameDispatch`: reads the url-check result from a JSON data island child element and fires a bubbling `url-check` custom event. Emitted by the `_url_check.html` HTMX partial (all non-error branches) so the wizard's rolling summary bar can show `known domain` / `new domain` beside the URL after step 1.

**Events dispatched:** `url-check` (bubbles) with payload `{ hostname: string, case: "A"|"B"|"new", domain_known: boolean }`.

**Usage:**
```html
{# Top of _url_check.html, before the case cards #}
{% if not error and hostname %}
<div x-data="urlCheckDispatch"><script type="application/json">{{ {"hostname": hostname, "case": case, "domain_known": domain is not none} | tojson }}</script></div>
{% endif %}
```

## `previewNameDispatch`

One-shot event dispatcher that reads a suggested page title from a JSON data island child element and fires a bubbling `preview-name` custom event. Used inside the `_preview_result.html` HTMX partial so that a successful preview auto-fills the Name field on step 3.

Uses the **JSON data island** pattern (`sortableChips` above; the reason it exists is `docs/STYLE.md` § **JSON data island pattern**) - the title is placed in a `<script type="application/json">` child rather than an HTML attribute, avoiding double-quote escaping hazards from `tojson`.

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

## `repFieldsEditor`

Wrapper for the `rep_fields` textarea + sortableChips suggestion strip on the InfoItem detail hub page. Handles `chip-insert` window events by merging the clicked key into the existing JSON object (preserving other keys) rather than replacing the whole textarea value.

**Methods:**
- `insertKey(key)` - finds `[name=rep_fields]` within `$el`, parses its current value as JSON, adds `key: ""` if absent, and writes back pretty-printed JSON. Falls back gracefully on parse errors.

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

---

## Document-level scripts (not Alpine)

Each is an IIFE that attaches listeners to `document` on load, surviving HTMX
body swaps because nothing it binds to is inside the swapped tree. Dropping any
of them from the `base.html` script list is silent - the behaviour simply stops
(archiver#62).

### `flash.js`

Toast/flash system. Listens for the `showFlash` `CustomEvent` - dispatched by
htmx from an `HX-Trigger` response header, or directly by other scripts - and
injects `.flash--*` toasts into the `#flash-region` overlay, announcing every
message through the two visually-hidden live regions. All three regions are
**recreated on demand** when absent: a boosted swap replaces everything inside
`<body>`, and the dashboard error page does exactly that, so without it the
first toast after such a swap was dropped in silence (archiver#178). Levels, dismissal rules,
the visible cap and its two overflow affordances: [UI.md](UI.md) § Flash
messages.

### `dark-mode.js`

Colour-scheme toggle (`[data-theme-toggle]`), persisting the choice in
`localStorage` under `co-color-scheme`. `base.html` re-reads that key in a
blocking inline script before the stylesheet paints, to prevent FOUC.

### `htmx-errors.js`

Makes failed htmx requests visible (archiver#178). htmx refuses to swap a
non-2xx response, so without this a failure is indistinguishable from a click
that never happened.

**Listens for:**
- `htmx:beforeSwap` - on a failed response, either swaps the server's error page
  in (boosted/full-page request: sets `detail.shouldSwap = true` and
  `detail.isError = false`) or, for a partial, leaves the swap refused and
  raises an `error` toast through `flash.js`.
- `htmx:sendError`, `htmx:timeout` - no response arrived, so
  `htmx:responseError` never fires; both toast.

**Reads:** the response's `HX-Trigger` header. A dashboard error carries
`showFlash`, which htmx raises before `beforeSwap` runs, so the listener stays
silent rather than double-reporting; a failure carrying no flash gets a
status-code toast rather than silence.

**Defers by one task before toasting.** htmx runs extension `onEvent` hooks
after DOM listeners, so at listener time the `response-targets` extension has
not yet decided whether an `hx-target-422` claims this failure. The deferred
check reads `detail.shouldSwap`: set means the error is already going somewhere
visible, and toasting would report it twice.

The server half - which paths render HTML, and why `_error.html` does not extend
`base.html` - is in [UI.md](UI.md) § Failures are surfaced, not swallowed.
