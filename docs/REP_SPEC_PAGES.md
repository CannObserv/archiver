# Archiver Dashboard - Replication Specification Pages

**The RepSpec list, create form and detail screen, and the routes behind
them.** Split out of [PAGES.md](PAGES.md), the per-page inventory, when that
file passed its context budget; same living-doc rule: a change to a
`rep_specs/` template or a `/dashboard/rep-specs/` route updates this file in
the same commit. Shared mechanics: [UI.md](UI.md), [HTMX.md](HTMX.md).

## Replication Specifications (`/dashboard/rep-specs/`)

**GET `/dashboard/rep-specs/`** - paginated list. Optional `provider` filter (enum: `gcs` / `gdrive` / `ia`). Columns: name (link to detail), provider badge, created_at.

**GET `/dashboard/rep-specs/new`** - create form. Provider `<select>` - `gdrive` and `ia` are rendered **disabled, not hidden**, each with its reason inline, because Replicator writes for `gcs` only (CannObserv/replicator#29); `UNWRITABLE_PROVIDERS` in `src/dashboard/providers.py` - shared with the InfoItem picker (archiver#308) - is the one place to lift when a writer lands, and the sub-schema question is #153 - name text input, document JSON textarea (the `repSpecEditor` component, validate-on-blur). The hint under the textarea is the authoring contract in miniature: `required_fields` lists the bag keys the template uses (a `_slug` key derives from its raw field, so list `org.title_slug` and enter `org.title` on the item), and the eight `source_revision.*` keys are supplied per replication and never listed there; `credentials_alias` is `<provider>-<role>` with the selected provider as prefix, e.g. `gcs-publication` (archiver#276). Returns 200 with an errors dict on validation failure.

**POST `/dashboard/rep-specs/new`** - form fields: `provider`, `name`, `document` (JSON string). Calls `create_rep_spec`. 303 to detail on success; re-renders the form with errors on missing provider, an unwritable provider (`gdrive`, `ia` - refused server-side too, so a direct POST cannot bypass the disabled option; a template-only gate is the #167 defect class), missing name, invalid JSON, or `InvalidRepSpecError`. The API's `POST /rep-specs` is unchanged: the contract still accepts the envelope's full enum.

**GET `/dashboard/rep-specs/{id}`** - detail page.

- The stored-document notice ([PAGES.md](PAGES.md) § Home), when `document` fails the current schema; frozen
  (assigned) specs get the clone remedy.
- Header: `.entity-card` (SCREENS.md § **Header**, `#rep-spec-heading`, #80) - eyebrow "Replication Specification", name, copyable `rep_spec_id`, `.detail-grid` (provider badge, created_at UTC, plus **Updated** UTC *only when* `updated_at` is non-null - a null means "never edited", and rendering `created_at` there would blur that distinction, #83).
- Document card - the `rep_specs/_document_card.html` partial, extracted so the update-document action can swap it in place (root `#rep-spec-document-card`, heading `#rep-spec-document-heading`). Shows the stored document JSON in `<pre class="code-block">`, then **conditionally** an edit form: the textarea renders only while the RepSpec is a *draft* - zero `info_item_rep_specs` rows, active **or** deactivated. That count comes from `assignment_count()`, deliberately not `_load_active_assignments`: a deactivated assignment still means a replication run happened under that document. A non-draft gets an `.alert--info` "frozen" notice with the count instead of the form (#83; clone + migrate is #95).
- Active assignments - `rep_specs/_assignments.html` (wrapper `#rep-spec-assignments`): count in heading; item name link, activated_at UTC, **Replication** (the `replication_state` macro over the latest `replication_commands` row for that assignment), read-only `public_url` with an `open_button`, and **Replicate now** + **Deactivate** actions. Deactivate is `hx-delete` to the RepSpec-scoped route below, targeting `#rep-spec-assignments` (`outerHTML`) so the row set, count, and empty-state re-render together. Assignments are manageable from either the RepSpec or the InfoItem screen (#80). The wrapper **polls itself while a command is open** (archiver#212), identically to the InfoItem hub's section and from the same `live_poll` decision, so the two screens cannot disagree about when a command is worth watching - see INFO_ITEM_DETAIL.md § Replication Specs for the mechanism and the two-minute bound. The poll yields to both row actions the same way too (archiver#220, HTMX.md § *A section that polls and takes actions*). Every render site spreads `_assignments_context`, which carries `spec` too (SCREENS.md § *One builder per behaviour-bearing partial*, #219).

**POST `/dashboard/rep-specs/{id}/document`** - replaces the `document` on a **draft** RepSpec (form field: `document`, a JSON object string). An **editor card** (SCREENS.md § **Editor cards**) against `#rep-spec-document-card`, error key `doc_error` - the same shape as the InfoSource source-specs editor. Whole-document replace, not merge (#83). Rejections: JSON parse failure, schema/sub-schema validation, an attempted `provider` change (immutable), and `RepSpecNotDraftError` - the last re-checked server-side, because a rendered editor goes stale if the spec acquires an assignment mid-edit.

**DELETE `/dashboard/rep-specs/{id}/assignments/{aid}`** - deactivates a RepSpec assignment (sets `deactivated_at`); the assignment must belong to `{id}` (404 otherwise). Returns the re-rendered `rep_specs/_assignments.html` fragment.

**GET `/dashboard/rep-specs/{id}/assignments`** - the Active Assignments section as a standalone fragment, for the poll above (archiver#212). Renders with `swapped=False` so a tick never moves focus.

**POST `/dashboard/rep-specs/{id}/assignments/{aid}/replicate`** - the InfoItem hub's twin, spec-scoped (archiver#171). Issues one replication occasion against the item's latest SourceRevision; the assignment must belong to `{id}` (404 otherwise). Re-renders the whole `rep_specs/_assignments.html` section and moves focus to its heading. Identical outcome handling to the hub route: always 200, always a `showFlash` toast (`success` / `warning` / `error`).

It exists because this screen is the natural entry point for "this spec's assignments are all stale", and rendering the state here while forcing a navigation hop per item to act on it makes the diagnosis useless.
