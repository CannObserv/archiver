# Archiver Dashboard — Style Reference

**Authoritative reference for CSS design tokens, component classes, theming, naming conventions, and accessibility requirements.**

> **AGENTS.md enforcement:** This file must be updated in the same commit as any change to `dashboard.css`, a Jinja2 template, or a new route that introduces new UI patterns.

---

## Theming

Three-layer system:
1. `:root { ... }` — light-mode defaults.
2. `@media (prefers-color-scheme: dark) { :root { ... } }` — OS preference fallback (no JS required).
3. `html.dark { ... }` / `html.light { ... }` — explicit user choice (wins by specificity).

**FOUC prevention:** Inline `<script>` in `<head>` **before** `<link rel="stylesheet">` reads `localStorage.getItem('co-color-scheme')` and adds `.dark`/`.light` to `<html>` before first paint.

**Tri-toggle** cycles: `system → light → dark → system`. `localStorage` key: `co-color-scheme`. `dark-mode.js` updates the button's `textContent` and `aria-label` on every toggle and on initial load. Icons: `◐` system, `☀` light, `☾` dark. `aria-label` values: `"Colour scheme: system"` / `"Colour scheme: light"` / `"Colour scheme: dark"`.

**Brand colour:** `--color-brand: #6d4488` (light) / `#a78bc4` (dark).

---

## Design Tokens

All tokens are CSS custom properties on `:root`. The canonical source is `src/dashboard/static/dashboard.css`.

### Colour tokens

| Token | Light | Dark | Purpose |
|---|---|---|---|
| `--color-brand` | `#6d4488` | `#a78bc4` | Primary brand / interactive |
| `--color-brand-dark` | `#5a3671` | `#c4a8db` | Hover state for brand |
| `--color-brand-light` | `#8a5eaa` | `#8a6aaa` | Active/focus accents |
| `--color-brand-subtle` | `#f2edf7` | `#2d1f3d` | Low-contrast brand bg |
| `--color-bg` | `#f8f9fa` | `#121212` | Page background |
| `--color-surface` | `#ffffff` | `#1e1e1e` | Card / panel surface |
| `--color-surface-alt` | `#f1f3f5` | `#2a2a2a` | Alternate surface (table rows, sidebar) |
| `--color-border` | `#dee2e6` | `#3d3d3d` | Default border |
| `--color-border-light` | `#e9ecef` | `#2d2d2d` | Subtle border |
| `--color-text` | `#212529` | `#e9ecef` | Body text |
| `--color-text-muted` | `#6c757d` | `#adb5bd` | Secondary text |
| `--color-text-on-brand` | `#ffffff` | `#ffffff` | Text on brand-coloured surfaces |

### Typography tokens

| Token | Value |
|---|---|
| `--font-sans` | System UI stack |
| `--font-mono` | SFMono / Consolas stack |
| `--font-size-2xs` – `--font-size-2xl` | 0.65 rem – 1.5 rem |
| `--font-weight-normal/medium/bold` | 400 / 500 / 700 |
| `--line-height-tight/normal/loose` | 1.25 / 1.5 / 1.75 |

### Spacing tokens

4 px base scale: `--space-1` (0.25 rem) through `--space-16` (4 rem).

### Other tokens

`--radius-sm/md/lg/xl/pill`, `--shadow-sm/md/lg`, `--sidebar-width` (14 rem), `--topbar-height` (3.5 rem), `--transition-fast` (150 ms ease).

---

## Component Classes

### Layout
- `.admin-layout` — flex wrapper; use inside `<body>` with `padding-top: var(--topbar-height)`.
- `.topbar` — fixed top bar; contains `.topbar__brand` and `.topbar__actions`.
- `.sidebar` — fixed left sidebar; contains `.sidebar__nav`, `.sidebar__link`, `.sidebar__section-label`.
- `.main-content` — right content area with `margin-left: var(--sidebar-width)`.

