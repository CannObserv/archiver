# Archiver Dashboard — UX Redesign Design

**Date:** 2026-06-04
**Status:** Approved
**Supersedes:** `docs/plans/2026-05-19-archiver-dashboard-design.md` (structural UX only — tech stack, auth, and CSS system unchanged)

---

## Goal

Replace the current DB-mirror navigation model with task-oriented, workflow-first flows. Archiver is the central registry and hub control plane for the CannObserv ecosystem; the dashboard should reflect that framing rather than exposing internal entity structure. Immediate focus: registration and authoring. Hub vision (cross-service status per InfoItem) is designed in from the start and filled in progressively as sibling service APIs mature.

---

## Approach

**Workflow-first + domains as first-class concept.** Watcher already has a `domains` table. Archiver adopts a minimal mirror of it (no rate-limiter columns) and uses it to power domain-pattern suggestions throughout the registration and authoring flows. The InfoItem detail page becomes a hub page — vertical scroll of sections, not tabs — with stub sections for Watcher and Replicator status that are visible now and filled in as integrations mature.

Tech stack, auth, and CSS system are unchanged from the original dashboard design.

---

## Key Decisions

### 1. Domains table

New `information.domains` table — minimal mirror of Watcher's concept:

| Column | Type | Notes |
|---|---|---|
| `id` | ULID PK | Internal identifier |
| `name` | VARCHAR(253) UNIQUE NOT NULL | Hostname (e.g. `regulations.cannabis.ca.gov`); matches Watcher's FK target |
| `notes` | TEXT NULL | Operator annotations |
| `is_active` | BOOLEAN NOT NULL DEFAULT TRUE | Gates inclusion in suggestions and domain overview |
| `archived_at` | TIMESTAMPTZ NULL | Lifecycle state |
| `created_at` / `updated_at` | TIMESTAMPTZ | Standard audit fields |

**Excluded intentionally:** `min_interval`, `max_concurrency`, `current_interval`, `decay_window`, `last_request_at` — these are Watcher rate-limiter internals. Archiver has no rate-limiting role; if ever needed, read from Watcher API, do not mirror.

`info_sources` gains `domain_name VARCHAR(253) NULL REFERENCES information.domains(name) ON DELETE SET NULL`. Populated silently at `create_info_source` time via an internal `get_or_create_domain(session, hostname)` helper (upsert by name, commit in same transaction). Existing rows backfilled via a follow-on data migration.

`InfoItem.domain_name` is derived — follow active primary `InfoItemSource → InfoSource → domain_name`. No FK on `info_items`; expose as a computed property in the ORM model and API serializer.

Computed status (not persisted): `archived > inactive > active`. Watcher also has `backoff` — leave that as a stub label in the Archiver UI until the cross-service status API exists.

### 2. Registration flow (`/dashboard/register`)

Replaces `/dashboard/info-items/new` as the primary entry point. URL is **required** — source-free InfoItem creation is a historical anomaly, not a supported new path. Old `/dashboard/info-items/new` redirects to `/dashboard/register`.

#### Step 1 — URL

Single URL input (required, `type="url"`). On blur (HTMX `hx-trigger="change delay:300ms"`, `hx-get="/dashboard/register/url-check"`), a partial replaces the hint area below the input with one of four cards:

| Scenario | Card |
|---|---|
| URL is new; domain is new | Neutral badge "New domain — will be created automatically." |
| URL is new; domain known + active | Green badge "Known domain — `example.com`" + link to domain detail + count of existing sources on domain. |
| URL is new; domain inactive/archived | Yellow/red warning "This domain is marked inactive — confirm before proceeding." |
| URL already registered (Case A below) | "URL already registered" card — see §Edge cases. |
| URL canonicalises to an already-registered URL | Same as Case A, but shows the canonical URL explicitly. |
| Unbound InfoSource exists at URL (Case B) | Separate card — see §Edge cases. |

Step guard: URL must be non-empty and syntactically valid before Next is enabled (HTML5 `type="url"` + server-side `InvalidUrlError` on the check call).

#### Step 2 — Selector

Two panels (side-by-side on wide viewports, stacked on narrow):

