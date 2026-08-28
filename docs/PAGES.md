# Archiver Dashboard - Page Inventory

**What each dashboard screen renders, and the routes behind it.**

Shared mechanics live in [UI.md](UI.md) - the URL map, the proxy-header auth
gate, and HTMX swap patterns (flash messages, `hx-target-422`);
[SCREENS.md](SCREENS.md) holds the detail-screen conventions this
file refers to by name. Alpine components are
catalogued in [COMPONENTS.md](COMPONENTS.md).

Every route below is auth-gated; see UI.md § Authentication. The entries do not
repeat it.

> **AGENTS.md enforcement:** update this file in the same commit as any Jinja2
> template change or new/changed dashboard route.

---

## Home (`/dashboard/`)

**GET `/dashboard/`** - summary dashboard. Four count tiles in nav order (Information Items, Information Sources, Information Source Revisions, Replication Specifications), each linking to its list page. Recent Changes table: last 10 SourceRevisions ordered by `captured_at desc`; columns Information Source (URL, links to source detail), Source Revision (truncated fingerprint, links to revision detail), Observed (captured_at as `%Y-%m-%d %H:%M`).

The health row is **Archiver + Redis + Outbox + Consumers** since archiver#147
(the absence of a Watcher badge is deliberate, not an omission). Each badge is
its own `hx-trigger="load"` partial - non-blocking, "checking…" until HTMX
fires. **Every badge is a live route:** the template used to branch on
`ARCHIVER_REDIS_URL` to render a static "not configured" span instead of the
loader, reporting configuration as if it were state (#147).

**GET `/dashboard/health`** - returns `<span class="badge badge--success">ok</span>`.

**GET `/dashboard/health/redis`** - `redis.ping()`. Success "ok"; danger
"error" with the exception message in `title`; the no-client branch below,
which returns before any logging (the other two log a warning).

**The no-client branch** (`_no_client_badge`; the Outbox badge applies the same
split in its own "not draining" vocabulary) splits `app.state.redis_client is None` by *why*: muted "not
configured" when `ARCHIVER_REDIS_URL` is unset (the dev server's bus-dormant
default), danger "init failed" when it is set and bus init raised at startup.
One branch reported both until CR round 1 finding 3 - a broken production bus
wearing the dev server's vocabulary is the same configuration-as-state
conflation #147 exists to remove.

**GET `/dashboard/health/outbox`** - over `src/core/changes/outbox_stats.py`
(archiver#112). The no-client branch splits the same way the other two do:
muted "not draining" with no `ARCHIVER_REDIS_URL` (publisher dormant - dev's
default - so a stale backlog is not ill health), danger "not draining (init
failed)" when the URL is set, which is exactly when a stale backlog *is* ill
health. Otherwise danger "N dead-lettered" if any poison row, warning
"backlog" if the oldest live unpublished row exceeds 300s, else success "ok";
`title` carries `depth=N oldest=Ns dead_lettered=N` in the drain states.