### Buttons
- `.btn` — base; always pair with a modifier.
- `.btn--primary` — brand filled.
- `.btn--secondary` — outline.
- `.btn--danger` — destructive action.
- `.btn--ghost` — transparent; **topbar use only** (text is `--color-text-on-brand` / white — invisible on light page backgrounds).
- `.btn--active` — brand-subtle background with brand text; use for the currently-selected state of a toggle button group (e.g. sort mode buttons in `sortableChips`).
- `.btn--sm` — compact size.
- Minimum touch target: 44 × 44 px (enforced by `min-height: 44px`).

### Badges & Status
- `.badge`, `.badge--success/warning/danger/info/neutral` — small inline label.
- `.badge--sm` — extra-compact size (use in tight contexts like tab count indicators).
- `.status-pill--cached/expired/missing` — SourceRevision cache state.

### Alerts & Flash
- `.alert`, `.alert--success/warning/danger/info` — static inline alerts.
- `.flash`, `.flash--success/warning/error/info` — ephemeral notifications injected by `flash.js`. Server sends `HX-Trigger: {"showFlash": {"level": "success", "body": "..."}}`.

### Data display
- `.data-table` — standard table; applies to `<table>`.
- `.entity-card`, `.entity-card__header`, `.entity-card__title`, `.entity-card__meta`, `.entity-card__actions`.
- `.entity-section`, `.entity-section__header`, `.entity-section__title`.
- `.detail-grid`, `.detail-grid__item`, `.detail-grid__label`, `.detail-grid__value`.

### Forms
- `.form-group`, `.form-label`, `.form-input`, `.form-select`, `.form-textarea`, `.form-hint`, `.form-error`.
- `.form-input--error` / `.form-select--error` / `.form-textarea--error` — red border on invalid field.
- `.form-input--inline` — compact width-auto variant for in-table rename inputs.
- `.filter-card` — for single-row action/filter bars: heading + inputs in a horizontal flex row (`align-items: flex-end`). Use for simple one-input + submit patterns. For multi-field stacked forms, add `.filter-card--stacked`.
- `.filter-card--stacked` — modifier; changes `filter-card` to a vertical column (`flex-direction: column; align-items: stretch`). Use when the card contains a heading above multiple stacked form fields.

### Navigation
- `.pagination`, `.pagination__btn`.
- `.tabs`, `.tabs__list`, `.tabs__btn`, `.tabs__btn--active`, `.tabs__panel`.
- `.typeahead-results`, `.typeahead-results__item`, `.typeahead-results__item--focused`.

### Modals
- `.modal-backdrop` — fixed overlay.
- `.modal`, `.modal__header`, `.modal__title`, `.modal__close`, `.modal__body`, `.modal__footer`.

### Code
- `.code-block` — monospace card for JSON display. Also used as `class="form-textarea code-block"` on `<textarea>` elements that contain JSON (e.g. `source_specs` array editor on InfoSource create/edit forms) to give the input a monospace font matching the display block.

### Danger zone
- `.danger-zone`, `.danger-zone__title` — destructive-action section at bottom of detail pages.

### Utilities
- `.text-muted`, `.text-sm`, `.text-xs`, `.text-mono`, `.truncate`, `.sr-only`.
- `.text-danger` — `color: var(--color-danger)`. Use on inline error messages and destructive-action labels.
- `.text-success` — `color: var(--color-success)`. Use on inline confirmation/status messages.
- `.skip-link` — top-of-page accessibility link.

### Alpine.js integration
- `[x-cloak] { display: none !important; }` — prevents FOUC on elements controlled by `x-show`. Add `x-cloak` to any element that should be hidden before Alpine initialises (e.g. collapsible panels). Do **not** add `x-cloak` to elements that should start visible.
- For elements that are conditionally hidden by `x-show` but start hidden, add `style="display:none;"` as an initial-state hint instead of `x-cloak`; Alpine's `x-show` manages their display after initialisation. This preserves the CSS class's `display` value (e.g. `display:flex` on `.entity-card__actions`) when the element is shown.
- **Inline toggle panel pattern** — when a section needs a togglable sub-panel (e.g. Swap primary source), wrap both the trigger and the panel in `x-data="{open:false}"`. The trigger button uses `@click="open=!open"` and `x-text="open ? 'Cancel' : 'Open'"`. The panel uses `x-show="open" x-cloak`. No named Alpine component needed for single-use panels.

