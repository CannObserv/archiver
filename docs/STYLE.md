# Archiver Dashboard - Style Reference

**Authoritative reference for CSS design tokens, component classes, theming, naming conventions, and accessibility requirements.**

> **AGENTS.md enforcement:** This file must be updated in the same commit as any change to `dashboard.css`, a Jinja2 template, or a new route that introduces new UI patterns.

---

## Theming

Three-layer system:
1. `:root { ... }` - light-mode defaults.
2. `@media (prefers-color-scheme: dark) { :root { ... } }` - OS preference fallback (no JS required).
3. `html.dark { ... }` / `html.light { ... }` - explicit user choice (wins by specificity).

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
| `--font-size-2xs` - `--font-size-2xl` | 0.65 rem - 1.5 rem |
| `--font-weight-normal/medium/bold` | 400 / 500 / 700 |
| `--line-height-tight/normal/loose` | 1.25 / 1.5 / 1.75 |

### Spacing tokens

4 px base scale: `--space-1` (0.25 rem) through `--space-16` (4 rem).

### Other tokens

`--radius-sm/md/lg/xl/pill`, `--shadow-sm/md/lg`, `--sidebar-width` (14 rem), `--topbar-height` (3.5 rem), `--transition-fast` (150 ms ease).

---

## Component Classes

### Layout
- `.admin-layout` - flex wrapper; use inside `<body>` with `padding-top: var(--topbar-height)`.
- `.topbar` - fixed top bar; contains `.topbar__brand` and `.topbar__actions`.
- `.sidebar` - fixed left sidebar; contains `.sidebar__nav`, `.sidebar__link`, `.sidebar__section-label`.
- `.main-content` - right content area with `margin-left: var(--sidebar-width)`.

### Buttons
- `.btn` - base; always pair with a modifier.
- `.btn--primary` - brand filled.
- `.btn--secondary` - outline (surface bg + border). Use for low-emphasis in-page actions that still need to read as buttons (e.g. Copy, Swap Primary, Begin Watching, Check now, Pause/Resume, Re-sync); pair with `.btn--sm` for compact contexts.
- `.btn--danger` - destructive action.
- `.btn--ghost` - transparent, borderless, no hover chrome beyond a faint fill. Reserved for the brand-colored **topbar** (Sign out, theme toggle), where `.topbar .btn--ghost` renders `--color-text-on-brand` (white). On page surfaces it defaults to `--color-text` but reads as plain text - prefer `.btn--secondary` for actions that should look clickable.
- `.btn--active` - brand-subtle background with brand text; use for the currently-selected state of a toggle button group (e.g. sort mode buttons in `sortableChips`).
- `.btn--sm` - compact size.
- Minimum touch target: 44 × 44 px (enforced by `min-height: 44px`).

### Badges & Status
- `.badge`, `.badge--primary/success/warning/danger/info/neutral/muted` - small inline label. `primary` is brand-subtle bg + brand text (use for the domain badge / brand-tagged labels). `neutral` and `muted` are synonyms (same visual - surface-alt bg, muted text); prefer `muted` for "not configured / disabled" states. `.badge` sets `text-decoration:none` so badges used as `<a>` links don't render underlined.
- `.badge--sm` - extra-compact size (use in tight contexts like tab count indicators).
- `.status-pill--cached/expired/missing` - SourceRevision cache state.

