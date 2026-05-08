---
title: Archiver v2 — Central Registry Architecture
date: 2026-05-08
status: approved (design)
trajectory: docs/research/2026-05-06-archiver-information-model.md
supersedes-implementation-of: docs/plans/2026-05-03-information-source-specifications-design.md (Phase 1–3a InfoItem ↔ InfoSpec model)
---

# Archiver v2 — Central Registry Architecture

## Goal

Evolve Archiver from the Phase 1–3a `InfoItem ↔ InfoSpec` model into the **central registry + authoring service** for the Cannabis Observer information layer. Watcher and the forthcoming Replicator become execution-side consumers; WordPress becomes a downstream display layer (separate design).

## Non-goals

- WordPress cache-table contract (deferred — needs its own design in the WP repo).
- Authoring CLI ergonomics (deferred — operators use the SDK directly until demand justifies a wrapper).
- `gdrive`/`ia` provider implementation details beyond the alias-resolved profile contract (Replicator-internal design).
- Multi-VM or distributed-cache deployment (MVP is single-VM `file://` cache; URI scheme is forward-compatible).

## Anchored decisions

These are the load-bearing choices that scoped the rest of the design. Each came out of the brainstorming interview and is recorded here so future readers know *why* the design has the shape it does.

1. **Driving force:** ecosystem-wide foundation. The v2 model under-girds Watcher, Replicator, and the WP redesign together — not any single one.
2. **Boundary (Option A — wide registry):** Archiver owns all five registry tables: `info_items`, `info_sources`, `source_revisions`, `rep_specs`, `info_item_rep_specs` — plus the two Item↔X join tables (`info_item_sources`, `info_item_source_revisions`). Watcher and Replicator own only their *operational* state (schedules, jobs).
3. **Pre-production freedom:** nothing depends on Archiver in a binding way. Schema cutover is a clean swap, no compat shim. Breaking SDK changes acceptable.
4. **Replicator status:** design-only, no code yet. We can stand it up greenfield against the v2 model.
5. **WP coordination:** WP redesign is underway; cache-table contract is its own design effort.
6. **Authoring location:** Archiver `/tools/*`. Bag normalization (`resolve_rep_fields`), spec validation, preview, propose-selectors all extend the existing v1 authoring surface.
7. **RepSpec schema/catalog location:** Archiver, alongside the SourceSpec schema. Per-provider sub-schemas under `src/core/rep_spec_schema/providers/`.
8. **Page-once cascade:** `info_sources.parent_info_source_id` enables cascade-from-a-single-fetch. XOR constraint on `(parent_info_source_id, url)` — a Source is either a root (has URL, no parent) or a fragment (has parent, no URL).
9. **Fingerprint algorithm:** SHA-256 over post-extraction, post-trim content. Stored as `sha256:<hex>` (prefixed for future algorithm migration). Simhash is no longer the dedup key; if retained anywhere, it's a Watcher-side significance signal on Change events.
10. **Provider credentials:** alias indirection. RepSpec carries a `credentials_alias` string; Replicator's deploy config (file/env) maps alias → bucket + creds. Single-tenant today, multi-tenant-ready by construction.
11. **Cache field semantics:** `content_cache_uri` is **authoritative-when-set**. The Watcher-side sweeper PATCHes the registry on file deletion (best-effort); Replicator's read-failure fallback is the safety net.

---

## Section 1 — Target Architecture

