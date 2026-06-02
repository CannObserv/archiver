---
title: InfoSource simplification — implementation plan
date: 2026-06-02
status: draft
---

# InfoSource Simplification — Implementation Plan

## Problem

The InfoSource model carries unnecessary complexity from the fragment concept: a
`parent_info_source_id` FK, an XOR root/fragment constraint, a `role` column on
`InfoItemSource`, and per-fragment binding logic in `bind_info_source`. With `sub_aspect`
removed, fragments serve only cross-check extraction — a purpose that fits naturally on
the InfoSource itself as a spec list. The schema is harder to reason about than the
domain warrants.

Design doc: `docs/plans/2026-06-02-info-source-simplification-design.md` (issue #48).

## Approach

Work through the stack bottom-up in TDD order: spec schema → ORM + migration → core
tools → API routes + schemas → bus payload → dashboard → SDK. Each layer's tests go
green before the next layer starts. A single Alembic migration handles all DB changes at
once; it includes data guards for any surviving fragment rows so it fails loudly rather
than silently losing data.

## Tradeoffs / alternatives

- **Incremental migration (fragment rows → merged source_specs, then drop columns)** —
  rejected; no production data exists yet, so a clean-break migration with a guard is
  simpler and safer than a two-phase data migration.
- **Keep `url` as computed column from `source_specs[0].target.url`** — rejected; creates
  positional semantics and deactivation ambiguity, as discussed in the design session.
- **Keep `source_specs` immutable, require succession for spec changes** — rejected;
  forces URL succession just to tune a selector, which breaks the natural lifecycle.

## Steps

1. **Update `source_spec_schema/v1.json`** — remove the `target` section entirely. Update
   `SourceSpecValidator` and its tests. Verify `uv run pytest tests/core/source_spec_schema/`
   green.

2. **Update `InfoSource` ORM model** — replace `source_spec` (JSONB object) + computed
   `url` + `parent_info_source_id` + `schema_version` with `url TEXT NOT NULL` (proper
   column, non-unique) + `source_specs JSONB NOT NULL`. Drop XOR check constraint,
   `UniqueConstraint` on url, and fragment pagination index. Add a plain `Index` on `url`.
   Update model tests.

3. **Update `InfoItemSource` ORM model** — drop `role` column, drop
   `ck_info_item_sources_role_values` CHECK constraint. Simplify the partial unique index
   condition from `deactivated_at IS NULL AND role IS NULL` → `deactivated_at IS NULL`.
   Delete `FRAGMENT_ROLES`, `FragmentRole` from `models/__init__.py`. Update model tests.

4. **Write Alembic migration** — single migration handling all of steps 2–3. Include data
   guards:
   - Fail if any `info_sources` row has `parent_info_source_id IS NOT NULL` (no fragments
     survive).
   - Fail if any `info_item_sources` row has `role = 'cross_check'` (no fragment bindings
     survive).
   Rename `source_spec` → `source_specs` (column rename, JSONB stays as-is for now; data
   shape update — wrapping existing objects into single-element arrays — handled in the
   same migration). Add `url` column populated from `source_spec->'target'->>'url'`.
   Apply `uv run alembic upgrade head`.

5. **Update `create_info_source` tool** — accept explicit `url: str` and
   `source_specs: list[dict]` instead of `source_spec: dict`. Remove all fragment/parent
   logic and `DuplicateUrlError`. Add validation: list non-empty; each element validates
   against the updated spec schema; all elements share a content-kind family. Apply URL
   canonicalization to the explicit `url` input. Update tool tests.

6. **Update `bind_info_source` tool** — remove `role` parameter and all shape/parent/family
   validation. Keep only: InfoItem exists, InfoSource exists, no active binding already
   exists (collision guard). Update tool tests.

7. **Add `update_info_source_specs` tool** — validates and persists a new `source_specs`
   list on an existing InfoSource (`url` immutable; specs mutable). Same family + schema
   validation as create. Write tool tests first.

8. **Update API schemas and routes** —
   - `InfoSourceCreate`: replace `source_spec` with `url` + `source_specs`.
   - `InfoSourceOut`: same rename; expose `url` as top-level field.
   - Remove `DuplicateUrlError` 409 handling from `POST /info-sources`.
   - Add `PATCH /info-sources/{id}/source-specs` wired to the new tool.
   - Add `?url=` exact-match filter to `GET /info-sources`.
   - `InfoItemSourceCreate`: remove `role` field.
   - `InfoItemSourceOut`: remove `role` field.
   - Update API tests; verify `uv run pytest tests/api/` green.

9. **Update bus event payload** — remove `role` from `InfoItemBinding`; bump
   `schema_version` on `SourceRevisionCapturedEvent` from `1` to `2`. Update outbox /
   integration tests.

10. **Update dashboard** — InfoSource create form: replace `source_spec` textarea with
    `url` input + `source_specs` textarea. InfoSource detail: show `url` prominently,
    `source_specs` as formatted JSON. Bind-source form on InfoItem detail: remove role
    selector. InfoSource list: add URL search input. Update `docs/STYLE.md` and
    `docs/UI.md` per conventions. Update dashboard tests.

11. **Update SDK to v4.0.0** — regenerate (or hand-update) generated models to remove
    `InfoItemSourceCreateRoleType0`, update `InfoItemSourceCreate`, `InfoSourceCreate`,
    `InfoSourceOut`. Update hand-written `client.py`: `create_info_source(url, source_specs)`,
    `add_info_source` loses `role`, add `update_info_source_specs(id, source_specs)`.
    Bump `pyproject.toml` version. Update SDK tests and CHANGELOG.

12. **Full suite + smoke** — `uv run pytest` all green. Run `bash scripts/smoke_phase4.sh`
    against the dev server to confirm the end-to-end authoring loop.

## Open questions / risks

- **Watcher coordinated deploy.** Watcher currently reads `source_spec` (singular object)
  and `source_spec->'target'->>'url'` from InfoSource API responses. After this ships,
  Watcher must be updated to read `source_specs` (array) and top-level `url`. Deploy
  order: Archiver first, Watcher immediately after. Watcher will error on old response
  shape during the gap — plan the window.

- **Bus event consumers.** `schema_version: 2` on `source_revision_captured` removes
  `bindings[*].role`. Any consumer that branches on `role` (Watcher selector-rot logic,
  Notifier filters) must be updated in the same deploy window.

- **Migration data guard sensitivity.** The guards fail loudly on any surviving cross_check
  binding or fragment InfoSource row. If the dev DB has any from manual testing, they must
  be cleaned up before `alembic upgrade head` can run.

- **`url` canonicalization.** Currently applied inside `create_info_source` via
  `url_canonicalization.py`. Confirm the canonical form is applied to the new explicit
  `url` input in step 5; no change to the canonicalization logic itself is expected.
