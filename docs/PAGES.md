# Archiver Dashboard - Page Inventory

**What each dashboard screen renders, and the routes behind it.**

Shared mechanics live in [UI.md](UI.md) - the URL map, the proxy-header auth
gate; the HTMX swap patterns (flash messages, `hx-target-422`) are [HTMX.md](HTMX.md);
[SCREENS.md](SCREENS.md) holds the detail-screen conventions this
file refers to by name. Alpine components are
catalogued in [COMPONENTS.md](COMPONENTS.md).

Every route below is auth-gated; see UI.md § Authentication. The entries do not
repeat it.

> **AGENTS.md enforcement:** update this file in the same commit as any Jinja2
> template change or new/changed dashboard route.

---

## Home (`/dashboard/`)

**GET `/dashboard/`** - summary dashboard. Four count tiles in nav order (Information Items, Information Sources, Information Source Revisions, Replication Specifications), each linking to its list page. Recent Changes table: last 10 SourceRevisions ordered by `captured_at desc, source_revision_id desc` (the id breaks ties, archiver#149); columns Information Source (URL, links to source detail), Source Revision (truncated fingerprint, links to revision detail), Observed (captured_at as `%Y-%m-%d %H:%M`).

**The health row** - the badges behind **GET `/dashboard/health`**,
**`/dashboard/health/redis`**, **`/dashboard/health/outbox`**,
**`/dashboard/health/consumers`** and **`/dashboard/health/registry`**, each its own
`hx-trigger="load"` partial - is
[docs/HEALTH_ROW.md](HEALTH_ROW.md): what each badge reports, its state ladder,
and why the lag probe is bounded where it is. Needed only when working on that
row; this entry stays the inventory line for its routes.

**GET `/dashboard/registry-audit`** (`registry_audit.html`, archiver#164) - the page the
Registry badge links to: every stored document the current schemas reject, one row per
document - kind (a source spec carries its list index), the row's id linked to its detail
page, the validator's messages, and the remedy (`src/dashboard/stored_documents.py`; an
assigned RepSpec's is "clone it", #83). Empty state "Every stored document validates."
The same sweep the badge runs, once per load.

**GET `/dashboard/bus-triage`** (`bus_triage/index.html` + `_outbox_section.html` /
`_dlq_section.html`, archiver#271) - the page the Outbox and Consumers badges link to in
every state: one section for dead-lettered outbox rows, one per
`TRIAGE_DLQS` queue. Section partials **GET `/dashboard/bus-triage/outbox`** and
**`/dashboard/bus-triage/dlq/{dlq}`**; row actions **POST `.../outbox/{row_id}/rearm`**,
**`.../outbox/{row_id}/discard`**, **`.../dlq/{dlq}/{entry_id}/reprocess`** and
**`.../dlq/{dlq}/{entry_id}/discard`**. What each section renders, its states, the flash
per outcome and the audit line: [BUS_TRIAGE.md](BUS_TRIAGE.md).

**Stored-document notice** (`stored_document_notice` macro, `#stored-document-notice`,
archiver#164) - an `.alert--warning` at the top of the InfoSource, InfoItem and RepSpec
detail pages when a document stored on that row fails its current schema: kind, messages,
remedy. It judges only that row, never a sweep. Page-level and rendered on load, so an
in-place save that fixes the document clears it on the next reload, not in the swap.

## Domain pages (`/dashboard/domains/`)

**GET `/dashboard/domains/`** - paginated list. Columns: Domain (linked to detail), Sources (count), Status badge, Created. Filter bar: `?is_active=true|false|` (all). Source counts come from a GROUP BY query.

**GET `/dashboard/domains/{name}`** - detail. `.entity-card` header (SCREENS.md § **Header**, `#domain-heading`, #82): eyebrow "Domain", the copyable name, `open_button` on `https://{name}` - `Domain` stores a hostname, not a URL (#176). `.detail-grid`: Status badge, created_at UTC → the **notes row, inside the panel**, read-only with an inline Edit toggle (`domainNotes`, COMPONENTS.md). Then two related-collection tables - **Information Items** (bound to this domain's sources by an active `info_item_sources` row) and **Information Sources**, source URLs carrying `open_button`. Both headings count from a route `COUNT` (#82), both keep their own `limit+1` `has_more` probe, and they page independently on `limit`/`offset` and `item_limit`/`item_offset` (#176) - SCREENS.md §§ **Related-collection tables**, **Two paginated tables on one screen get two windows**. Each has two empty states: an overshot offset gives "No sources/items on this page" plus a link back to that table's first page, an empty collection "No Information Sources registered for this domain yet" / "No Information Items bound to this domain yet". **Archive** is a `.danger-zone` block at the bottom, shown only while active (`.btn--danger` + static confirm). **Restore** is recovery, not destruction, so it sits inline in the header Status field beside the "archived" badge (`.btn--secondary`), and the danger zone is then hidden entirely. Both stay full-page POST→303 by design - the *allowed variant* note under SCREENS.md § **HTMX mutations**.

**POST `/dashboard/domains/{name}/notes`** - saves notes. HTMX: swaps `#notes-section` with `domains/_notes_partial.html` in read-only mode, `swapped=True` (focus move) plus a `showFlash` toast. Non-HTMX: 303 to detail, so the form's no-JS fallback lands (SCREENS.md § **HTMX mutations**).

**POST `/dashboard/domains/{name}/archive`** - sets `archived_at`, redirects 303 to detail. Triggered from the danger-zone Archive button.

**POST `/dashboard/domains/{name}/restore`** - clears `archived_at`, redirects 303 to detail. Triggered from the header Restore button.

Templates: `domains/list.html`, `domains/detail.html`, `domains/_notes_partial.html`.

## Registration flow (`/dashboard/register`)

4-step flow (#49): URL → Selector → Metadata → Review & Submit. Full spec:
`docs/plans/2026-06-04-dashboard-ux-redesign-design.md`. State lives in the
`registerWizard` component ([COMPONENTS.md](COMPONENTS.md)). Its routes:

**GET `/dashboard/register`** - renders the wizard (step 1: URL input).

**GET `/dashboard/register/url-check?url=`** - HTMX partial: domain badge +
Case A/B/C card for the URL; empty body when `url` is blank. Case B's card is
the reuse choice ([REGISTER.md](REGISTER.md)).

**GET `/dashboard/register/suggest-specs?url=`** - HTMX partial: top-5 selector
suggestions from the URL's domain.

**POST `/dashboard/register/preview`** - HTMX partial: attempts a preview
extraction for `url` + `source_specs`, through the extractor Processor would
dispatch for the response's media type (#317). A spec that extractor refuses
(`css` on XML, `xpath` on HTML until cannobserv#557) renders as an error, one `path: message` line per validation error. Step 2's
help text names those limits: CSS for HTML pages, XPath for XML and feeds only,
full-page for anything.

**POST `/dashboard/register`** - the submit. Form fields `url`, `source_specs`,
`name`, `description`, `cadence`, `watch_active`, `source_choice` (Case B: an
InfoSource ULID to reuse, or `new`; archiver#51). Atomic create-source (or
reuse and save its specs) → create-item → bind, 303 to detail; 422 re-renders
the wizard, and so does a 409 when the reused source was bound since the check.

**The wizard's rolling step-summary bar, its Step 1 Case B choice and its Step 3
(Metadata) Watcher settings** - the chip anatomy, the reuse radios, the cadence
`<select>` and its vocabulary, and the watch-active checkbox - are
[docs/REGISTER.md](REGISTER.md), needed only
when working on that screen. The entries above stay the inventory line for
each route.

---

## Information Items (`/dashboard/info-items/`)

**GET `/dashboard/info-items/`** - paginated list with optional `name_contains` search. Filter panel: search input (flex-fill) + Search button (right-aligned via `margin-left:auto`). Columns: name (link to detail), Information Source (primary source URL linked to InfoSource detail; `-` if none), Observed (max `captured_at` of the primary source's revisions, `%Y-%m-%d %H:%M`; `-` if none).

**GET `/dashboard/info-items/new`** - 301 redirect to `/dashboard/register`.

**POST `/dashboard/info-items/new`** - legacy direct-create, still live. Form fields: `name`, `description`, `owner`, `rep_fields` (JSON), `initial_url` (string), `initial_source_specs` (JSON array). 303 to detail on success; 422 re-rendering `info_items/new.html` on validation error, including a `rep_fields` bag that is not Rep Fields v1 (archiver#302). With `initial_url` it binds through `bind_info_source`, so it emits `info_item_primary_changed` with a null `old_info_source_id` (archiver#390). Interactive registration goes through `/dashboard/register`.

**GET `/dashboard/info-items/{id}`** - the 5-section hub page
(`info_items/detail.html`). Its anatomy, partials, swap targets and **Action-route
contracts** (the shared Watcher-POST contract, the three routes retired with the
SDK, the always-200 always-flash replication outcome rule) are
[docs/INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md) and [INFO_ITEM_ACTIONS.md](INFO_ITEM_ACTIONS.md), needed only when working on
that screen. The entries below stay the inventory line for each route.

**GET `/dashboard/info-items/{id}/watcher-status`** - HTMX partial rendered from local state, zero SDK calls (#151); states not_watching/no_status/watching. No page embeds it: it is reachable directly, and is the (discarded) response body of the two action POSTs.

**GET `/dashboard/info-items/{id}/watcher-section`** - the section 3 partial (its anatomy is in [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md)), same local render. Loaded on page init via `hx-trigger="load"` and re-fetched on the `watcherUpdated` body event. The section's `<h2>` is a plain heading - the Watcher deeplink it used to carry retired with archiver#142.

**POST `/dashboard/info-items/{id}/toggle-watch-active`** - pauses or resumes by writing `info_items.watch_active` and announcing it (archiver#158); no SDK call. Form field `active` is the desired target state ("true" → resume, anything else → pause); the button submits the opposite of the current *applied* state. On an unannounceable item (no active source with specs) it writes nothing and re-renders with an error flash (archiver#167). Gating, applied-state lag, and the failure path: [INFO_ITEM_ACTIONS.md](INFO_ITEM_ACTIONS.md).

**POST `/dashboard/info-items/{id}/watch-cadence`** - replaces `info_items.watch_spec` and announces it (archiver#158). Form field `interval`; empty means *delegate* (document keeps only `schema_version`, consumer applies its own default). Refused like `toggle-watch-active` on an unannounceable item (archiver#167). Replace-vs-merge reasoning and the vocabulary gate: [INFO_ITEM_ACTIONS.md](INFO_ITEM_ACTIONS.md).

**POST `/dashboard/info-items/{id}/swap-primary-source`** - inline primary-source swap: creates a new InfoSource (form fields: `url`, `source_specs` JSON array), then runs `swap_primary_source`, the core tool behind `PUT /api/v1/info-items/{id}/primary-source` (archiver#45). It deactivates the old active binding, binds the new source, emits `info_item_primary_changed` and announces the whole swap as one `info.registry` frame. 204 + `HX-Redirect` to detail on success; 422 with a `<div id="swap-error">` fragment on validation error. Template: `info_items/_swap_primary.html`.

**POST `/dashboard/info-items/{id}/swap-primary-by-id`** - the same swap (`swap_primary_source`) for an existing InfoSource (form field: `info_source_id` ULID). Deactivates the old binding, binds the new source, emits `info_item_primary_changed`, announces once. 204 + `HX-Redirect`; the current primary is a 204 that writes nothing, and an earlier primary of this item starts a new tenure (a new binding row, archiver#392). A ULID validation error returns 422 with a `<div id="swap-by-id-error">` fragment.

**POST `/dashboard/info-items/{id}/bind-source`** - binds an existing InfoSource (form field: `info_source_id`). Emits `info_item_primary_changed`, naming the item's latest closed tenure as `old_info_source_id` (archiver#390), and announces. 303 to detail; 409 if an active binding already exists. Not linked from the dashboard UI - interactive use goes through swap-primary-by-id.

**DELETE `/dashboard/info-items/{id}/info-sources/{source_id}`** - HTMX delete (form POST + route handler); sets `deactivated_at = now()`. Response triggers an HTMX redirect to detail.

**GET `/dashboard/info-items/{id}/rep-spec-picker`** - the *Add a spec* picker (`#ii-rep-spec-picker`), re-fetched on a sibling's `replicationChanged`; `no-store`, never moves focus (archiver#308). Readiness and path read the linked Power Map org (archiver#304).

**POST `/dashboard/info-items/{id}/rep-spec-picker/assign`** - assigns a RepSpec (`rep_spec_id`) through `assign_rep_spec`; answers with the picker. Success fires `replicationChanged` + a toast and prompts to replicate; a refusal is a 200 naming the reason in `#picker-refusal` (archiver#301, #312, #334). Replaced the full-page `POST …/assign-rep-spec` (archiver#308). Contract: [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md) section 5.

**DELETE `/dashboard/info-items/{id}/rep-spec-assignments/{aid}`** - HTMX delete; sets `deactivated_at = now()`, idempotent (skipped if already deactivated). Returns the re-rendered `info_items/_rep_spec_assignments.html` fragment (targets `#ii-rep-spec-assignments`), which updates the table/empty-state and moves focus to the section heading. Fires `HX-Trigger` `replicationChanged` (`{"source": "assignments"}`): the Fields block's rows come from the active assignments (archiver#307).

**POST `/dashboard/info-items/{id}/rep-spec-assignments/{aid}/replicate`** - issues one replication occasion for this assignment against the InfoItem's latest SourceRevision (archiver#171). Returns the re-rendered `info_items/_rep_spec_assignments.html` fragment (targets `#ii-rep-spec-assignments`) and moves focus to the section heading - the swap destroys the clicked button, exactly as the Deactivate beside it does. Double guard: [INFO_ITEM_ACTIONS.md](INFO_ITEM_ACTIONS.md). Both buttons `hx-sync` on the section so its poll yields to them (archiver#220, [HTMX.md](HTMX.md) § *A section that polls and takes actions*). Fires no `replicationChanged`: an occasion changes nothing a sibling block renders, and the Fields block's re-fetch would discard unsaved input there (archiver#307).

**GET `/dashboard/info-items/{id}/rep-fields`** - the Fields block (`#ii-rep-fields`), re-fetched on a sibling's `replicationChanged`; `no-store`, never moves focus (archiver#307). `selected_spec` adds an unassigned spec's keys; `focus=true` (the picker's Select) focuses the first one it needs (archiver#308). A linked Power Map org's keys render read-only as *from Power Map* (archiver#304).

**GET `/dashboard/info-items/{id}/rep-fields/readout`** - the Fields block's live readout: unsaved `field_*` lists (and `selected_spec`) in, each row's status cell out of band. Writes and fires nothing (archiver#307).

**PATCH `/dashboard/info-items/{id}/rep-fields`** - saves `rep_fields` through `set_rep_fields`, from the Fields form's `field_key`/`field_value`/`field_type` lists or a `rep_fields` JSON string. 200 re-renders the block (`HX-Retarget`) and fires `replicationChanged`; 422 and 409 (paths as the picker's, #333) render `_move_flash.html` into `#rep-fields-flash` (#302, #307); a linked item's `org.title`/`org.acronym` is a 422 naming the org (archiver#304). A posted `selected_spec` keeps the picker's selection (archiver#308). Contract: [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md) section 5.


**PUT `…/{id}/org`**, **GET `/dashboard/power-map/orgs`** - Organization row Link / Unlink and type-ahead: [ORG_ROW.md](ORG_ROW.md) (archiver#306).

## Information Sources (`/dashboard/info-sources/`)

**GET `/dashboard/info-sources/`** - paginated list. Query params: `url_contains` (ilike filter on the `url` column), `limit`, `offset`.

**GET `/dashboard/info-sources/new`** - create form. Fields: `url` (text input) + `source_specs` (JSON array textarea, validates JSON on blur).

**POST `/dashboard/info-sources/new`** - form fields: `url` (string), `source_specs` (JSON array string). Calls `create_info_source`. 303 to detail on success; re-renders the form with an `errors` dict on `InvalidUrlError`, `InvalidSourceSpecError`, `MixedAlgorithmFamilyError`.

**GET `/dashboard/info-sources/{id}`** - detail page. Sections:

- The stored-document notice (§ Home), when `source_specs` fails the current schema.
- Header: `.entity-card` (SCREENS.md § **Header**, `#info-source-heading`, #79) - eyebrow "Information Source", the `url` in `<code>`, copyable `info_source_id`, then the **domain pill**: `domain_name` as a `.badge--primary` linking `/dashboard/domains/{name}`, or a `.badge--muted` "No domain" where the column is null - a state of its own, not an absence (#185). `open_button` is the header's action slot. `.detail-grid` (created_at UTC).
- Source Specification editor - the `info_sources/_source_specs_card.html` partial, extracted so the update-specs action can swap it in place (root `#source-specs-card`, heading `#source-specs-heading`, titled "Source Specification"). `sourceSpecsCard(startEditing)` (`main.js`; not in the COMPONENTS.md catalogue - it exists only for this card) gates it: **view mode** (`x-show="!editing"`) renders `source_specs` in `<pre class="code-block">`, edit mode the textarea form. All three buttons share one `.entity-card__actions` slot in the `.entity-card__header` (#185): **Edit** (`x-show="!editing"`); **Cancel** (`btn--secondary`, for border parity with the `apiKeyRow` Cancel - `@click="cancel()"` restores the stored specs and returns to view mode with no server call); **Save**, which submits the `POST .../source-specs` replace via `form="source-specs-form"` - it renders outside the `<form>`, so without that association it is inert with JS off. `specs_error` opens the card in edit mode (`sourceSpecsCard(true)`) so the error and the submitted text stay visible. The URL is immutable.
- Other Sources at This URL - shown only when other InfoSources share this `url` (the model allows several sources per URL, #79 #8); count in the heading, capped at 50 via a `limit+1` probe and rendered "50+" beyond that, each linked by `info_source_id` with its created date UTC.
- Bound Information Items - table of active `info_item_sources` bindings (count in heading; item name link, bound date UTC).
- Revision History - last 50 `source_revisions` ordered by `captured_at desc, source_revision_id desc` (count in heading; fingerprint truncated, captured date UTC, cache status pill).

**POST `/dashboard/info-sources/{id}/source-specs`** - replaces the `source_specs` list on an existing InfoSource (form field: `source_specs` JSON array). An **editor card** (SCREENS.md § **Editor cards**) against `#source-specs-card`, error key `specs_error` (#79 #7). Rejections: JSON parse failure, schema validation, mixed algorithm family.

## Information Source Revisions (`/dashboard/source-revisions/`)

**GET `/dashboard/source-revisions/`** - paginated list ordered by `captured_at desc, source_revision_id` (ascending tiebreak, unlike the two above). Optional `info_source_id` filter (ULID). Columns: truncated fingerprint (link to detail), source URL (link to InfoSource detail), captured date, cache status pill (`.status-pill--cached` / `.status-pill--expired` / `.status-pill--missing`).

**GET `/dashboard/source-revisions/{id}`** - detail page, and the reference implementation of the SCREENS.md conventions. The header lives in `source_revisions/_detail_card.html`, extracted so clear-cache can swap it in place (root `#revision-card`): `.eyebrow` "Information Source Revision" above an `<h1>` titled with the copyable `source_revision_id`. `.detail-grid` carries the copyable full fingerprint and the Information Source on `.detail-grid__item--full` rows so long values extend horizontally; the Information Source value holds the internal source-detail link plus an `open_button` to the target URL. Then captured_at (UTC), size and media type (each if set), and cache status - a status pill plus the `content_cache_uri` (`open_button` when `http(s)`, otherwise copyable) and an expiry line. "View all revisions for this source →" deeplinks the list as `?info_source_id=`. A danger-zone clear-cache form shows only when `content_cache_uri` is set.

**POST `/dashboard/source-revisions/{id}/clear-cache`** - sets `content_cache_uri = NULL` and `content_cache_expires_at = NULL`. HTMX requests (`hx-post`, `hx-target="#revision-card"`, `hx-confirm`) get the re-rendered `_detail_card.html` swapped in place plus an `HX-Trigger: showFlash` success toast; non-HTMX requests fall back to a 303 to detail. No request body required.

## Replication Specifications (`/dashboard/rep-specs/`)

The list, create form, detail screen and their routes:
[REP_SPEC_PAGES.md](REP_SPEC_PAGES.md).

## Settings - API Keys (`/dashboard/settings/api-keys`)

**GET** - lists the current user's keys. Table columns: Label, Prefix, Last Used, Actions. The create form starts collapsed; "+ Add key" in the header expands it.

**POST** - creates a key (`label` form field required). Returns the full page with `new_raw_key` in the template context so `apiKeyReveal` shows the raw key once; the create form collapses (`showForm` resets to false) and the reveal panel appears above the table. After navigation the raw key is gone.

A blank label - spaces, which pass the input's `required` attribute - returns the page **at 200** with `HX-Trigger: showFlash` at `error` level and no key created. It was a `raise_422` until archiver#178, and since the form is boosted htmx discarded the response whole: the button looked dead.

**DELETE `/dashboard/settings/api-keys/{id}`** - HTMX delete; the response replaces `<tr id="key-row-{id}">` with an empty string, removing the row. 404 if the key belongs to a different user.

**PATCH `/dashboard/settings/api-keys/{id}`** - renames the label (`label` form field, submitted via `hx-include`). Returns the `settings/_api_key_row.html` fragment replacing the row in view mode. 404 if the key belongs to a different user - ownership is resolved before the label is judged. A blank label returns the **unchanged** row at 200 with an `error` flash (archiver#178): a refused swap left the row looking exactly as it does after a successful rename.

Partial template: `settings/_api_key_row.html` - reusable `<tr x-data="apiKeyRow">` used both in the list render and as the PATCH response. Starts in view mode (`editing: false`); Edit switches to edit mode, Save sends the PATCH, Cancel reverts with no server call.

## Error pages (no route of their own)

Rendered by the exception handlers in `src/dashboard/errors.py`, not by a route,
so they appear under no URL above - any `/dashboard` path can produce them.
Templates and the rendering contract: [UI.md](UI.md) § **Error pages**.