```
                             ┌──────────────────────────────────┐
                             │           ARCHIVER               │
                             │  (FastAPI + Postgres, port 8020) │
                             │                                  │
                             │  Registry tables:                │
                             │   • info_items                   │
                             │   • info_sources                 │
                             │   • source_revisions             │
                             │   • info_item_sources            │
                             │   • info_item_source_revisions   │
                             │   • rep_specs                    │
                             │   • info_item_rep_specs          │
                             │                                  │
                             │  Authoring /tools/*:             │
                             │   • validate_source_spec         │
                             │   • validate_rep_spec            │
                             │   • validate_rep_fields          │
                             │   • resolve_rep_fields           │
                             │   • fetch_and_render             │
                             │   • preview_extraction           │
                             │   • propose_selectors            │
                             │   • find_info_item               │
                             │   • create_info_item (atomic)    │
                             │   • assign_rep_spec              │
                             │   • bind_revision                │
                             │                                  │
                             │  Bus producer: info.changes      │
                             └─┬────────────┬────────────┬──────┘
                               │            │            │
                ┌──────────────┘            │            └──────────────┐
                │ archiver-client SDK       │                           │
                │                           │                           │
                ▼                           ▼                           ▼
        ┌───────────────┐         ┌──────────────────┐         ┌────────────────┐
        │   WATCHER     │         │    REPLICATOR    │         │   WORDPRESS    │
        │ (port 8010)   │         │ (port 8030, new) │         │ (display only) │
        │               │         │                  │         │                │
        │ POSTs source_ │         │ Subscribes       │         │ Out of scope:  │
        │ revisions on  │         │ info.changes;    │         │ separate WP    │
        │ fingerprint   │         │ executes per     │         │ design.        │
        │ shift via     │         │ active rep_spec; │         │                │
        │ outbox.       │         │ PATCHes          │         │                │
        │               │         │ public_url back  │         │                │
        │ Owns: schedule│         │ to Archiver.     │         │                │
        │ + Change      │         │                  │         │                │
        │ outbox + temp │         │ Owns: jobs +     │         │                │
        │ cache + sweep.│         │ provider clients │         │                │
        │               │         │ + profiles.      │         │                │
        └───────┬───────┘         └─────────┬────────┘         └────────────────┘
                │                           │
                │ writes via SDK            │ subscribes
                ▼                           │
            ┌─────────────────────────────────┐
            │   info.changes (Redis Stream)   │
            │   payload: source_revision_id,  │
            │            info_item_ids[]      │
            │            (event published     │
            │             from Archiver       │
            │             outbox)             │
            └─────────────────────────────────┘
```

### Role shifts vs. today

| Concern | Today (Phase 1–3a) | v2 |
|---|---|---|
| Authoritative URL+target spec | Watcher resolves *primary InfoSpec* per InfoItem | Each InfoItem has 1..N Sources via `info_item_sources`; each Source carries a SourceSpec. |
| Content versioning | Implicit in Watcher's local snapshots | Explicit `source_revisions` table; `(source_id, fingerprint)` unique. Items reference revisions. |
| Replication assignments | Doesn't exist | `info_item_rep_specs` join with effective dating + `public_url` writeback. |
| Replication-fields bag | Doesn't exist | `info_items.rep_fields` JSONB; normalized via `/tools/resolve-rep-fields`. |
| RepSpec catalog | Doesn't exist | `rep_specs` table; per-provider schema docs in Archiver. |
| Change-bus producer | Watcher | Archiver (registry is system-of-record for "new revision exists"). |
| Change-bus payload | `info_item_id, info_spec_id` | `source_revision_id, info_item_id, info_source_id, info_item_ids[]`. |
| Operator authoring | Archiver `/tools/*` (validate/fetch/preview) | Same surface, expanded for rep_spec / rep_fields / assignment. |
| Page-once cascade | Each fragment fetch is a separate URL hit | `info_sources.parent_info_source_id`: one fetch per root, fragments cascade from cached bytes. |

### Deliberate exclusions from Archiver's scope

- Watcher's schedule, fetch history, rate-limit state, change detection state.
- Replicator's job queue, worker state, retry counters, provider credentials.
- WP's display-side data shape.
- The temp-cache filesystem itself (Watcher owns the directory and the sweeper).

---

## Section 2 — Data-model Cutover

Greenfield: drop `information.info_specs`, create the v2 tables in a single Alembic migration. No compat shim.

### v2 schema

All tables remain in the `information` schema; the `info_*` prefix is preserved per CLAUDE.md vocabulary policy.