### Alerts & Flash
- `.alert`, `.alert--success/warning/danger/info` - static inline alerts.
- `.flash`, `.flash--success/warning/error/info` - toast notifications injected by `flash.js` into the `#flash-region` overlay. Server sends `HX-Trigger: {"showFlash": {"level": "success", "body": "..."}}`. `#flash-region` is `position: fixed` (top-right on desktop, full-width top on ≤640px), `z-index: 1000` - anchored to the viewport so toasts stay visible at any scroll position (archiver#65). `success`/`info` auto-dismiss after 6 s; `error`/`warning` persist until dismissed. Capped at 4 visible slots; on overflow a transient still flashes as a single lane and persistent excess collapses behind a `+N more` counter (archiver#73 - see `docs/UI.md` "Flash messages").
- `.flash__more` - the `+N more` overflow counter button occupying the 4th slot when more than four persistent toasts stack; dashed-border, surface-alt pill. Click/Enter expands the overlay to reveal all (no re-collapse). Announcement is carried by the visually-hidden `#flash-announcer-assertive` / `#flash-announcer-polite` live regions (`.sr-only`), not the visible toasts.

### Data display
- `.data-table` - standard table; applies to `<table>`. Carries `margin-bottom` so it never butts against what follows (#176). It is the *only* source of that gap where two tables stack on one screen (domain detail), and it standardises three others: the registration button row, the InfoItem swap-primary panel, and `.pagination`, whose six inline `margin-top:var(--space-3)` overrides were removed once this rule made them redundant. A table that is the last child of a `<section>` with its own bottom margin is unaffected - the margins collapse. Spacing **above** a `.section-heading` or a `.pagination` therefore comes from the preceding element's bottom margin or from the class itself, never an inline `margin-top` on the component: such an override is either a no-op that collapses against that margin, or a sign the preceding element is missing one and the fix belongs here in the stylesheet. `tests/dashboard/test_template_style_rules.py` enforces it for both.
- `.entity-card`, `.entity-card__header`, `.entity-card__title`, `.entity-card__meta`, `.entity-card__actions`.
- `.eyebrow` - small uppercase kicker label above an `.entity-card__title` (e.g. the entity kind). Non-interactive; distinct from a breadcrumb.
- `.entity-section`, `.entity-section__header`, `.entity-section__title`. `.entity-section__title` is the `<h1>` page title inside an `.entity-section__header`; section-level `<h2>`s use `.section-heading` below.
- `.section-heading` - related-collection section heading on a detail screen (`<h2>Revision History (12)</h2>`): bottom rule + spacing. Use for a plain heading-over-a-table; use `.entity-section__header` instead when the header needs a flex action slot. Replaced five verbatim inline-style copies (archiver#82). Applied to a bare `<h2>` - do **not** combine with `.entity-section__title`, which is for `<h1>` page titles inside an `.entity-section__header`; base `h2` already supplies the same size and weight, and combining the two made the rendered margin depend on stylesheet source order.
- `.detail-grid`, `.detail-grid__item`, `.detail-grid__label`, `.detail-grid__value`. `.detail-grid__item--full` spans every grid column (`grid-column: 1 / -1`) so long values (fingerprints, URLs) extend horizontally at wide viewports instead of cramping into one track.
- `.detail-row` - an **authored** row of the same `.detail-grid__item` cells, where `.detail-grid` is an auto-filled one: the author picks which fields share a row (#181). Steps **3 -> 2 -> 1** columns on the width the row *has*, via `repeat(auto-fit, minmax(min(100%, var(--detail-row-min)), 1fr))` - never viewport media queries, which cannot see the fixed sidebar. `--detail-row-min` (default `14rem`) is the column floor, overridable on the container. Two rules for reuse: `min(100%, …)` is what makes the last step a single column rather than an overflow, and **rows sharing a container must be handed the same width** - `auto-fit` counts columns from that width, so padding one row and not its sibling makes them disagree.
- `.table-scroll` - the wrapper **every** `.data-table` sits in (#182): a table will not shrink below its min-content width, so an unwrapped one widens whatever contains it. **It carries the bottom margin, not the table** - `overflow-x` makes it a formatting context, so a margin on the table is trapped inside and stacks with the next element's instead of collapsing against it. Scrollable means keyboard-scrollable, hence `tabindex="0"` + `role="region"` + `aria-label` (the table's own name; the doubled announcement buys "scrollable container" and "table" being said separately), static rather than script-applied so it survives JS being off. Tripwires fail if table 19 arrives without a wrapper, or with a margin of its own.
- `.notes-heading`, `.notes-row`, `.notes-row__actions`, `.notes-readout` - the read-only-first notes row inside a detail header panel (domain detail, #176). `.notes-heading` is the row's own `<h2>` label: a panel-internal section heading, quieter than `.section-heading`, and its own rule rather than borrowing `.detail-grid__label` from the grid above it. `.notes-row` is a wrapping flex row: the readout (or, in edit mode, the `.form-textarea`) takes the free width, `.notes-row__actions` holds the inline Edit / Cancel+Save buttons at intrinsic width and drops below on narrow viewports. `.notes-readout` matches the `.form-textarea` it swaps with on border, radius, and padding so the edges hold still; what stops the panel *resizing* on the flip is the shared `min-height` on `.notes-row > *` - the readout would otherwise sit at its content height against the textarea's floor. `white-space: pre-wrap` preserves author line breaks.
- `.field-row-group`, `.field-row__label`, `.field-row`, `.field-row__actions`, `.field-row__readout` - the same read-only-first shape at **single-line** height, generalised from the notes row for the Watcher panel's editable fields (#181). `.field-row-group` stacks the label above the row so the label does not move on the flip; `.field-row__label` is the quiet uppercase treatment `.notes-heading` uses, without being an `<h2>`. `.field-row__readout` matches `.form-select--sm` on border, radius, padding and font-size, and both share a `min-height` for the reason `.notes-row` does. Use this family for a control that fits on one line and `.notes-row` for a textarea.
- `.watch-panel`, `.watch-panel__header`, `.watch-panel__fields` - the InfoItem Watcher panel ([INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md)). The header anchors its one control to the top right inside corner **out of flow**, so it costs no vertical space; the price is `.watch-panel__header ~ .detail-row`, a `6rem` gutter on **every** row (`~` not `+`, per the width rule above) rather than on the one cell under the button, which changes with the column count.

### Forms
- `.form-group`, `.form-label`, `.form-input`, `.form-select`, `.form-textarea`, `.form-hint`, `.form-error`. **There is no `.input` class** - `<input>`/`<textarea>`/`<select>` must use `.form-input`/`.form-textarea`/`.form-select` or they render unstyled (browser default).
- `.form-input--error` / `.form-select--error` / `.form-textarea--error` - red border on invalid field.
- `.form-input--inline` - compact width-auto variant for in-table rename inputs.
- `.form-select--sm` - inline-scale `<select>` for action rows: `width:auto` and sized to `.btn--sm` (32px, `--font-size-xs`) so a select and a button share a baseline. The base `.form-select` is a full-width 44px block built for stacked forms and looks wrong beside a small button (added for the InfoItem cadence editor, archiver#158).
- Use `.form-select` (not `.form-input`) on `<select>` elements so the select-specific focus ring and `.form-select--error` variant apply. Optional advanced/secondary form controls may be nested in a native `<details>`/`<summary>` disclosure (e.g. registration Step 3 "Watcher settings (advanced)") - no dedicated class; the `<summary>` carries `.text-sm`.
- Checkboxes have no dedicated class: wrap the `<input type="checkbox">` and its caption in a single `<label class="form-label">` set to `display:flex;align-items:center;gap:var(--space-2)` so the box and text sit on one clickable line (e.g. registration Step 3 "Watch active immediately").
- `.filter-card` - for single-row action/filter bars: heading + inputs in a horizontal flex row (`align-items: flex-end`). Use for simple one-input + submit patterns. For multi-field stacked forms, add `.filter-card--stacked`.
- `.filter-card--stacked` - modifier; changes `filter-card` to a vertical column (`flex-direction: column; align-items: stretch`). Use when the card contains a heading above multiple stacked form fields.

### Navigation
- `.pagination`, `.pagination__btn`. Carries its own `margin-top`; templates must not add an inline one (see `.data-table` above).
- `.tabs`, `.tabs__list`, `.tabs__btn`, `.tabs__btn--active`, `.tabs__panel`.
- `.typeahead-results`, `.typeahead-results__item`, `.typeahead-results__item--focused`.

### Modals
- `.modal-backdrop` - fixed overlay.
- `.modal`, `.modal__header`, `.modal__title`, `.modal__close`, `.modal__body`, `.modal__footer`.

### Shared Jinja macros (`templates/_macros.html`)
- Import per-template: `{% from "_macros.html" import copyable, open_button %}` (works from any subdir - Jinja resolves import paths from the loader root).
- `copyable(value)` - copy-to-clipboard affordance: a monospace value plus a `.btn--secondary .btn--sm` "Copy" button ("Copy"→"Copied ✓" for 1.5 s). The value is bound via `|tojson` to an Alpine data prop and copied through it (`writeText(v)`), never spliced into the handler's JS source, so arbitrary DB strings cannot break out of the JS-string context. Used for ULIDs and fingerprints on detail screens (InfoItem, Source Revision).
- `open_button(url, label="Open")` - scheme-guarded external-open affordance rendered as a link styled as a small secondary button (`.btn .btn--secondary .btn--sm`), modeled on the "Copy" affordance so opening a target URL reads as a distinct action, cleanly separated from the displayed value. Always `target=_blank rel=noopener noreferrer`; anchor (not `<button>`) because it is navigation. **Only renders for `http(s)` URLs** - non-http values (provider-native `gs://`/`s3://`, or a `javascript:` injection attempt from an unvalidated field like RepSpec `public_url`) render nothing, so the macro is safe to call on any string. Used site-wide for external URLs: InfoItem/domain/revision source URLs, RepSpec `public_url`, and `content_cache_uri`. (Section-header deeplinks like the InfoItem "Watcher ↗" `<h2>` are intentionally not buttons - they are heading affordances, not value-adjacent ones.)

### Code
- `.code-block` - monospace card for JSON display. Also used as `class="form-textarea code-block"` on `<textarea>` elements that contain JSON (e.g. `source_specs` array editor on InfoSource create/edit forms) to give the input a monospace font matching the display block.

### Danger zone
- `.danger-zone`, `.danger-zone__title` - destructive-action section at bottom of detail pages.

### Error page
- `.error-page`, `.error-page__heading`, `.error-page__actions` - the dashboard error page (`templates/_error.html` and its `_error_body.html` block, archiver#178). Centred and capped at `40rem` because it renders **without** the shell: the standalone page has no sidebar to sit in, and the htmx fragment replaces the one it had. It owns its own `margin`/`padding` for the same reason - nothing above it in either context supplies spacing. The incident id on a 5xx uses `.text-mono`.

### Utilities
- `.text-muted`, `.text-sm`, `.text-xs`, `.text-mono`, `.truncate`, `.sr-only`.
- `.text-danger` - `color: var(--color-danger)`. Use on inline error messages and destructive-action labels.
- `.text-success` - `color: var(--color-success)`. Use on inline confirmation/status messages.
- `.skip-link` - top-of-page accessibility link.

### Alpine.js integration
- `[x-cloak] { display: none !important; }` - prevents FOUC on elements controlled by `x-show`. Add `x-cloak` to any element that should be hidden before Alpine initialises (e.g. collapsible panels). Do **not** add `x-cloak` to elements that should start visible.
- For elements that are conditionally hidden by `x-show` but start hidden, add `style="display:none;"` as an initial-state hint instead of `x-cloak`; Alpine's `x-show` manages their display after initialisation. This preserves the CSS class's `display` value (e.g. `display:flex` on `.entity-card__actions`) when the element is shown.
- **Inline toggle panel pattern** - when a section needs a togglable sub-panel (e.g. Swap primary source), wrap both the trigger and the panel in `x-data="{open:false}"`. The trigger button uses `@click="open=!open"` and `x-text="open ? 'Cancel' : 'Open'"`. The panel uses `x-show="open" x-cloak`. No named Alpine component needed for single-use panels.

### HTMX and Alpine patterns

Moved to [UI.md](UI.md) § **HTMX Patterns** (#182 curation) - the async partial,
inline form error, action-swaps-card and JSON data island patterns are HTMX and
Alpine *mechanics*, with no CSS in them, and UI.md is the doc whose stated scope
is the dashboard's shared mechanics. This file keeps the classes they toggle.

### Alpine component catalogue (`main.js`)

All components are registered via `window.Alpine.data('name', factory)` inside a `alpine:init` listener before `Alpine.start()`. Do **not** add inline `x-data="{ ... }"` blobs for logic that should be reusable or testable.

The per-component index moved to [COMPONENTS.md](COMPONENTS.md) § Catalogue index, beside the full entries it summarised - two lists of the same components drift, and the CSS classes they toggle are what this file is for.

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

- Async content sections (HTMX async partial pattern): `aria-live="polite" aria-atomic="false"`.
- Inline form error targets (HTMX inline form error pattern): `aria-live="polite" aria-atomic="true"`.
- Toast announcers (archiver#73): `#flash-announcer-assertive` (errors) / `#flash-announcer-polite` (other levels), both `.sr-only`. `flash.js` writes every message here so announcement is decoupled from the visible `#flash-region` cap; visible toasts carry no live role.
- Active sidebar link: `aria-current="page"`.
- Focus rings: `:focus-visible` with 2 px brand-colour outline.
- Minimum touch targets: 44 × 44 px.
- Skip link: `.skip-link` at top of every page.
- Modals: focus trapped on open; restored on close.
- `@media (prefers-reduced-motion: reduce)` collapses all transitions to 0.01 ms.
