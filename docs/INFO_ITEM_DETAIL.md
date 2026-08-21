# Dashboard - the Information Item detail screen

**The anatomy of `/dashboard/info-items/{id}`: its five sections, its partial
templates, and their swap targets.** Split out of [PAGES.md](PAGES.md) when that
file passed its context budget at 12.8k tokens - this screen alone was half of
it, and nobody working on Domains or RepSpecs needs to load it. PAGES.md keeps
the page and route inventory, including every route listed here; this document
is what the screen *is*.

Sibling docs: [UI.md](UI.md) shared mechanics · [COMPONENTS.md](COMPONENTS.md)
Alpine catalogue · [STYLE.md](STYLE.md) tokens and component classes.

---

## The five sections

**GET `/dashboard/info-items/{id}`** - 5-section vertical-scroll hub page (`info_items/detail.html`):

1. **Overview** - `.entity-card` header (canonical detail-screen pattern, #81): `.eyebrow` "Information Item" kicker → `<h1 class="entity-card__title" id="info-item-heading" tabindex="-1">` name → copyable ULID (shared `copyable` macro) → domain badge linking to `/dashboard/domains/{name}`, or a muted "No primary source" when unbound; `.detail-grid` with description, owner (if set), created_at. Watcher status is deliberately absent here - the status and its controls live in section 3 (#62).

2. **Information Sources** - `x-data="{swapOpen:false}"` wrapper around a `data-table` of active `info_item_sources` bindings (columns: URL, Domain, Spec, Bound, Actions); the first row carries a brand left-border marking it primary. The **Spec** column summarises the InfoSource's primary `source_specs` entry (`_format_spec_summary`, e.g. `css · 2 specs`) out of `spec_summary_by_source_id`, computed by the detail route - the spec belongs here, not in the Watcher section (#62). The Actions cell on the primary row holds a "Swap primary" / "Cancel" toggle (`@click="swapOpen=!swapOpen"`) that reveals `info_items/_swap_primary.html` inside `<div x-show="swapOpen" x-cloak>`; with no active bindings that panel (`id="swap-panel"`) renders unconditionally, titled "Add primary source". Its "author new source" form posts with `hx-target-422="#swap-error"` and succeeds with 204 + `HX-Redirect`; the "bind by ID" `<details>` sub-form does the same against `#swap-by-id-error`.

3. **Watcher** - a plain `<h2>` heading. It used to be a deeplink ("Watcher ↗") built from `WATCHER_PUBLIC_BASE_URL` + `item.watcher_item_id` (#62); archiver#142 retired it, because announcements never hand Watcher's primary key back and Watcher exposes no lookup by `info_item_id`, so there is no per-item URL left to build. Body: `<div id="watcher-section">` loaded async via `hx-trigger="load"` + `hx-get="…/watcher-section"` + `hx-swap="outerHTML"`; the root element also carries `hx-trigger="watcherUpdated from:body"` so the panel self-refreshes whenever an action fires that event. Template `info_items/_watcher_section.html`.

   **The panel renders from local state with zero SDK calls (archiver#151):** the `watch_status` cache (Archiver's tail of `info.watch-status`), `item.watch_spec` / `watch_active` / generations, and the latest `source_revisions.captured_at` of the active binding, composed by `src/dashboard/watch_panel.py` (`build_watch_context`). **Announceability decides the state *before* the cache row is consulted** - an active binding whose source carries non-empty `source_specs`, passed into `build_watch_context` as `is_announceable`. A status row can outlive the fact it describes (an item dropped from the announced set is tombstoned to Watcher, but the cached row lingers until the status stream catches up, or forever if it never does), and reading the row first would render `watching` for an item nothing is watching. archiver#142 moved this off `watcher_item_id`: announcements never populate that column, so the old key would have reported `not_watching` for *every* item - an inversion rather than a failure. Four states: `not_watching` (outside the announced set - no button, since watching is a consequence rather than an action; the copy names what closes the gap: "bind an active source with extraction specs"), **`no_status`** ("NO STATUS YET" - announced but Watcher has never reported; distinct from paused and from healthy, and what every item shows until watcher#264 publishes), `watching`, and `degraded` (only an *action* failure renders it - the local read path cannot degrade). `no_status` renders the status row alone - every provenance field is empty there by construction - and carries **no pause toggle**: `applied_active` is None, so "Pause" and "Resume" would both be guesses at the button's own effect.

   **The `watching` body is three zones (archiver#181).** A `.watch-panel__header` anchoring the pause/resume toggle to the panel's top right inside corner, out of flow so it costs no vertical space; then two **authored** `.detail-row` grids, stepping 3 -> 2 -> 1 columns as the viewport narrows; then `.watch-panel__fields`, the editable fields one per row. The rows are authored rather than auto-filled because the grouping is the point - an operator asks "healthy, how often, when next" before asking anything else:

   | Row | Fields |
   |---|---|
   | 1 - status at a glance | Health, Cadence, Next due |
   | 2 - provenance | Last attempted, Last observed, Announcement |

   Every cell renders unconditionally, falling back to a muted `-`: an authored row that reflows as fields come and go is an auto-filled grid with extra steps. **Health** is the health badge (open vocabulary - `"ok"` is the only healthy value; anything else, known or unknown, renders verbatim on `badge--danger`) plus the Paused and pending badges below. **Cadence** leads with the applied `applied_interval` and falls back to the announced one, carrying an "announced ..." `badge--danger` when they diverge; it answers *how often it is actually running*, where the editable row below answers *what was asked for*, which is why both exist. **Next due** is derived (`last_attempt_at` + effective interval), overdue in `text-danger`. **Announcement** is the drift line - "gen N announced / M applied" with a checkmark when in sync, a `drift, 40m`-style badge when applied lags (danger past the 15-minute threshold, aged from `info_items.announced_at`), or an "ahead of registry" badge when applied *exceeds* announced, which is an anomaly rather than health.

   **`Last changed` left the panel in archiver#181.** The two authored rows hold six fields and there is no seventh slot; Revision History further down this same screen already carries every `captured_at`, so the value left the summary rather than the screen.

   A **Paused** badge shows when `applied_active` is false, and a "Pause/Resume pending" badge when the item's desired `watch_active` differs from what Watcher reports applied.

   **The SDK actions are gone (archiver#142).** "Begin Watching", "Check now", and "Re-sync" each rode an outbound HTTP call, along with the 409-adoption recovery and the stale-link reconcile behind them. Nothing replaces them individually: reconciliation is level-triggered off `info.registry`, so there is no per-item push to retry, no remote id to adopt or clear, and no provisioning gesture to repeat. While paused the toggle reads "Resume".

   **The control plane is local as of archiver#158.** Pause/resume and cadence are `UPDATE`s on `info_items` plus an `info.registry` announcement - no SDK call - and Watcher reconciles them off the stream. Two consequences on this panel. First, the **cadence editor** (`info_items/_cadence_editor.html`) posts to `watch-cadence`; archiver#181 made it a **view/edit row** on the Domains pattern (#176) - a `.field-row__readout` of the announced cadence *label* beside a row-level Edit, flipping to the `form-select--sm` of `src/dashboard/cadence.py`'s vocabulary beside Cancel + Save, toggled by the generic `editableField` Alpine component (COMPONENTS.md). It was a bare select plus a "Set" button, the one editable field on the dashboard that committed without an explicit edit gesture. Unlike the notes row it **does** carry the inline `display:none` FOUC hint, because there is no no-JS save path to strand: `watch-cadence` answers with a bare fragment rather than a 303, and the form only ever posted over HTMX. The editor did not exist at all before #158, because post-registration cadence was display-only while the live value was Watcher's. It renders in **both** announced states - `watching` and `no_status` - because a freshly registered item sits in `no_status` until Watcher's first status frame, which is exactly when an operator wants to revise the cadence they just picked. `not_watching` has no announceable source by definition and `degraded` shows an error, so neither carries it. Second, **both policy affordances - pause/resume and the cadence editor - are gated on `has_active_source`**: an active binding whose source has non-empty `source_specs`, the same announceability rule `_collect_full_set` and the announce service use. Mutating policy on an item that cannot announce live emits a *tombstone* and burns a generation, which then reads as drift on this very panel for an item where nothing is wrong. Since archiver#142 that same value is the panel's state key, so the gate and the state agree by construction rather than by coincidence. Third, the **archived-item guard is gone**. Archiver models no per-item archived state (only `domains.archived_at`), and the design settled that a Watcher-local pause is reverted by reconciliation - archive is mechanism, not policy, like `domain_suspended`. An archived item's toggle now succeeds locally and the divergence surfaces as `applied_active != active` on the return leg, which the panel already renders, rather than as a silent 409.

4. **Revision History** - `data-table` of the last 50 `source_revisions` captured across the item's InfoSource **bindings** - the active primary **plus** previous primaries (deactivated `info_item_sources` rows, preserved as succession history) - ordered `captured_at desc`, count in the heading. Columns: Fingerprint (linked to revision detail), Source (the InfoSource URL, linked to source detail - present because an item accumulates successive sources over its life), Captured (UTC), Cache (`.status-pill--cached/expired/missing`). The timeline is a query over bindings, **not** over the `info_item_source_revisions` pin table, which was dropped in archiver#101. The route computes `revisions` + `rev_sources_by_id`, the latter covering deactivated previous primaries that the active-only `sources_by_id` misses.

5. **Replicator** - two sub-sections:
   - *Rep Fields* - `x-data="repFieldsEditor()"` wrapper; HTMX-loaded `sortableChips` suggestions (`hx-trigger="load"`); `<textarea name="rep_fields">` with `PATCH /dashboard/info-items/{id}/rep-fields` inline save; flash target `#rep-fields-flash`.
   - *Replication Specs* - `info_items/_rep_spec_assignments.html` (wrapper `#ii-rep-spec-assignments`, heading `#ii-rep-spec-heading`): `data-table` of active `info_item_rep_specs` assignments plus an assign form (`filter-card`, `rep_spec_id` field). Rows (`_rep_spec_row.html`) carry six columns - Spec, Provider, Activated, **Replication**, Public URL, Actions. **Both** row actions - deactivate and **Replicate now** (confirm- and `hx-disabled-elt`-guarded) - re-render the whole section (table + empty state) and focus the heading, because each destroys the button that was clicked.

     **Replication** renders the `replication_state` macro over the latest `replication_commands` row for that assignment: the state badge, the producer's `reason` for a failure or Archiver's local one for a skip (`detail` on the `title`), the `command_id`, and when it closed. Skips are shown for the reason they are persisted at all - a refusal that lives only in a log line renders as "not replicated yet" forever, indistinguishable from one still in flight.

     `public_url` is **read-only** (archiver#171). #170 gave the column an automated writer, so the inline edit was a field whose value the next occasion silently clobbered; the provenance beside it is what the author actually needed.

---

## Partial templates and swap targets

Partial templates under `info_items/`:

| Template | Swap target (`outerHTML`) | States |
|---|---|---|
| `_rep_spec_row.html` | - (included only; both its actions swap `#ii-rep-spec-assignments`) | via `replication_state`: none, `requested`, `complete`, `failed`, `abandoned`, `skipped` |
| `_swap_primary.html` | `#swap-panel` | - |
| `_watcher_status.html` | `#watcher-status-strip` | `not_watching`, `no_status`, `degraded`, `watching` |
| `_watcher_section.html` | `#watcher-section` | `not_watching`, `no_status`, `degraded`, `watching` |
| `_cadence_editor.html` | - (included, `hx-swap="none"`) | view / edit (`editableField`) |

Each root element carries its own `id`, so it survives the swap that replaces it;
`_watcher_section.html`'s root additionally carries `hx-trigger="watcherUpdated
from:body"` for the event-driven auto-refresh. Both Watcher partials take the
context keys `state`, `item_id`, `watch` (the `build_watch_context` dict -
health, ages, cadence, next-due, drift), `has_active_source`, and
`error_message` (degraded only), and both render the badges and toggle
described in section 3. There is no `not_configured` state and no Watcher client
to configure: #151 made the render local, #142 removed the client outright.
`degraded` is likewise not a Watcher condition - the only path into it is a
*local* write failing, which is why its copy names the write and not the service.

`_swap_primary.html` is a full-width card - no max-width, so it spans the
bindings table - titled "Swap primary source" or "Add primary source" depending
on whether `iis_rows` is non-empty. It holds a URL input (`id="swap-url"`,
`.form-input`), a source_specs textarea (`id="swap-specs"`, `.form-textarea`), a
Preview HTMX button (`.btn--secondary`, `hx-include="#swap-url,#swap-specs"`)
targeting `#swap-preview`, the submit to `swap-primary-source` (`.btn--primary`),
and an advanced `<details>` for `swap-primary-by-id` (`.form-input` field +
`.btn--secondary` Bind button).

## Action-route contracts

Moved here from [PAGES.md](PAGES.md), which keeps the inventory line for each of
these routes. This is the behaviour behind them.

**The two Watcher action POSTs share a contract.** `toggle-watch-active` and
`watch-cadence` each re-render a Watcher partial and set `HX-Trigger:
{"watcherUpdated":{}}`. Their forms use `hx-swap="none"`, so the rendered body is
discarded and the trigger is what refreshes `#watcher-section` - swapping the
response in *and* firing the trigger would render twice. On failure each adds a
`showFlash` error to that trigger rather than 500ing (#60, #61). Each also carries
`hx-on::after-request` moving focus to `#watcher-heading` (archiver#181): the
refresh destroys the control that was clicked, and the `<h2>` is the nearest
thing that survives it, living in `detail.html` outside the swapped region. The
focus-script-in-the-response trick the domain notes row uses cannot work here -
`hx-swap="none"` discards the body a script would ride in.

**There were five.** `begin-watching`, `check-now`, and `resync-watcher` were
SDK-backed and retired with it in archiver#142, along with the stale-link
reconcile they triggered (a `WatcherNotFound` NULLed `watcher_item_id` so the
panel could re-offer "Begin Watching"). Nothing replaces them individually:
reconciliation is level-triggered off `info.registry`, so there is no per-item
push to retry, no remote id to go stale, and no provisioning gesture to repeat.
The two survivors are *local* writes
that announce and let Watcher converge; the route entries in [PAGES.md](PAGES.md) name only what each adds.

### Replication actions

**Every outcome is a 200, and every outcome flashes** via `HX-Trigger: showFlash` - issued at `success` naming the rendered destination, a recorded `skipped` row at `warning` naming its reason (it also renders as state in the Replication column), and a refusal the service will not record - `not_active`, `no_active_source`, `no_revision`, `assignment_unreachable` - at `error`. Refusals are 200s rather than 422s because htmx discards a 4xx body (see UI.md § **Inline validation errors** and the STYLE.md rule it points at). The outcome→flash translation is `src/dashboard/replication_actions.py`, shared with the RepSpec-scoped twin (PAGES.md § **Replication Specifications**).

It exists because a new assignment on *stable* content otherwise never replicates - issuance is triggered by a new revision, and a stable InfoItem may never produce one.

*(The former `PATCH .../public-url` is **retired**. `public_url` acquired an automated writer in archiver#170, so an inline edit was a field whose value the next occasion silently clobbered.)*
