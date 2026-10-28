# Archiver Dashboard - Information Source Pages

**The InfoSource and SourceRevision screens, and the routes behind them.** Split out of
[PAGES.md](PAGES.md), the per-page inventory, when that file passed its context budget; same
living-doc rule: a change to an `info_sources/` or `source_revisions/` template or a
`/dashboard/info-sources/` or `/dashboard/source-revisions/` route updates this file in the same
commit. Shared mechanics: [UI.md](UI.md), [HTMX.md](HTMX.md).

## Information Sources (`/dashboard/info-sources/`)

**GET `/dashboard/info-sources/`** - paginated list. Query params: `url_contains` (ilike filter on the `url` column), `limit`, `offset`.

**GET `/dashboard/info-sources/new`** - create form. Fields: `url` (text input) + `source_specs` (JSON array textarea, validates JSON on blur); its hint names the family rule: `css` (HTML), `xpath` (HTML and XML) or `jsonpath` (JSON), with `full_page` pairing with either (#356).

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

**GET `/dashboard/source-revisions/`** - paginated list ordered by `captured_at desc, source_revision_id` (ascending tiebreak, unlike the InfoSource list above and the InfoItem list in [PAGES.md](PAGES.md)). Optional `info_source_id` filter (ULID). Columns: truncated fingerprint (link to detail), source URL (link to InfoSource detail), captured date, cache status pill (`.status-pill--cached` / `.status-pill--expired` / `.status-pill--missing`).

**GET `/dashboard/source-revisions/{id}`** - detail page, and the reference implementation of the SCREENS.md conventions. The header lives in `source_revisions/_detail_card.html`, extracted so clear-cache can swap it in place (root `#revision-card`): `.eyebrow` "Information Source Revision" above an `<h1>` titled with the copyable `source_revision_id`. `.detail-grid` carries the copyable full fingerprint and the Information Source on `.detail-grid__item--full` rows so long values extend horizontally; the Information Source value holds the internal source-detail link plus an `open_button` to the target URL. Then captured_at (UTC), size and media type (each if set), and cache status - a status pill plus the `content_cache_uri` (`open_button` when `http(s)`, otherwise copyable) and an expiry line. "View all revisions for this source →" deeplinks the list as `?info_source_id=`. A danger-zone clear-cache form shows only when `content_cache_uri` is set.

**POST `/dashboard/source-revisions/{id}/clear-cache`** - sets `content_cache_uri = NULL` and `content_cache_expires_at = NULL`. HTMX requests (`hx-post`, `hx-target="#revision-card"`, `hx-confirm`) get the re-rendered `_detail_card.html` swapped in place plus an `HX-Trigger: showFlash` success toast; non-HTMX requests fall back to a 303 to detail. No request body required.