```sql
-- Semantic layer
information.info_items
  info_item_id            ULID PK
  name                    VARCHAR(200)  NOT NULL
  description             VARCHAR(2000) NULL
  owner                   VARCHAR(200)  NULL
  rep_fields              JSONB         NOT NULL DEFAULT '{}'   -- the bag
  created_at, updated_at

-- Physical layer (replaces info_specs)
information.info_sources
  info_source_id          ULID PK
  parent_info_source_id   ULID NULL  FK → info_sources(info_source_id) ON DELETE RESTRICT
  source_spec             JSONB         NOT NULL
  schema_version          INTEGER       NOT NULL
  url                     TEXT GENERATED ALWAYS AS (source_spec->'target'->>'url') STORED
  created_at
  CHECK ((parent_info_source_id IS NULL) != (url IS NULL))   -- XOR: root has URL, fragment has parent
  UNIQUE (url) WHERE url IS NOT NULL
  INDEX (parent_info_source_id) WHERE parent_info_source_id IS NOT NULL

information.source_revisions
  source_revision_id        ULID PK
  info_source_id            ULID FK → info_sources
  content_fingerprint       TEXT          NOT NULL    -- 'sha256:<hex>'
  captured_at               TIMESTAMPTZ   NOT NULL
  content_size_bytes        BIGINT        NULL
  content_media_type        TEXT          NULL
  content_cache_uri         TEXT          NULL        -- temporary; authoritative-when-set
  content_cache_expires_at  TIMESTAMPTZ   NULL        -- best-effort hint from sweeper
  UNIQUE (info_source_id, content_fingerprint)
  INDEX (info_source_id, captured_at DESC)

-- Item ↔ Source binding (operator-declared)
information.info_item_sources
  info_item_id            ULID FK → info_items   ON DELETE CASCADE
  info_source_id          ULID FK → info_sources
  role                    VARCHAR(50)  NOT NULL   -- 'primary' | 'secondary' | …
  created_at
  deactivated_at          TIMESTAMPTZ  NULL       -- effective-dated; NULL = active
  PRIMARY KEY (info_item_id, info_source_id)
  UNIQUE (info_item_id, role) WHERE deactivated_at IS NULL AND role = 'primary'

-- Item ↔ Revision binding (content history; append-only)
information.info_item_source_revisions
  info_item_id            ULID FK → info_items   ON DELETE CASCADE
  source_revision_id      ULID FK → source_revisions
  bound_at                TIMESTAMPTZ  NOT NULL
  PRIMARY KEY (info_item_id, source_revision_id)
  INDEX (info_item_id, bound_at DESC)

-- Replication catalog
information.rep_specs
  rep_spec_id             ULID PK
  provider                VARCHAR(50)  NOT NULL    -- 'gcs' | 'gdrive' | 'ia' | …
  name                    VARCHAR(200) NOT NULL
  schema_version          INTEGER      NOT NULL
  document                JSONB        NOT NULL    -- provider config + credentials_alias + path_template + required_fields
  created_at
  INDEX (provider)

-- Item ↔ RepSpec assignment
information.info_item_rep_specs
  id                      ULID PK
  info_item_id            ULID FK → info_items   ON DELETE CASCADE
  rep_spec_id             ULID FK → rep_specs
  activated_at            TIMESTAMPTZ  NOT NULL
  deactivated_at          TIMESTAMPTZ  NULL
  public_url              TEXT         NULL
  INDEX (info_item_id) WHERE deactivated_at IS NULL
  INDEX (rep_spec_id)
```

### Why two Item↔X join tables, not one

The research doc lists `source_revisions` as a list directly on `InfoItem`. Splitting that into two tables honors a real distinction:

- **`info_item_sources`** — operator says "this item tracks these URLs." Mostly stable; an empty source list is valid for a brand-new item before its first capture.
- **`info_item_source_revisions`** — append-only history of which revisions this item has been pinned to over time. Watcher writes a row on every fingerprint shift; operator can write one at item creation to back-pin to a pre-existing revision.

"Current content" for an item is the most-recent revision per active source — a query, not a column.

### Page-once cascade — InfoSource parent/child semantics

Schema invariant: a Source is **either** a root (URL-bearing) **or** a fragment (parent-bearing), never both. Encoded as `CHECK ((parent_info_source_id IS NULL) != (url IS NULL))`.

**Cascade execution lives in Watcher** (it has the bytes in hand and owns scheduling). On a fetch:

