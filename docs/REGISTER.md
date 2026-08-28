# Register Screen - Wizard Anatomy

**The `/dashboard/register` wizard's summary bar and its Step 3 controls.**
Needed only when working on that screen; [PAGES.md](PAGES.md) § **Registration
flow** stays the inventory line for each route, and the component state lives in
`registerWizard` ([COMPONENTS.md](COMPONENTS.md)).

**Rolling step-summary bar**: `#wizard-summary` (`role="group"`,
`aria-label="Completed steps"`), rendered between the step-indicator badges and
the form, visible from step 2 on (`x-show="step>=2"`). Completed steps show as
clickable chips (`.btn.btn--secondary.btn--sm`) that jump back to their step -
same semantics as the step-4 Edit buttons:

- **URL chip** (step ≥ 2) - the entered URL (CSS-truncated at 20rem, full value
  in `title`) plus a parenthesised domain note: `(known domain: <host>)` /
  `(new domain: <host>)` when a url-check result has landed for the current
  hostname (`domainSummary`), else just `(<host>)` (`urlHostname`).
- **Selector chip** (step ≥ 3) - `selectorSummary`, also reused for the step-4
  review Selector row.
- **Name chip** (step ≥ 4) - `itemName`.

**Step 3 (Metadata) - Watcher settings (advanced)**: a collapsed `<details>`
block exposes two controls.

A **Fetch cadence** `<select.form-select>` (`name="cadence"`,
`x-model="cadence"`, `x-ref="cadenceInput"`). Options and default are rendered
server-side from the shared cadence vocabulary (`src/dashboard/cadence.py`:
Hourly `1h` / Every 6 hours `6h` / Daily `1d` (default) / Weekly `7d`), injected
as the `cadence_labels` / `default_cadence` Jinja globals. The value is a Watcher
interval string; on submit the server writes `{"schema_version": 1, "interval":
<value>}` to `info_items.watch_spec` **only when the value is a recognised
option**, otherwise leaving the column default standing, which spells "the
consumer applies its own default" - the handler never fabricates a cadence. That
column is what the `info.registry` announcement carries, and since archiver#142
the announcement is the only path to Watcher. The
selection is sticky across validation re-renders (`cadence_value` → `selected`
attribute). Step 4 review shows the label via `cadenceLabel`. The same vocabulary
backs `_format_cadence` on the InfoItem Watcher section, so recognised cadences
display with the same friendly labels in both places.

A **Watch active immediately** checkbox (`<input type="checkbox"
id="reg-watch-active" name="watch_active" value="on"`, `x-model="watchActive"`,
`x-ref="watchActiveInput"`), checked by default. Checked → the server writes
`watch_active=True`; unchecked (the checkbox sends nothing) → `watch_active=False`,
announcing the item **paused**. Both are written before the announcement, so the
item's very first `info.registry` frame carries the policy the operator chose.
Sticky across validation re-renders (`watch_active_value` → `checked` attribute,
defaulting to checked via `|default(true)`). Step 4 review shows "Active
immediately" / "Paused" via `watchActiveLabel`.