**Suggestions panel** (left): HTMX-fetched on URL confirmation (`GET /dashboard/register/suggest-specs?url={url}`). Server queries `info_sources` where `domain_name = hostname AND deactivated_at IS NULL`, extracts `source_specs`, deduplicates by `algorithm + selector` combo, returns top 5 as `sortableChips` (see §Alpine components). Frequency count shown on each chip. Clicking a chip pre-fills the spec editor. If zero suggestions: "No existing selectors for this domain."

**Spec editor + preview** (right): `jsonFieldEditor` textarea for `source_specs` JSON array. Placeholder pre-populated with domain's most common algorithm if suggestions exist. "Preview extraction →" button fires `POST /dashboard/register/preview` with `{url, source_specs}`, renders `_preview_result.html` partial in an expandable panel:
- Extracted text (truncated at 500 chars, "show more" toggle).
- Content fingerprint prefix.
- Extraction errors in a red alert box if applicable.

Preview is optional — user can proceed without running it.

Step guard: `source_specs` must be a valid JSON array (client-side via `jsonFieldEditor`).

#### Step 3 — Metadata

- `name` (required; pre-populated from page `<title>` if the preview ran and returned a suggested name, otherwise blank)
- `description` (optional textarea)
- `owner` (auto-populated from the current AppUser; not free text — the dashboard user identity from proxy headers is the owner)