1. Watcher fetches the root's URL once.
2. Hashes the root extraction (SHA-256). If the root SourceRevision already exists → fast-path: skip cascade, no new revisions, no events.
3. Otherwise: insert root SourceRevision, then enumerate `parent_info_source_id = root.id` Sources and run their extraction against the *cached page bytes*. Insert revisions and emit events for whichever fragments shifted.

**URL canonicalization at write time:** strip `#fragment`, lowercase scheme+host, normalize percent-encoding, trim trailing slashes. If the fragment is semantically meaningful (anchor identifies the section to extract), encode it as `source_spec.target.fragment`. This keeps `UNIQUE(url)` coherent.

**Query strings:** keep verbatim by default. Allow per-Source override via `source_spec.target.url_canonicalization` (e.g., `{ "strip_query_keys": ["utm_source", "utm_medium"] }`).

**SourceSpec schema variants:** `RootSourceSpec` (requires `target.url`, optional `target.fetch`) vs. `FragmentSourceSpec` (extraction + fingerprint only — no URL, no fetch policy). Schema enforces this with a discriminator.

**Authorization rule** ("Watcher only schedules fetches for Sources with a URL") is enforced naturally by the schema — fragment Sources have `url IS NULL`.

**Depth:** schema permits arbitrary chain depth; cascade walks the parent chain to find the root for fetch. In practice depth = 2 covers the expected workload.

### Fingerprint algorithm — SHA-256

Locked decision:

- **Algorithm:** SHA-256 over post-extraction, post-trim content.
- **Storage:** `sha256:<hex>` (prefixed string). 71 chars total. Future algorithm migration possible without schema change.
- **Domain rules:**
  - Text: UTF-8 encode after extraction normalization (strip surrounding whitespace, normalize line endings to `\n`).
  - Binary (PDF, etc.): raw bytes after content-type-appropriate extraction (e.g., PDF → extracted text, not raw PDF bytes).
- **`fingerprint.algorithm` removed from SourceSpec schema.** Implicit `sha256` everywhere; YAGNI on the algorithm enum.

Simhash retains a possible role as a Watcher-side significance signal on Change events, but is not the dedup key.

### Provider credentials — alias indirection

RepSpec carries a *name*; Replicator's deployment binds the name to actual creds + storage target.

```jsonc
// rep_specs.document
{
  "provider": "gcs",
  "credentials_alias": "org_x",
  "path_template": "{org.acronym_slug}/{event.year}/{event.date_segment}/{file.label_slug}.{file.ext}",
  "required_fields": ["org.acronym", "event.date_segment", "file.label", "file.ext"],
  "object_options": { "storage_class": "ARCHIVE", "cache_control": "public, max-age=86400" }
}
```

**Replicator's deploy config** (file or env-derived; not in DB to start):

```yaml
profiles:
  default:
    provider: gcs
    bucket: cannobserv-archive-default
    credentials_path: /etc/replicator/keys/default.json
  org_x:
    provider: gcs
    bucket: cannobserv-archive-org-x
    credentials_path: /etc/replicator/keys/org_x.json
  ia_default:
    provider: ia
    api_key_env: IA_API_KEY_DEFAULT
```

**Validation boundary:**
- Archiver's `validate_rep_spec` checks structure (provider known, `path_template` parses, `required_fields` are valid bag paths).
- Archiver does *not* validate that `credentials_alias` resolves — that's Replicator's job at job-execution time (clean 400 if unknown alias).
- Optional later: a `GET /providers/{alias}/health` endpoint on Replicator that Archiver's `validate_rep_spec` can call for early feedback. Not required v1.

**Bucket name lives in the profile, not the RepSpec** — credentials and bucket are typically deployed as a unit. RepSpec stays portable across environments.

### Temp cache protocol — `content_cache_uri` lifecycle

The cache field is **fetch-once across Watcher → cascade → Replicator**, not canonical storage.

**MVP scheme:** `file:///var/cache/archiver/<source_revision_id>.bin`. Single-VM; both Watcher and Replicator read locally. URI scheme is forward-compatible to `gcs://` / `s3://` later.

**Lifecycle protocol:**

1. **Watcher writes** the bytes to `/var/cache/archiver/<source_revision_id>.bin` *before* `POST /source-revisions`. POST body carries `content_cache_uri` + `content_cache_expires_at = now + TTL`. TTL default 600s.

