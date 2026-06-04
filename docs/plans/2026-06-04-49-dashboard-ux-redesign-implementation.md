# #49 — Dashboard UX Redesign Implementation Plan

**Design doc:** `docs/plans/2026-06-04-dashboard-ux-redesign-design.md`
**Branch:** `49-dashboard-ux-redesign`
**Worktree:** `.worktrees/49-dashboard-ux-redesign`

---

## Problem

The current dashboard mirrors the DB entity structure (flat lists of InfoItems, InfoSources, SourceRevisions, RepSpecs navigated independently). Operators work in terms of URLs and domains; the existing UI forces them to construct context from first principles on every session. There is also no hub framing — no single page that shows everything known about a registered InfoItem across the ecosystem.

## Approach

Deliver the redesign in eight sequential steps, each independently testable. Steps 1–2 are pure backend (data + API); steps 3–7 are dashboard changes; step 8 finalises docs and SDK. TDD throughout: red tests before implementation code.

The design doc is authoritative for all UX specifics. This plan tracks sequence and verifiability only.

## Tradeoffs / Alternatives

- **Single large PR vs. step-by-step:** Step-by-step chosen. Each step passes CI independently; rollback scope is limited if a step goes wrong.
- **Domain table now vs. derive at query time:** Explicit table chosen per design decision — Watcher already owns the concept, Archiver needs it for domain overview, suggestions, and status.
- **Tabs vs. vertical scroll on InfoItem detail:** Vertical scroll chosen; removes Alpine tab state, improves scannability, positions hub sections naturally at the bottom.

## Steps

- [ ] **1. Data layer** — Alembic migrations: (a) `create_domains_table`, (b) `add_domain_name_to_info_sources` (nullable FK + index), (c) `backfill_info_sources_domain_name` (extract hostname from `url`). `Domain` ORM model in `src/core/models/`. `get_or_create_domain(session, hostname)` helper in `src/core/tools/`. Tests: migration applies cleanly, helper upserts correctly, backfill sets expected values.

- [ ] **2. API layer** — `/api/v1/domains` CRUD (GET list with `is_active`/`archived` filters, GET one, PATCH upsert, DELETE with 409 guard, POST archive/restore). `DomainOut` + `DomainPatch` Pydantic schemas. `InfoSourceOut` gains `domain_name: str | None`. `GET /api/v1/info-sources` gains `?domain_name=` filter. Tests: all six domain routes, domain_name in InfoSource responses, list filter. SDK methods deferred to step 8.

- [ ] **3. Nav + Home page** — Nav: promote Domains before Information Items in the REGISTRY group. Home: single primary CTA ("Register Information Item"), secondary "Browse Information Items" link only; expand health strip to Archiver + Watcher (if `WATCHER_BASE_URL` set) + Redis; rename "Recent Changes" → "Recent Activity", add Item column; add Domain overview table (top 10 by InfoSource count, links to domain detail). Tests: home renders 200, domain overview appears when domains exist, health strip shows configured/unconfigured correctly.

- [ ] **4. Domain dashboard pages** — `GET /dashboard/domains/` list (paginated, `is_active` filter) and `GET /dashboard/domains/{name}` detail (read-only: notes, status badge, linked InfoSources). HTMX routes for inline notes edit (`POST /dashboard/domains/{name}/notes`), archive (`POST /dashboard/domains/{name}/archive`), restore (`POST /dashboard/domains/{name}/restore`). Templates: `domains/list.html`, `domains/detail.html`. Tests: list shows domains, detail shows linked sources, archive/restore toggle status.

- [ ] **5. `sortableChips` Alpine component** — Register `Alpine.data('sortableChips', factory)` in `main.js`. State: `sort` (frequency / asc / desc), reactive `chips` array. Sort controls: three `.btn--ghost` / `.btn--active` pill buttons. Server embeds `data-frequency` and `data-label` on chip `<button>` elements; factory reads them from the DOM on init. JS unit tests (Vitest): default sort is frequency-descending, setSort('asc') re-orders alphabetically, chip click fires expected event. Document in `docs/UI.md`.

- [ ] **6. Registration flow** — Routes under `src/dashboard/routes/register.py`: `GET/POST /dashboard/register`, `GET /dashboard/register/url-check`, `GET /dashboard/register/suggest-specs`, `POST /dashboard/register/preview`. Templates: `register/step1.html`, `register/step2.html`, `register/step3.html`, `register/step4.html`, partials `_url_check.html` (domain badge + Case A/B/C cards), `_spec_suggestions.html` (sortableChips), `_preview_result.html`. `owner` auto-populated from `current_user.id`; `rep_fields` omitted. Atomic submit: `get_or_create_domain` → `create_info_source` → `create_info_item` → `add_info_source` → 303 to detail. Redirect `/dashboard/info-items/new` → 301 to `/dashboard/register`. Tests: happy path creates InfoItem + InfoSource + binding; Case A shows existing items; Case B offers bind-existing; invalid URL re-renders step 1; invalid specs re-renders step 2; preview returns extracted text.

- [ ] **7. InfoItem detail hub page** — Replace tabbed detail with vertical-scroll 5-section layout. Sections in order: (1) Overview (domain badge, copy-ULID button), (2) Information Sources (primary binding highlighted, domain-check hint on bind form), (3) Watcher stub (domain + "View in Watcher →" link), (4) Replicator (Rep Fields sub-section with `sortableChips` + `jsonFieldEditor` + `PATCH /dashboard/info-items/{id}/rep-fields` inline save; Replication Specs sub-section with assign form and 501-stub suggest button; integration stub copy), (5) Revision History (last). Tests: all sections render, rep_fields inline save persists, existing binding tests pass (no regressions).

- [ ] **8. Docs + SDK + CHANGELOG** — SDK: add `list_domains`, `get_domain`, `upsert_domain`, `delete_domain`, `archive_domain`, `restore_domain` to `ArchiverClient`; regenerate generated client; bump to minor version. Update `AGENTS.md` route table. Update `docs/UI.md`: `sortableChips` component catalogue entry, all new `/dashboard/register/*` and `/dashboard/domains/*` routes, InfoItem detail section inventory. Update `docs/STYLE.md` if any new CSS patterns. Update `CHANGELOG.md`.

## Open Questions / Risks

- `WATCHER_BASE_URL` env var for health badge and "View in Watcher →" links — needs to be added to `/etc/archiver/.env` on the VM post-deploy. Document in AGENTS.md.
- Preview extraction in Step 6 calls `preview_extraction` which does a live HTTP fetch. In tests, use `respx` to mock the outbound request (same pattern as existing preview tests).
- The domain overview on the home page runs a GROUP BY query across `info_sources`. If the table grows large, this may need an index on `domain_name`. Add the index in migration step 1b alongside the FK.
