# InfoSource Simplification — Design

**Date:** 2026-06-02
**Status:** Approved

---

## Goal

Simplify the InfoSource / InfoItemSource data model by eliminating the fragment concept
and collapsing cross-check extraction specs onto the InfoSource itself. The result is a
flatter registry: InfoItem → InfoSource (via InfoItemSource) → SourceRevisions, with no
parent/child InfoSource relationship and no role semantics on bindings.

This work follows the removal of `sub_aspect` (committed 2026-06-02), which left
`cross_check` as the only fragment role and made the redundancy of the fragment model
obvious.

---

## Approved Approach

**Promote `url` to a first-class column on InfoSource. Replace the single `source_spec`
JSONB object with a mutable `source_specs` JSONB array. Drop all fragment machinery.**

---

## Key Decisions

### 1. `url` is a first-class column — not embedded in specs, not unique

`InfoSource.url` becomes a plain `TEXT NOT NULL` column with a non-unique index for
lookup. Embedding `target.url` inside a spec created positional semantics (`source_specs[0]`
must own the URL) and complicated deactivation reasoning. As a top-level column it is the
immutable identity of the InfoSource; the spec list carries only extraction configuration.

URL is **not** unique because multiple InfoSources at the same URL are valid and expected —
different InfoItems can derive distinct semantic content from the same page using different
extraction strategies.

### 2. `source_specs` replaces `source_spec` — mutable JSONB array

Each element: `{schema_version, extraction, fingerprint}` — no `target` section.

- **Order is meaningful:** the first spec is the primary extraction strategy; subsequent
  specs are cross-check alternatives (selector-rot detection, fallback). Watcher runs all
  specs against the same fetched bytes.
- **Mutable:** operators can update the spec list via `PATCH /info-sources/{id}` without
  URL succession. `url` is immutable; `source_specs` is configuration.
- **Validation at write time:** list non-empty; each element validates against the updated
  spec schema (no `target` section); all elements must share a content-kind family
  (`html_text`: css/xpath/regex/full_page; `json`: jsonpath).

### 3. Fragment concept eliminated

`InfoSource.parent_info_source_id`, the XOR check constraint, and the fragment pagination
index are dropped. There is no longer a root/fragment distinction. Every InfoSource is
URL-bearing.

Consequence: the `source_spec_schema/v1.json` `target` section is removed. The schema
validates `{schema_version, extraction, fingerprint}` only.

### 4. `InfoItemSource.role` dropped

With fragments gone, every binding is simply "this InfoItem tracks this InfoSource."
`deactivated_at` already distinguishes the current primary (active) from succession
history (deactivated). The `role` column, `FRAGMENT_ROLES` constant, `FragmentRole` type,
and the role CHECK constraint are all removed.

The partial unique index condition simplifies from
`deactivated_at IS NULL AND role IS NULL` → `deactivated_at IS NULL`.

### 5. `DuplicateUrlError` / 409 on duplicate URL removed

With URL no longer unique, `POST /info-sources` always creates a new row. Operators
discover existing InfoSources for a URL via `GET /info-sources?url=…` (see §6).

### 6. URL search endpoint

`GET /info-sources?url=…` (exact match, paginated) is added so operators can check
whether an InfoSource for a given URL already exists before creating a new one. Complements
the existing name-search on InfoItems.

### 7. Bus event payload: `InfoItemBinding.role` removed

The `source_revision_captured` event's `bindings[*].role` field is removed. Consumers
that branched on `role` to filter primary vs. fragment bindings no longer need to — every
binding in the payload represents an active primary. This is a breaking change to the
event schema; `schema_version` on `SourceRevisionCapturedEvent` bumps to `2`.

### 8. SDK — breaking change, major version bump

The combined effect of `source_spec` → `source_specs`, `url` as explicit input,
`role` removal from `add_info_source`, and 409/DuplicateUrl removal constitutes a
breaking API change. The archiver-client SDK bumps to v4.0.0.

---

## Final Schema

```
information.info_sources
  info_source_id  ULID PK
  url             TEXT NOT NULL                 -- immutable; non-unique; indexed
  source_specs    JSONB NOT NULL                -- mutable array of extraction configs
  created_at      TIMESTAMPTZ

information.info_item_sources
  info_item_id    ULID FK → info_items   (PK)
  info_source_id  ULID FK → info_sources (PK)
  created_at      TIMESTAMPTZ
  deactivated_at  TIMESTAMPTZ NULL
  UNIQUE INDEX where deactivated_at IS NULL     -- one active binding per InfoItem

-- Unchanged:
information.info_items                          -- name, description, owner, rep_fields
information.source_revisions                    -- (info_source_id, content_fingerprint)
information.info_item_source_revisions          -- append-only per-item revision history
information.rep_specs
information.info_item_rep_specs
information.changes_outbox
information.app_users
information.api_keys
```

---

## Out of Scope

- **Watcher fetch deduplication.** When multiple active InfoSources share the same URL,
  Watcher is responsible for fetching that URL once and fanning the bytes to each
  InfoSource's spec list. The Archiver registry is agnostic to fetch scheduling.
- **Per-spec extraction fingerprinting.** SourceRevision fingerprints the fetched bytes at
  the InfoSource level. Individual spec extraction results are not separately fingerprinted
  or stored.
- **InfoSource mutation history / audit log.** `source_specs` is mutable with no version
  history. If spec history becomes important, a separate `info_source_spec_revisions` table
  can be added later.
- **Sub-page semantic fragments as InfoSources.** Content with distinct semantic meaning
  extracted from a sub-page region is modelled as its own InfoItem with its own InfoSource,
  not as a fragment of a parent InfoSource.