2. **Cascade fragment extraction** in Watcher reads the same local file — no separate fetch.

3. **Sweeper** lives in Watcher (producer cleans up). Runs every 60s, deletes files older than TTL. **For each deleted file, PATCHes `/source-revisions/{id} {content_cache_uri: null, content_cache_expires_at: null}` as a best-effort follow-up.** Filename embeds `source_revision_id`; sweeper extracts the ULID directly.

4. **Replicator reads** the cache URI:
   - If field is `NULL` (sweeper got there first) or `content_cache_expires_at` is in the past → skip to fallback.
   - Open the file. On `ENOENT` → fallback.
   - On success → upload to provider, then `PATCH /info-item-rep-specs/{id} {public_url}`.
   - **Fallback:** PATCH the cache fields to NULL, then re-fetch the source URL via SourceSpec, **hash-verify against `content_fingerprint`**, upload. On hash mismatch → log + fail the job (revision is no longer producible from the URL; operator concern).

5. **Hash-verify on re-fetch is non-negotiable.** Without it, drift between Watcher's original capture and a later re-fetch could silently replicate different content under the same revision identity.

The sweeper PATCH is **best-effort, not transactional** — sweeper deletes the file regardless of Archiver availability. If the PATCH fails, log and drop; the read-failure path remains the safety net. Field semantics: "if non-NULL, *probably* readable; if NULL, definitely not."

**Configuration knobs (Watcher):**
- `WATCHER_CACHE_DIR` (default `/var/cache/archiver/`)
- `WATCHER_CACHE_TTL_SECONDS` (default `600`)
- `WATCHER_CACHE_SWEEP_INTERVAL_SECONDS` (default `60`)

**Future optimization (not MVP):** if sweep batches grow, add `PATCH /source-revisions:bulk-clear-cache {source_revision_ids: [...]}` to amortize round-trips.

### Schema-versioned documents

Three independently-versioned JSON Schema documents in `src/core/`:

