# archiver — Conventions Reference

The reasoning and worked examples behind the rules stated in `AGENTS.md`.

## Changelog trigger — what the path regex means

M1
cat "$S/D1_changelog.md"
cat <<'M2'

## Logging — plain-text `ExecStartPre` lines in journald

M2
cat "$S/D2_journald.md"
cat <<'M3'

## Error envelope — worked examples and the `kind` vocabulary

M3
cat "$S/D3_errors.md"
} > docs/CONVENTIONS.md

# --- docs/SCHEMA.md ---
{
cat <<'HDR'
# archiver — Schema & Domain Entities

Per-table contracts and invariants for the registry. Identifiers are verbatim —
see the never-rename rule in `AGENTS.md`.

## Entities

- **`InfoItem`** (`info_items`) — semantic anchor; carries domain meaning + `rep_fields` JSONB bag.
  `watcher_item_id VARCHAR(50)` — nullable; stores the Watcher-allocated WatchedItem ID once
  provisioned. `NULL` means not yet watched (use "Begin watching" in the dashboard or wait for
  the next `create_info_item` call with Watcher configured).
  **Fetch group invariant:** exactly one URL is fetched (the primary binding's InfoSource URL) and
  exactly one content-kind is produced (HTML/text or JSON). All specs in the bound InfoSource's
  `source_specs` list are evaluated against the same fetched bytes (no chaining off primary's
  extracted output). All specs in a list must share a content-kind family
  (`{css,xpath,regex,full_page}` ≠ `{jsonpath}`); see `src/core/source_spec_schema/families.py`.
- **`InfoSource`** (`info_sources`) — physical layer. `url TEXT NOT NULL` (non-unique — multiple
  InfoSources may share the same URL for different extraction strategies). `source_specs JSONB`
  (mutable array): first element is the primary extraction spec; subsequent elements are
  cross-check alternatives for selector-rot detection. Each spec: `{schema_version, extraction,
  fingerprint}` — no `target` section; URL is on the InfoSource directly.
- **`SourceRevision`** (`source_revisions`) — content-addressed snapshot. Identity is `(info_source_id, content_fingerprint)`; fingerprint is always `sha256:<hex>`.
- **`InfoItemSource`** (`info_item_sources`) — operator-declared item↔source binding. No `role`
  column — every binding is a primary binding. Two distinct states:
  - **Current primary** — the one active row (`deactivated_at IS NULL`). Enforced one-per-InfoItem
    by partial unique index `uq_info_item_sources_active`. Its InfoSource URL is what Watcher
    fetches each tick.
  - **Previous primary** — a deactivated row (`deactivated_at IS NOT NULL`). Preserved indefinitely
    as succession history. Watcher may continue watching previous primaries for unanticipated
    changes.

- **`RepSpec`** (`rep_specs`) — replication specification. JSONB `document` carries provider config, `credentials_alias`, `path_template`, `required_fields`. Per-provider sub-schemas under `src/core/rep_spec_schema/providers/`.
  **Tiered mutability** (#83): `name` always editable; `document` editable only while the RepSpec is a
  *draft* — zero `info_item_rep_specs` rows, active **or** deactivated; `provider` frozen always.
  `updated_at` is nullable and never backfilled (NULL = never edited). An assigned spec is frozen
  because its assignment rows assert which document produced the artefacts at their `public_url`;
  clone + migrate is #95. See `docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md`.
- **`InfoItemRepSpec`** (`info_item_rep_specs`) — effective-dated assignment + `public_url` writeback target.
- **`ChangesOutboxRow`** (`changes_outbox`) — pending change-bus event awaiting publication.

The Phase 1–3a `InfoSpec` model has been retired. Avoid any new references to `info_spec*` outside historical alembic migration files. The "Archiver" rename was service-name-only; `info_*` table prefix and `information` schema preserved per design decision.
