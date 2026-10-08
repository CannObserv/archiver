# InfoItem Detail - Organization Row

**The InfoItem Overview's Organization row (archiver#306): the linked Power Map
org, its notices, the `orgCombobox` type-ahead, and the link and unlink flow.**
Needed only when working on that row. [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md)
§ Overview names it; [PAGES.md](PAGES.md) keeps the inventory lines for its two
routes; [COMPONENTS.md](COMPONENTS.md) catalogues the component. Org identity
itself - the snapshot, `link_org`, the follower - is
[SCHEMA.md](SCHEMA.md)'s and the design doc's
(`docs/plans/2026-10-02-repspec-assignment-workflow-design.md` §§2-3).

## The row

`info_items/_org_row.html` (`#ii-org`, label `#ii-org-heading`), a full-width
`.detail-grid` cell on the `editableField` view/edit pattern. Its one builder is
`_org_row_context` (registered in the #219 partial contracts); the hub page
spreads it whole, so its keys are `org_`-prefixed where they could collide.

**View** reads the `pm_organizations` snapshot, never Power Map: the org's
name (acronym), or a muted "Not linked", plus one notice per state - each a
`badge--sm` *word* beside its sentence, so no state rides on colour alone. Pure
in `src/dashboard/org_row.py`:

| Notice | When | Says |
|---|---|---|
| Renamed | `RECENT_DAYS` (30) after `renamed_at` | "was X; paths now `organizations/<org.title_slug>/…`" - the slug from the effective bag, so a stored override shows; none when the name slugs to nothing |
| Merged | 30 days after a merge folded another org in | the loser's name: a row whose `merged_into` is this org, dated by its `checked_at` (set at the merge; the follower never checks an unlinked loser again) |
| Succeeded | `succeeded_by` set | the successor's name when archiver holds its snapshot, else its id; never followed |
| Archived / Inactive | `archived_at` / `not active` | as named |
| Missing | `missing_since` set | since when; the last snapshot still renders |

**Edit** is the type-ahead below. With Power Map not configured it is a
"linking is unavailable" status line instead. **Unlink** (linked only) needs no
confirmation - "Unlink keeps current paths; the values become hand-typed" - and
works with Power Map dormant: `link_org` never asks Power Map to unlink.

## The type-ahead

It opens on **local suggestions**: orgs linked to other items on this item's
domains (active bindings' `domain_name`), most-linked first, the item's own org
left out, no Power Map call. From two characters `GET /dashboard/power-map/orgs`
(300ms debounce, `hx-sync="this:replace"`) searches Power Map, limit 10,
archived excluded; under two it answers with the local suggestions again.
Dormant, unavailable or no match is a `role="status"` line in a **200**, so only
the type-ahead degrades. Options render from `power_map/_org_options.html`,
swapped into `#ii-org-results`.

`orgCombobox` (`main.js`) is an ARIA 1.2 combobox with list autocomplete: the
input keeps focus throughout and announces the active option through
`aria-activedescendant`. **It never builds an option** - it reads
`[role=option]` and its `data-pm-org-id`/`data-label` each time, so an htmx swap
needs only `onResults()`, wired to `@htmx:after-swap`.

| Key | Effect |
|---|---|
| ArrowDown / ArrowUp | Open if closed; move the active option, wrapping. From none active, Down starts at the first, Up at the last. |
| Enter | Choose the active option. With none active and nothing chosen, swallowed: an implicit submit would send a blank `pm_org_id`, which is Unlink. With a choice, it submits like Link. |
| Escape | Close an open list; on a closed one, clear the input and the choice. |
| Tab | Close, and let focus move on. |

A click on an option chooses it (`@mousedown.prevent` keeps focus in the
input); a click outside closes; focus opens the list when it has an option or a
status line.

**Two invariants.** `pm_org_id` (`$refs.choice`) is non-blank only while the
input still shows the label it came with: `@input` calls `clearChoice()`, and
Link is `:disabled="!chosen"`. And a confirmation never outlives its choice
(CR 1): choosing, typing over a choice, and `reset()` all empty the flash the
form's `data-flash` names, so a 409's **Link and move** cannot link an org the
input no longer shows. Cancel calls `reset()` - which also restores
`$refs.local`, the suggestions the row opened with - before `editableField`'s
`cancelEdit()`; neither component can see the other's refs.

JS tests: `tests/js/org-combobox.test.js`.

## Link and unlink

Both `PUT /dashboard/info-items/{id}/org` through `link_org`, the write
`PUT /info-items/{id}/org` shares. The posted `q` (the input) names the org in a
refusal. Refusals land in `#ii-org-flash` (`aria-live="polite"`) via
`hx-target-409`/`-422`/`-503`, rendered by `_move_flash.html`:

- **409** - #302's move contract: the stored hand-typed `org.title`/`org.acronym`
  differ from Power Map's, so an active assignment's path moves. Before → after
  per assignment, with **Link and move** re-sending the warned-about `pm_org_id`
  with `allow_destination_change`.
- **422** - an org Power Map lacks, or one that breaks an assignment (naming the
  RepSpec and key).
- **503** - Power Map dormant or down; nothing linked.

**200** re-renders the row (`HX-Retarget: #ii-org`, focus to its label) and
fires `replicationChanged` from `org`, so Fields and the picker re-read the
effective bag (UI.md § *Blocks that share a section*).