- `source_spec_schema/v1.json` — root + fragment variants (replaces today's `info_spec_schema/v1.json`).
- `rep_spec_schema/v1.json` (envelope) + `rep_spec_schema/providers/{gcs,gdrive,ia}/v1.json` (per-provider sub-schemas).
- `rep_fields_schema/v1.json` — meta-schema for the bag's namespacing convention (`org.*`, `event.*`, `file.*`); RepSpec docs constrain *which* keys are required for a given assignment.

### Authoring tools — full v2 surface

| Tool | Status |
|---|---|
| `validate_source_spec` | Renamed from `validate_info_spec`; same behavior. |
| `validate_rep_spec` | New — schema-validate a candidate RepSpec doc against per-provider sub-schema. |
| `validate_rep_fields` | New — check an item's bag against a RepSpec's required vars. |
| `resolve_rep_fields` | New — domain-input → normalized bag (raw + slug forms). |
| `find_info_item` | Unchanged. |
| `fetch_and_render` | Unchanged. |
| `preview_extraction` | Now takes a `source_spec` doc (root or fragment). |
| `propose_selectors` | Unchanged. |
| `create_info_item` (atomic) | Reshaped — accepts `initial_source_spec` (creates Source + binds via `info_item_sources`) and optionally `initial_rep_spec_assignments`. |
| `assign_rep_spec` | New — bind an existing RepSpec to an InfoItem (writes `info_item_rep_specs` row). |
| `bind_revision` | New — operator-action variant of Watcher's automatic revision-pinning, for backfill scenarios. |

### Change-bus payload v2

```json
{
  "event_type": "source_revision_captured",
  "occurred_at": "2026-…",
  "info_source_id": "01HZZ…",
  "source_revision_id": "01HZZ…",
  "content_fingerprint": "sha256:…",
  "info_item_ids": ["01HZZ…", "01HZZ…"]
}
```

`info_item_ids` is denormalized into the event so subscribers (Replicator, Notifier) can route without a callback to Archiver. It's a snapshot of the binding at emit time.

**Producer:** Archiver. Insert SourceRevision → write outbox row in same transaction → background publisher drains to Redis Stream `info.changes`. Watcher just POSTs and forgets.

### Cutover mechanics

1. Drop `information.info_specs`.
2. Single Alembic migration creates the seven new tables + indices.
3. Bump `archiver-client` SDK to v1.0 (regenerate from new OpenAPI; no compat shim).
4. Watcher's `info_resolver.py` swap: `resolve_primary` → `resolve_root_sources_with_children(info_item_id) → list[ResolvedRootSource]`.

---

## Section 3 — Phased Path

### Dependency graph

```
Phase 4 — Archiver v2 (schema + tools + bus publisher + SDK v1.0)
   │
   ├──→ Phase 5 — Watcher refactor (parallel-able with Phase 6)
   │
   └──→ Phase 6 — Replicator stand-up (MVP: gcs, gdrive, ia)
```

Phase 4 is the only serial bottleneck. Phases 5 and 6 can run in parallel after it. Phase 7 (WP integration) and Phase 8 (CLI) are out of scope of this design.

### Phase 4 — Archiver v2: schema + tools + bus publisher

**Goal:** Archiver fully on the v2 model, with no live consumers yet.

**Schema cutover** (single Alembic migration; pre-prod = no compat shim):
- Drop `information.info_specs`.
- Create `info_sources`, `source_revisions`, `info_item_sources`, `info_item_source_revisions`, `rep_specs`, `info_item_rep_specs`.
- Add `info_items.rep_fields` JSONB column.

**Schema documents** (`src/core/`):
- `source_spec_schema/v1.json` (root + fragment variants).
- `rep_spec_schema/v1.json` envelope + `rep_spec_schema/providers/{gcs,gdrive,ia}/v1.json`.
- `rep_fields_schema/v1.json`.

**Authoring tools** — reshape existing, add new (per Section 2 surface table).

**SourceRevision write endpoint** — `POST /source-revisions`. Idempotent on `UNIQUE (source_id, fingerprint)` — repeated POST returns the existing row, doesn't error.

**Source-revisions cache PATCH** — `PATCH /source-revisions/{id}` accepts `{content_cache_uri, content_cache_expires_at}` (set or null). Used by Watcher's sweeper and Replicator's read-failure fallback.

**Change-bus publisher in Archiver** — outbox pattern. Insert SourceRevision → write outbox row in same transaction → background publisher drains to Redis Stream `info.changes`.

**SDK** — regenerate `archiver-client` to v1.0. New methods: `list_sources`, `get_source`, `post_source_revision`, `patch_source_revision`, `assign_rep_spec`, `patch_rep_spec_assignment`, `resolve_rep_fields`, `validate_rep_spec`, `validate_rep_fields`, etc. Drop info_spec methods.

**Smoke test** — `scripts/smoke_phase4.sh`: end-to-end the v2 authoring loop (create item, declare source, post fake revision, observe `info.changes` event, assign rep_spec, simulate `public_url` writeback, simulate sweeper-PATCH cache clear). No real fetcher needed.

**Exit criteria:** every v2 entity creatable via SDK; smoke passes; change-bus event observable; old `info_specs` table gone.

### Phase 5 — Watcher refactor

**Goal:** Watcher produces SourceRevisions in Archiver instead of locally-stored `Snapshot`s with embedded fingerprints.

**Pipeline rewrite:**
- Replace `src/core/info_resolver.py:resolve_primary` with `resolve_root_sources_with_children(info_item_id) → list[ResolvedRootSource]` (single SDK call returns each root + its child fragments — avoids N+1).
- Fetch root URL once; SHA-256 over extracted content; rely on `POST /source-revisions` idempotency for dedup (one round trip).
- Cascade: walk children from the same fetched bytes; extract per fragment SourceSpec; SHA-256; POST each.
- Watcher's existing `Snapshot` and `Change` tables become operational/local-only; the canonical revision identity now lives in Archiver. Replace `info_spec_id` on Watcher's `Change` with `source_revision_id` if a local cross-reference is useful, or drop the column.

**Watcher-side outbox:** when Archiver is unreachable, buffer planned `POST /source-revisions` calls in a local `pending_source_revisions` table. Background worker drains. Pattern mirrors today's `published_to_bus_at` on `Change`.

**Temp cache + sweeper:** Watcher writes bytes to `WATCHER_CACHE_DIR`, includes `content_cache_uri` in POST body, runs sweeper per Section 2 protocol.

**Schedule semantics:** root sources are the unit of fetch scheduling; fragments are not directly scheduled. Watcher's `Watch` table reshapes from `info_item_id` binding to `info_source_id` binding (root sources only).

**Drop simhash plumbing** (or relegate to a `Change.change_metadata.significance` field; no longer the dedup key).

**Exit criteria:** `Watch` rows resolve their cascade tree; fetches produce SourceRevisions in Archiver; events fire on `info.changes`; integration tests cover root-only, root+fragments, and fragment-only changes.

### Phase 6 — Replicator stand-up (parallel-able with Phase 5)

**Goal:** Replicator subscribes to `info.changes`, executes per-active-RepSpec replication, writes `public_url` back to Archiver.

**Sibling repo** — model after the Archiver extraction itself (`/home/exedev/replicator/`, port 8030, `replicator.service` systemd unit, separate Postgres schema).

**Service shape:**
- FastAPI app for admin endpoints (`/jobs`, `/healthz`, `/profiles`).
- Background change-bus subscriber consuming `source_revision_captured` events.
- Per-event flow: pull `info_item_ids` from event payload → for each item, query Archiver for active `info_item_rep_specs` → for each (item, rep_spec) pair, enqueue a job.
- Worker pool executes jobs: render path template against item's `rep_fields`, read source bytes (from `content_cache_uri` if available, fallback per Section 2), upload to provider, PATCH `public_url` back to Archiver.

**Provider profile resolver** — alias-driven config from Section 2. YAML at `/etc/replicator/profiles.yaml`.

**MVP providers:** `gcs`, `gdrive`, `ia`.

**Job table (Replicator-local operational state):**
```
replicator.jobs
  id, info_item_id, rep_spec_id, source_revision_id, status,
  enqueued_at, started_at, finished_at, attempt, last_error
```

**Exit criteria:** assigning a `gcs` RepSpec to an item triggers replication on the next SourceRevision, writes a real GCS object, PATCHes back the canonical URL, and the URL is queryable from Archiver. Equivalent smoke for `gdrive` and `ia`.

### Sequencing notes

- **Phase 5 ‖ Phase 6 parallelism** is real but limited by reviewer bandwidth. Single-developer: Phase 5 first (de-risks the consumer contract Replicator will also use). Multi-developer: Phase 6 can start the day Phase 4 ships.
- **Cross-repo SDK regeneration after Phase 4** is the synchronization point. Pin `archiver-client` v1.x release before either consumer phase begins.
- **Phase 4 includes outbox + bus publisher**, not Phase 5 or 6. This lets Phase 4 smoke tests exercise the full event flow with manually-POSTed revisions.

---

## Out of scope (deferred)

- **Phase 7 — WordPress cache integration:** awaits a dedicated design doc in the WP repo before re-scoping.
- **Phase 8 — Authoring CLI:** thin `archiver-client` wrapper for operator ergonomics. Defer until demand justifies.
- **`gdrive` / `ia` provider implementation details** beyond the alias-resolved profile contract — Replicator-internal design at Phase 6 implementation time.
- **Multi-VM cache-URI scheme migration** (`gcs://`, `s3://`) — forward-compatible by design but unnecessary for MVP.
- **`replication_event_log`** (per-execution audit detail beyond the `public_url` writeback) — research-doc note; not required for MVP.

---

## Open questions (track during implementation)

1. **Watcher `Watch` table reshape:** binding to `info_source_id` (root sources only) is cleaner, but how do we handle items with multiple root sources? Likely one Watch per (source × schedule) pair. Resolve in Phase 5 design refinement.
2. **Hash-verify failure policy:** when Replicator re-fetches and the hash doesn't match the recorded fingerprint, we currently fail the job. Is there a class of "trusted re-fetch" sources where a fingerprint update is acceptable? Probably not — but worth confirming when the first such failure surfaces.
3. **`info_item_source_revisions` growth bound:** append-only; will need a retention policy or partitioning eventually. Not blocking for v1.
