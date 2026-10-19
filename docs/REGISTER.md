# Register Screen - Wizard Anatomy

**The `/dashboard/register` wizard's summary bar, its Step 1 Case B choice and
its Step 3 controls.**
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

**Step 1 - Case B: reuse the existing source** (archiver#51). The url-check card
(`_url_check.html`) is Case B when the URL has InfoSources and none is actively
bound. The new item **reuses one by default**: `source_revisions` hang off
`info_source_id`, so the source's revision history and fingerprint chain carry
over, and the item detail lists the earlier revisions at once. An unbound source
belongs to no other item, so editing its specs affects no one.

- **The choice** is a `source_choice` radio group in the card's `<fieldset>`:
  one radio per source (its `created_at`, a specs summary, "N earlier revisions
  will appear", a link to the source), then **Create a new source instead**
  (`value="new"`), which keeps the create path. With **one** source it is
  pre-selected. With **several**, none is, and step 1's Next stays disabled
  (`needsSourceChoice`) until the operator picks.
- **Stored specs the current schema rejects** (#164): the card runs
  `validate_source_spec` over each source and names the errors under it. A
  reused source's specs are saved through `update_info_source_specs`, which
  runs the same validator, so an unfixed stored spec reopens step 2 with the
  same `errors.source_specs` line an edited one gets. The browser can't call
  `/api/v1/tools/validate-source-spec`, which needs an API key.
- **Pre-fill**: choosing a source copies its stored specs into step 2's
  textarea (`chooseSource`), but only while the textarea is empty or still holds
  the last pre-fill. An edit, or specs a validation re-render brought back, are
  never overwritten. The opt-out leaves the specs as they are.
- **Review**: the step-4 **Information Source** row (`sourceChoiceLabel`) reads
  "Reuse the existing source (N earlier revisions will appear)" or "A new
  source".
- **The server re-derives the case** and doesn't trust the card. Every refusal
  at a valid URL re-renders the wizard with the card included server-side and
  the choice still checked, because htmx fetches the card only on the URL's
  `change` (an invalid URL has no card to show):
  - Case B with no `source_choice` is a 422 at step 1.
  - A `source_choice` naming a source not at this URL is a 422.
  - A source bound since the check is a **409** at step 1: the bind takes
    `require_unbound_source`, which locks the source, so two registrations
    can't both take it.
- **Side effects** (measured on 8001, archiver#51): reusing a source issues
  **no** `content.replicate` and **no** `content.persist`. Both are issued on a
  newly recorded revision, and binding records none. `source_revisions` is
  unique on `(info_source_id, content_fingerprint)`, so Watcher's first fetch of
  unchanged content records nothing, and a RepSpec assigned to the new item
  waits for a content change or the operator's **Replicate now**. Earlier
  revisions are never replicated on the new item's behalf.

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
The submit binds through `bind_info_source`, so a registration also stages one
`info_item_primary_changed` on `info.changes` with a null `old_info_source_id`
(archiver#390), in the same transaction.
Sticky across validation re-renders (`watch_active_value` → `checked` attribute,
defaulting to checked via `|default(true)`). Step 4 review shows "Active
immediately" / "Paused" via `watchActiveLabel`.