**GET `/dashboard/health/consumers`** - over
`src/core/bus_health.collect_group_lag` (archiver#147). Liveness from
`app.state.{revisions,artifacts}_consumer_task`, no broker call; depths from
the same probe module the #130 timer uses. Ladder, first match wins - the
no-client branch above / muted "gated off" (`ARCHIVER_BUS_CONSUMER` unset, the
dev default) / danger "not started" / danger "stopped" / warning "lag unknown"
(probe raised or timed out) / danger "N dead-lettered" / warning "group
missing" (absent group, not a healthy zero) / warning "lagging" / success
"running". Liveness outranks lag: a stopped consumer is the cause, its lag the
symptom. `title` carries `<name>=<state> pending=N dlq=N` per consumer.

The probe is bounded by `LAG_PROBE_TIMEOUT_SECONDS` (5s) at the call site
rather than by a socket timeout on the client: the badge borrows the lifespan's
Redis client, and the group consumers issue a blocking `XREADGROUP` on it, so a
socket timeout under that block would break them. Unbounded, a broker that
hangs rather than refuses never reaches "lag unknown" at all (CR round 1,
finding 1). Only `TimeoutError` and `RedisError`/`OSError` become that badge -
a `TypeError` out of the probe is a bug here and is left to 500 rather than
dressed up as a broker condition (finding 2). A timeout titles itself `probe
exceeded <N>s` rather than the bare `TimeoutError()` an empty `str()` produced,
so a wedged broker reads differently from a refused one (round 2, finding 11).

**`…/health/watcher` retired with archiver#142** - it pinged Watcher over the
SDK, and the no-outbound-HTTP rule left nothing to ping. Its successor signal
is the announced-vs-applied generation drift on the InfoItem detail panel,
which measures whether Watcher is *acting on what we published* - the question
the badge was a proxy for.

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
Case A/B/C card for the URL; empty body when `url` is blank.

**GET `/dashboard/register/suggest-specs?url=`** - HTMX partial: top-5 selector
suggestions from the URL's domain.

**POST `/dashboard/register/preview`** - HTMX partial: attempts a preview
extraction for `url` + `source_specs`.

**POST `/dashboard/register`** - the submit. Form fields `url`, `source_specs`,
`name`, `description`, `cadence`, `watch_active`. Atomic create-source →
create-item → bind, 303 to detail; 422 re-renders the wizard.

**The wizard's rolling step-summary bar and its Step 3 (Metadata) Watcher
settings** - the chip anatomy, the cadence `<select>` and its vocabulary, and
the watch-active checkbox - are [docs/REGISTER.md](REGISTER.md), needed only
when working on that screen. The entries above stay the inventory line for
each route.

---

## Information Items (`/dashboard/info-items/`)

**GET `/dashboard/info-items/`** - paginated list with optional `name_contains` search. Filter panel: search input (flex-fill) + Search button (right-aligned via `margin-left:auto`). Columns: name (link to detail), Information Source (primary source URL linked to InfoSource detail; `-` if none), Observed (max `captured_at` of the primary source's revisions, `%Y-%m-%d %H:%M`; `-` if none).

**GET `/dashboard/info-items/new`** - 301 redirect to `/dashboard/register`.

**POST `/dashboard/info-items/new`** - legacy direct-create, still live. Form fields: `name`, `description`, `owner`, `rep_fields` (JSON), `initial_url` (string), `initial_source_specs` (JSON array). 303 to detail on success; 422 re-rendering `info_items/new.html` on validation error. Interactive registration goes through `/dashboard/register`.

**GET `/dashboard/info-items/{id}`** - the 5-section vertical-scroll hub page
(`info_items/detail.html`). Its section anatomy, partial templates, and swap
targets are [docs/INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md), needed only when
working on that screen.

**The hub screen's action-route contracts** - the shared Watcher-POST contract,
the three routes that retired with the SDK, and the always-200 always-flash
replication outcome rule - are in
[docs/INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md) § **Action-route contracts**.
The entries below stay the inventory line for each route.

**GET `/dashboard/info-items/{id}/watcher-status`** - HTMX partial rendered from local state, zero SDK calls (#151); states not_watching/no_status/watching. No page embeds it: it is reachable directly, and is the (discarded) response body of the two action POSTs.

**GET `/dashboard/info-items/{id}/watcher-section`** - the section 3 partial (its anatomy is in [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md)), same local render. Loaded on page init via `hx-trigger="load"` and re-fetched on the `watcherUpdated` body event. The section's `<h2>` is a plain heading - the Watcher deeplink it used to carry retired with archiver#142.

**POST `/dashboard/info-items/{id}/toggle-watch-active`** - pauses or resumes by writing `info_items.watch_active` and announcing it (archiver#158); no SDK call. Form field `active` is the desired target state ("true" → resume, anything else → pause); the button submits the opposite of the current *applied* state. Gating, applied-state lag, and the failure path: [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md) § **Action-route contracts**.

**POST `/dashboard/info-items/{id}/watch-cadence`** - replaces `info_items.watch_spec` and announces it (archiver#158). Form field `interval`; empty means *delegate* (document keeps only `schema_version`, consumer applies its own default). Replace-vs-merge reasoning and the vocabulary gate: [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md) § **Action-route contracts**.

**POST `/dashboard/info-items/{id}/swap-primary-source`** - inline primary-source swap: creates a new InfoSource (form fields: `url`, `source_specs` JSON array), deactivates the old active binding, binds the new source, and announces the whole swap as one `info.registry` frame. 204 + `HX-Redirect` to detail on success; 422 with a `<div id="swap-error">` fragment on validation error. Template: `info_items/_swap_primary.html`.

**POST `/dashboard/info-items/{id}/swap-primary-by-id`** - the same swap flow for an existing InfoSource (form field: `info_source_id` ULID). Deactivates the old binding, binds the new source, announces once. 204 + `HX-Redirect`; a ULID validation error returns 422 with a `<div id="swap-by-id-error">` fragment.

**POST `/dashboard/info-items/{id}/bind-source`** - binds an existing InfoSource (form field: `info_source_id`). 303 to detail; 409 if an active binding already exists. Not linked from the dashboard UI - interactive use goes through swap-primary-by-id.

**DELETE `/dashboard/info-items/{id}/info-sources/{source_id}`** - HTMX delete (form POST + route handler); sets `deactivated_at = now()`. Response triggers an HTMX redirect to detail.

**POST `/dashboard/info-items/{id}/assign-rep-spec`** - assigns a RepSpec (form field: `rep_spec_id`). 303 to detail.

**DELETE `/dashboard/info-items/{id}/rep-spec-assignments/{aid}`** - HTMX delete; sets `deactivated_at = now()`, idempotent (skipped if already deactivated). Returns the re-rendered `info_items/_rep_spec_assignments.html` fragment (targets `#ii-rep-spec-assignments`), which updates the table/empty-state and moves focus to the section heading.

**POST `/dashboard/info-items/{id}/rep-spec-assignments/{aid}/replicate`** - issues one replication occasion for this assignment against the InfoItem's latest SourceRevision (archiver#171). Returns the re-rendered `info_items/_rep_spec_assignments.html` fragment (targets `#ii-rep-spec-assignments`) and moves focus to the section heading - the swap destroys the clicked button, exactly as the Deactivate beside it does. Double guard: [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md) § **Action-route contracts**.

**PATCH `/dashboard/info-items/{id}/rep-fields`** - inline save for `rep_fields` JSONB (form field: `rep_fields` JSON string). Returns a flash fragment into `#rep-fields-flash`.

**GET `/dashboard/info-items/{id}/suggest-rep-fields`** - HTMX partial: domain-scoped `rep_fields` key suggestions as `sortableChips` ([COMPONENTS.md](COMPONENTS.md)).


## Information Sources (`/dashboard/info-sources/`)

**GET `/dashboard/info-sources/`** - paginated list. Query params: `url_contains` (ilike filter on the `url` column), `limit`, `offset`.

**GET `/dashboard/info-sources/new`** - create form. Fields: `url` (text input) + `source_specs` (JSON array textarea, validates JSON on blur).

**POST `/dashboard/info-sources/new`** - form fields: `url` (string), `source_specs` (JSON array string). Calls `create_info_source`. 303 to detail on success; re-renders the form with an `errors` dict on `InvalidUrlError`, `InvalidSourceSpecError`, `MixedAlgorithmFamilyError`.

**GET `/dashboard/info-sources/{id}`** - detail page. Sections:

- Header: `.entity-card` (SCREENS.md § **Header**, `#info-source-heading`, #79) - eyebrow "Information Source", the `url` in `<code>`, copyable `info_source_id`, then the **domain pill**: `domain_name` as a `.badge--primary` linking `/dashboard/domains/{name}`, or a `.badge--muted` "No domain" where the column is null - a state of its own, not an absence (#185). `open_button` is the header's action slot. `.detail-grid` (created_at UTC).
- Source Specification editor - the `info_sources/_source_specs_card.html` partial, extracted so the update-specs action can swap it in place (root `#source-specs-card`, heading `#source-specs-heading`, titled "Source Specification"). `sourceSpecsCard(startEditing)` (`main.js`; not in the COMPONENTS.md catalogue - it exists only for this card) gates it: **view mode** (`x-show="!editing"`) renders `source_specs` in `<pre class="code-block">`, edit mode the textarea form. All three buttons share one `.entity-card__actions` slot in the `.entity-card__header` (#185): **Edit** (`x-show="!editing"`); **Cancel** (`btn--secondary`, for border parity with the `apiKeyRow` Cancel - `@click="cancel()"` restores the stored specs and returns to view mode with no server call); **Save**, which submits the `POST .../source-specs` replace via `form="source-specs-form"` - it renders outside the `<form>`, so without that association it is inert with JS off. `specs_error` opens the card in edit mode (`sourceSpecsCard(true)`) so the error and the submitted text stay visible. The URL is immutable.
- Other Sources at This URL - shown only when other InfoSources share this `url` (the model allows several sources per URL, #79 #8); count in the heading, capped at 50 via a `limit+1` probe and rendered "50+" beyond that, each linked by `info_source_id` with its created date UTC.
- Bound Information Items - table of active `info_item_sources` bindings (count in heading; item name link, bound date UTC).
- Revision History - last 50 `source_revisions` ordered by `captured_at desc` (count in heading; fingerprint truncated, captured date UTC, cache status pill).

**POST `/dashboard/info-sources/{id}/source-specs`** - replaces the `source_specs` list on an existing InfoSource (form field: `source_specs` JSON array). An **editor card** (SCREENS.md § **Editor cards**) against `#source-specs-card`, error key `specs_error` (#79 #7). Rejections: JSON parse failure, schema validation, mixed algorithm family.

## Information Source Revisions (`/dashboard/source-revisions/`)

**GET `/dashboard/source-revisions/`** - paginated list ordered by `captured_at desc`. Optional `info_source_id` filter (ULID). Columns: truncated fingerprint (link to detail), source URL (link to InfoSource detail), captured date, cache status pill (`.status-pill--cached` / `.status-pill--expired` / `.status-pill--missing`).

**GET `/dashboard/source-revisions/{id}`** - detail page, and the reference implementation of the SCREENS.md conventions. The header lives in `source_revisions/_detail_card.html`, extracted so clear-cache can swap it in place (root `#revision-card`): `.eyebrow` "Information Source Revision" above an `<h1>` titled with the copyable `source_revision_id`. `.detail-grid` carries the copyable full fingerprint and the Information Source on `.detail-grid__item--full` rows so long values extend horizontally; the Information Source value holds the internal source-detail link plus an `open_button` to the target URL. Then captured_at (UTC), size and media type (each if set), and cache status - a status pill plus the `content_cache_uri` (`open_button` when `http(s)`, otherwise copyable) and an expiry line. "View all revisions for this source →" deeplinks the list as `?info_source_id=`. A danger-zone clear-cache form shows only when `content_cache_uri` is set.

**POST `/dashboard/source-revisions/{id}/clear-cache`** - sets `content_cache_uri = NULL` and `content_cache_expires_at = NULL`. HTMX requests (`hx-post`, `hx-target="#revision-card"`, `hx-confirm`) get the re-rendered `_detail_card.html` swapped in place plus an `HX-Trigger: showFlash` success toast; non-HTMX requests fall back to a 303 to detail. No request body required.

## Replication Specifications (`/dashboard/rep-specs/`)

**GET `/dashboard/rep-specs/`** - paginated list. Optional `provider` filter (enum: `gcs` / `gdrive` / `ia`). Columns: name (link to detail), provider badge, created_at.

**GET `/dashboard/rep-specs/new`** - create form. Provider `<select>`, name text input, document JSON textarea (the `repSpecEditor` component, validate-on-blur). Returns 200 with an errors dict on validation failure.

**POST `/dashboard/rep-specs/new`** - form fields: `provider`, `name`, `document` (JSON string). Calls `create_rep_spec`. 303 to detail on success; re-renders the form with errors on missing provider, missing name, invalid JSON, or `InvalidRepSpecError`.

**GET `/dashboard/rep-specs/{id}`** - detail page.

- Header: `.entity-card` (SCREENS.md § **Header**, `#rep-spec-heading`, #80) - eyebrow "Replication Specification", name, copyable `rep_spec_id`, `.detail-grid` (provider badge, created_at UTC, plus **Updated** UTC *only when* `updated_at` is non-null - a null means "never edited", and rendering `created_at` there would blur that distinction, #83).
- Document card - the `rep_specs/_document_card.html` partial, extracted so the update-document action can swap it in place (root `#rep-spec-document-card`, heading `#rep-spec-document-heading`). Shows the stored document JSON in `<pre class="code-block">`, then **conditionally** an edit form: the textarea renders only while the RepSpec is a *draft* - zero `info_item_rep_specs` rows, active **or** deactivated. That count comes from `assignment_count()`, deliberately not `_load_active_assignments`: a deactivated assignment still means a replication run happened under that document. A non-draft gets an `.alert--info` "frozen" notice with the count instead of the form (#83; clone + migrate is #95).
- Active assignments - `rep_specs/_assignments.html` (wrapper `#rep-spec-assignments`): count in heading; item name link, activated_at UTC, **Replication** (the `replication_state` macro over the latest `replication_commands` row for that assignment), read-only `public_url` with an `open_button`, and **Replicate now** + **Deactivate** actions. Deactivate is `hx-delete` to the RepSpec-scoped route below, targeting `#rep-spec-assignments` (`outerHTML`) so the row set, count, and empty-state re-render together. Assignments are manageable from either the RepSpec or the InfoItem screen (#80).

**POST `/dashboard/rep-specs/{id}/document`** - replaces the `document` on a **draft** RepSpec (form field: `document`, a JSON object string). An **editor card** (SCREENS.md § **Editor cards**) against `#rep-spec-document-card`, error key `doc_error` - the same shape as the InfoSource source-specs editor. Whole-document replace, not merge (#83). Rejections: JSON parse failure, schema/sub-schema validation, an attempted `provider` change (immutable), and `RepSpecNotDraftError` - the last re-checked server-side, because a rendered editor goes stale if the spec acquires an assignment mid-edit.

**DELETE `/dashboard/rep-specs/{id}/assignments/{aid}`** - deactivates a RepSpec assignment (sets `deactivated_at`); the assignment must belong to `{id}` (404 otherwise). Returns the re-rendered `rep_specs/_assignments.html` fragment.

**POST `/dashboard/rep-specs/{id}/assignments/{aid}/replicate`** - the InfoItem hub's twin, spec-scoped (archiver#171). Issues one replication occasion against the item's latest SourceRevision; the assignment must belong to `{id}` (404 otherwise). Re-renders the whole `rep_specs/_assignments.html` section and moves focus to its heading. Identical outcome handling to the hub route: always 200, always a `showFlash` toast (`success` / `warning` / `error`).

It exists because this screen is the natural entry point for "this spec's assignments are all stale", and rendering the state here while forcing a navigation hop per item to act on it makes the diagnosis useless.

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