`rep_fields` is omitted here; editing it is deferred to the InfoItem detail screen. A follow-up issue (#50) tracks adding a Watcher configuration affordance to this step once the Watcher integration story is settled.

Name pre-population: `POST /dashboard/register/preview` response includes `suggested_name`; client writes it into the name input only if the field is currently empty.

#### Step 4 — Review & Submit

Read-only summary: URL, domain badge, selector summary (algorithm + selector string), name, description, owner (current user display name). "Edit" links back to each step without resetting state.

Single `POST /dashboard/register` — server executes atomically:
1. `get_or_create_domain(hostname)`
2. `create_info_source(url=url, source_specs=[...])`
3. `create_info_item(name=..., description=..., owner=current_user.id)`
4. `add_info_source(info_item_id, info_source_id)` (null role = primary)
5. Commit → 303 redirect to InfoItem detail.

On error: re-render at the failing step with sticky values. No reset to step 1.

#### Edge cases: URL already in the registry

**Case A — URL exists, bound to one or more active InfoItems**

"URL already registered" card at Step 1 shows:
- List of existing InfoItems bound to sources at this URL (name linked to detail).
- Summary of current `source_specs` in use (algorithms).
- Two actions (in prominence order):
  1. **"Register a new Information Item at this URL"** *(default, prominent)* — continues the flow. A second InfoSource at the same URL is valid (non-unique by design post-#48). Use when the user wants a different selector or a semantically distinct item at the same URL.
  2. **"Add a selector to an existing source"** *(secondary)* — short-circuits to the `POST /dashboard/info-sources/{id}/source-specs` edit form for that source. Use when the user wants to extend what's already being watched.

The listed InfoItem names are themselves links to their detail pages — no separate "Go to existing" action needed.

**Case B — URL exists as an InfoSource but not bound to any active InfoItem**

"Unbound source" card shows:
- "This URL has an existing Information Source with no active Information Item bound."
- Two actions:
  1. **"Register a new Information Item and bind this source"** *(default)* — at Step 4 submit, skips `create_info_source` and binds the existing InfoSource.
  2. **"Create a new source anyway"** *(secondary, not prominent)* — proceeds as if the URL were new.

**Case C — URL canonicalises to an already-registered URL**

Canonicalization runs server-side on the url-check call. Treat as Case A against the canonical form; show "Registered as `{canonical_url}`" in the card header.

### 3. InfoItem detail — hub page

Vertical scroll of five labelled sections. No tabs. Each section has a heading with a `border-bottom` separator. Sections 3–4 (Watcher, Replicator) sit at the bottom of their service group with lighter heading weight and muted background on stub content.

#### Section 1 — Overview

Name (h1), ULID (with copy-to-clipboard button), domain badge (derived from active primary source; links to domain detail; shows "No primary source" if unbound), description, owner (AppUser display name), created_at.

#### Section 2 — Information Sources

Table of active `InfoItemSource` bindings: URL (linked to InfoSource detail + external ↗ link), primary indicator (badge), bound date. Primary row visually distinguished (left border accent or subtle background).

Below table: "Bind Existing Information Source" form — `info_source_id` input with same domain-check HTMX hint as registration Step 1. Deactivation confirmation dialog notes when the source being removed is the primary.

#### Section 3 — Watcher *(stub)*

Muted section. Shows: domain name, primary URL, "View domain in Watcher →" link (Watcher dashboard URL for that hostname, constructed from `WATCHER_BASE_URL` env var if set). Static copy: "Watcher integration — cadence, last fetch, and health will appear here once cross-service status is available."

Future (tracked in #50): Watcher configuration affordance — cadence, last fetch timestamp, HTTP status, backoff state, next scheduled fetch, pause/resume actions via Watcher API.

#### Section 4 — Replicator

Contains all Replicator-related configuration (Rep Fields and Replication Specs), plus a stub for future integration. Replicator is TBD; this section is functional for authoring config but the integration half is stubbed.

**Rep Fields sub-section:**

`sortableChips` component loaded via HTMX on section load (`GET /dashboard/info-items/{id}/suggest-rep-fields`). Server queries `rep_fields` bags of all InfoItems on the same domain (active only), extracts unique keys, counts frequency. Returns chips with `data-frequency` and `data-label` attributes. Pre-sorted by frequency descending; component allows client-side resort to A→Z or Z→A. Chip label format: `key.path ×N` (muted suffix). Clicking a chip inserts the key with empty value into the `jsonFieldEditor` below.

`jsonFieldEditor` textarea for the `rep_fields` JSON object. Inline save via HTMX `PATCH /dashboard/info-items/{id}/rep-fields` (new route). Re-renders section partial on success with a flash "Saved."

**Replication Specs sub-section:**

Table of active `InfoItemRepSpec` assignments: RepSpec name (linked to detail), provider badge, activated_at, public_url (inline edit via existing PATCH route), deactivate action.

Below table: assign form (RepSpec ID input). "Suggest RepSpec" button stubs a `GET /dashboard/info-items/{id}/suggest-rep-specs` route that returns 501 initially — wires up when domain-scoped RepSpec suggestion is implemented.

**Replicator integration stub:**

Muted copy at the bottom of the section: "Replicator integration — replication job history and public URL writeback will appear here once the Replicator service is available."

Future: job history, last run status, target storage path.

#### Section 5 — Revision History

Last 50 `InfoItemSourceRevision` rows ordered by `bound_at desc`. Columns: fingerprint prefix (linked to revision detail), captured_at, cache status pill. Positioned last — reference data rather than actionable configuration.

### 4. Home page

**Quick actions (top):** Single primary CTA: "Register Information Item" → `/dashboard/register`. Secondary text link: "Browse Information Items" (other entity lists are accessible via navigation).

**Service health strip:** Existing HTMX-polled Archiver badge plus: Watcher badge (polls `{WATCHER_BASE_URL}/health` if `WATCHER_BASE_URL` env var is set; shows "not configured" muted badge if unset), Redis badge (polls reachability of `ARCHIVER_REDIS_URL`; shows "not configured" if unset).

**Recent Activity** (replaces "Recent Changes"): adds **Item** column (InfoItem name linked to detail, "—" if revision not bound to an item) alongside existing Source, Revision, Observed columns. Table is item-centric rather than revision-centric.

**Domain overview** (new, below fold): top 10 domains by InfoSource count descending. Columns: Domain (linked to `/dashboard/domains/{name}`), Sources (count), Items (derived count of InfoItems with a primary source on this domain), Status badge. Requires `domains` table.

### 5. Navigation

```
[Home]

─ REGISTRY ──────────
  Domains             ← first in section
  Information Items

─ SOURCES ───────────
  Information Sources
  Source Revisions

─ REPLICATION ───────
  Replication Specs

─ SETTINGS ──────────
  API Keys
```

### 6. Alpine.js — new `sortableChips` component

Registered in `main.js` as `Alpine.data('sortableChips', factory)` before `Alpine.start()`.

**Factory args:** `initialChips: Array<{label: string, frequency: number}>`, `defaultSort: 'frequency' | 'asc' | 'desc'` (default `'frequency'`).

**State:** `sort: string`, `chips: Array` (reactive, re-sorted on `sort` change).

**Methods:** `setSort(s)` — sets `sort`, re-orders `chips` in place.

**Sort control:** a strip of three pill buttons above the chip row — `[Frequency ▾]`, `[A → Z]`, `[Z → A]`. Active button gets `.btn--active`; inactive get `.btn--ghost`. Sort is purely client-side; server embeds `data-frequency` and `data-label` on each chip element at render time.

**Chip format:** `key.path ×N` where `×N` is a muted frequency suffix. Clicking a chip fires a `@click` that writes the key into the target editor (passed as a `targetProp` factory arg, analogous to `jsonFieldEditor`'s `rootProp`).

Reusable: selector suggestion chips in the registration Step 2 panel use the same component.

---

## New Routes

### Dashboard

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/dashboard/register` | Registration flow (step 1) |
| `POST` | `/dashboard/register` | Submit registration (atomic) |
| `GET` | `/dashboard/register/url-check` | HTMX: domain + URL existence check (partial) |
| `GET` | `/dashboard/register/suggest-specs` | HTMX: selector suggestions for URL (partial) |
| `POST` | `/dashboard/register/preview` | HTMX: preview extraction (partial) |
| `GET` | `/dashboard/domains/` | Domain list |
| `GET` | `/dashboard/domains/{name}` | Domain detail (read-only: notes, status, linked sources) |
| `POST` | `/dashboard/domains/{name}/notes` | HTMX inline notes edit |
| `POST` | `/dashboard/domains/{name}/archive` | Archive domain |
| `POST` | `/dashboard/domains/{name}/restore` | Restore domain |
| `PATCH` | `/dashboard/info-items/{id}/rep-fields` | Inline rep_fields save (new) |

`/dashboard/info-items/new` → 301 redirect to `/dashboard/register`.

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/domains` | List domains (filter: `is_active`, `archived`) |
| `GET` | `/api/v1/domains/{name}` | Get one domain |
| `PATCH` | `/api/v1/domains/{name}` | Upsert domain (notes, is_active) |
| `DELETE` | `/api/v1/domains/{name}` | Delete; 409 if InfoSources reference it |
| `POST` | `/api/v1/domains/{name}/archive` | Archive |
| `POST` | `/api/v1/domains/{name}/restore` | Restore |

`GET /api/v1/info-sources` gains `?domain_name=` filter.
`InfoSourceOut` gains `domain_name: str | None`.

---

## Data Migrations (ordered)

1. `create_domains_table` — `information.domains` with columns above.
2. `add_domain_name_to_info_sources` — nullable FK column + index.
3. `backfill_info_sources_domain_name` — data migration; extracts hostname from `url` for all root-shaped rows. Separate migration for auditability.

---

## SDK Changes

- New methods: `list_domains`, `get_domain`, `upsert_domain`, `delete_domain`, `archive_domain`, `restore_domain`.
- `InfoSourceOut` gains `domain_name: str | None`.
- Minor version bump (new surface, backward-compatible). CHANGELOG entry required.

---

## Living Docs

Any commit touching templates, JS modules, or `dashboard.css` must update `docs/UI.md` and `docs/STYLE.md` per existing convention. Required additions:
- `sortableChips` Alpine component entry in `docs/UI.md`.
- `/dashboard/register/*` and `/dashboard/domains/*` route entries in `docs/UI.md`.
- Rep Fields suggestion strip pattern in `docs/UI.md`.

---

## Out of Scope

- Watcher rate-limiter config (`min_interval`, `max_concurrency`) — Watcher-owned; Archiver surfaces a "View in Watcher →" link only.
- Global "Assign Replication Spec" flow — per-item only for now.
- Cross-service status polling (Watcher cadence, Replicator jobs) — stub sections present; integration deferred.
- Domain as a first-class entity in the SDK beyond what's listed above — no `DomainOut` in `InfoItemOut`; domain_name string is sufficient.
- Source-free InfoItem creation path — historical anomaly, not a supported new flow.