### HTMX async partial pattern

For non-blocking page sections that call a slow or potentially unavailable service, load them after the page renders:

```html
<div id="target-id"
     hx-get="/dashboard/path/to/partial"
     hx-trigger="load"
     hx-swap="outerHTML"
     aria-live="polite" aria-atomic="false">
  <p class="text-muted text-small">Loading…</p>
</div>
```

Rules:
- `hx-trigger="load"` fires the request immediately after the page renders (no user interaction needed).
- `hx-swap="outerHTML"` replaces the entire placeholder div. The server-rendered partial **must** include the same `id` as the placeholder so subsequent re-renders can re-target it.
- `aria-live="polite" aria-atomic="false"` is required on every HTMX swap target (see Accessibility section).
- The placeholder content degrades gracefully if JS is disabled or the request fails.
- Use this pattern for sections that depend on a sibling service (Watcher, Replicator) so that service outages do not block the dashboard page load.

### JSON data island pattern

When an Alpine component needs server-rendered data at initialisation, place the data in a `<script type="application/json">` child element rather than embedding JSON inside the `x-data` attribute. Jinja2's `tojson` filter does **not** escape `"`, so JSON in a double-quoted attribute is silently truncated by the HTML parser; single-quoted attributes work but are fragile to copy. The data island avoids both problems:

```html
<div x-data="myComponent()">
  <script type="application/json">{{ my_data | tojson }}</script>
  ...
</div>
```

In `init()`, read it with:
```javascript
var el = this.$el.querySelector('script[type="application/json"]');
var data = el ? JSON.parse(el.textContent || "[]") : [];
```

Notes: `tojson` escapes `<` → `<`, so `</script>` inside JSON values cannot close the tag early. Browsers do not execute `<script type="application/json">`. Alpine and HTMX ignore it. Apply this pattern to any Alpine component that needs a non-trivial server-rendered data structure at startup.

### Alpine component catalogue (`main.js`)

All components are registered via `window.Alpine.data('name', factory)` inside a `alpine:init` listener before `Alpine.start()`. Do **not** add inline `x-data="{ ... }"` blobs for logic that should be reusable or testable.

| Component | File | Description |
|---|---|---|
| `sortableChips` | `main.js` | Chip strip for selector/rep-field suggestions with client-side sort. Uses JSON data island: `x-data="sortableChips('frequency')"` with `<script type="application/json">{{ chips \| tojson }}</script>` inside. Optional `value` field on each chip overrides the dispatch payload. Clicking dispatches `chip-insert` window event; caller listens with `@chip-insert.window`. Full docs in `docs/UI.md`. |
| `repFieldsEditor` | `main.js` | Wrapper for the rep_fields textarea + suggestion strip. Listens for `chip-insert` window events and merges the key into the existing JSON object. Usage: `x-data="repFieldsEditor()" @chip-insert.window="insertKey($event.detail.label)"`. Full docs in `docs/UI.md`. |
| `repSpecEditor` | `main.js` | JSON editor for RepSpec documents on the create form. |
| `apiKeyReveal` | `main.js` | One-time raw key display after API key creation. |
| `registerWizard` | `register/index.html` | 4-step registration wizard (client-side only; inline script in the template). |

---

## Display Names

Dashboard UI uses fully qualified domain names. Code, API, and docs use terse forms.

| Terse (code/API) | Display (UI) |
|---|---|
| InfoItem | Information Item |
| InfoSource | Information Source |
| RepSpec | Replication Specification |
| SourceRevision | Information Source Revision |

---

## Accessibility

Target: **WCAG 2.1 AA**.

- All HTMX swap targets: `aria-live="polite" aria-atomic="false"`.
- Active sidebar link: `aria-current="page"`.
- Focus rings: `:focus-visible` with 2 px brand-colour outline.
- Minimum touch targets: 44 × 44 px.
- Skip link: `.skip-link` at top of every page.
- Modals: focus trapped on open; restored on close.
- `@media (prefers-reduced-motion: reduce)` collapses all transitions to 0.01 ms.
