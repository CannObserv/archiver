---
title: RepSpec assignment workflow on the InfoItem detail screen — Power Map org identity, one bag resolver, a readiness-driven Replication section
date: 2026-10-02
status: approved
---

# RepSpec assignment workflow — design

**Epic:** archiver#300 · **Children:** archiver#301–#309 (see [Steps](#steps)) · **Cross-repo:** power-map#607 (merged id discoverable on read)

## Problem

Getting an InfoItem replicating takes six steps across three screens: author or find a
RepSpec on its own screen, copy its ULID, learn its `required_fields` (shown nowhere on the
item), hand-type a nested JSON `rep_fields` bag knowing that `org.title` satisfies
`org.title_slug`, save, expand a `<details>`, paste the ULID, submit a full-page POST — then
*Replicate now*, or stable content never replicates. Nothing previews the destination before
the RepSpec document freezes on assignment (#83) and the rendered path becomes a citable
`public_url`.

Four defects sit underneath, all verified in code:

1. **Unrenderable bag on assign → 500.** `assign_rep_spec` raises `RepFieldsUnrenderableError`
   (`src/core/tools/assign_rep_spec.py:117`); neither `src/dashboard/routes/info_items.py` nor
   `src/api/routes/info_items.py` catches it.
2. **The rep-fields save validates nothing** (`patch_rep_fields`): not the v1 shape, not the
   active assignments. Dropping a required key from an assigned item silently turns every later
   occasion into an `unrenderable` skip — the invariant assignment enforces is unenforced after
   it. It is also the *only* post-create writer: no API route updates `rep_fields`.
3. **The same spec is assignable twice.** `ix_iirs_item_active` is non-unique and
   `assign_rep_spec` does not check; both assignments render one path and issuance skips both as
   `destination_collision` on every occasion.
4. **Assign failures leave the screen** for an error page that does not name the missing fields;
   success redirects to `?tab=repspecs`, a tab retired in #49.

And one structural gap: `org.*` is organization data typed per item. The canonical layout
(epic #207) exists to land beside the CLI's `organizations/{org.title_slug}` directories; #206
made the *slugger* agree cluster-wide, but nothing makes the *title* agree. A one-character
difference mints a sibling directory in a permanent public bucket.

## Decisions

| # | Question | Decision | Why |
|---|---|---|---|
| Q1 | How are RepSpecs used? | **Few shared specs**; creation is rare | Specs are shared, freeze on first assign, and prod has one serving every item. The item screen *selects*; creation stays on the RepSpec screen behind a link. Inline creation optimizes the rare act and breeds near-duplicates for #95 to clean up. |
| Q2 | Where do `org.*` values come from? | **Power Map**, the cluster's identity system of record | Not a local org table (a second source of truth), not hand-typed per item. |
| Q3 | Where does the item→org link live? | **First-class**: `info_items.pm_org_id` + local `pm_organizations` snapshot | Org is item identity, not replication config; one row per org rather than one copy per bag. |
| Q4 | Power Map renames a linked org | **Follow automatically** | Matches the CLI, which renders from the current title; history of the rename stays in each command's rendered destination. |
| Q5 | How does Archiver follow? | **Hourly conditional-GET sweep** now; a Power Map bus stream later | `/changes` + `/subscriptions` are slated for retirement in power-map#490 (sole consumer: usa-wa). The sweep needs only read endpoints. The bus stream (Q5 option C) is being filed on Power Map; its consumer replaces the trigger, not the logic. |
| — | UI shape | **One in-place Replication section** of three blocks | Matches the dashboard's in-place section pattern (Watcher panel, cadence editor). A wizard adds a page without a capability; minimal hardening leaves the core problems and would be thrown away. |

## Design

### 1. Data model and contracts

**`pm_organizations`** — local snapshot of each linked Power Map org; written only by the link
action and the follower, never edited in archiver.

| Column | Notes |
|---|---|
| `pm_org_id` (PK) | Power Map ULID, `Text` |
| `name`, `acronym` | Canonical values at last check |
| `archived_at`, `active`, `succeeded_by` | Mirrored; drive the notices |
| `merged_into` | Set on a merge; row kept for provenance |
| `renamed_from`, `renamed_at` | Previous canonical name and when the follower saw it change |
| `etag`, `pm_updated_at`, `checked_at`, `missing_since` | Follower bookkeeping |

**`info_items.pm_org_id`** — nullable FK to it. A merge re-points items to the winner.

**The effective bag** — `effective_rep_fields(bag, org)` (pure; callers load the item's org)
overlays the stored bag on the linked org's `name`/`acronym` as `org.title`/`org.acronym`, then runs `resolve_rep_fields`. It is the
**single resolution point**: `render_destination`, assignment's `required_fields` check and
probe render, issuance, `/tools/validate-rep-fields` and the preview all go through it. A guard
test fails on any other call to `resolve_rep_fields`.

**Precedence.** While an org is linked, the stored bag may not carry `org.title` or
`org.acronym` (refused on save). Other `org.*` keys behave as today — a stored `org.title_slug`
stays an explicit override, rendered as "override". Unlinked items keep working from
hand-typed values and carry a "not linked to Power Map" notice.

**Duplicate assignments** — partial unique index on `info_item_rep_specs (info_item_id,
rep_spec_id) WHERE deactivated_at IS NULL`.

**API / SDK** — additive; CHANGELOG + `client-drift` regen:

- `PUT /info-items/{id}/org` `{pm_org_id | null}` — fetches the org from Power Map at link time;
  Power Map down → 503, nothing linked.
- `PUT /info-items/{id}/rep-fields` — whole-bag replace; validates shape and every active
  assignment. The dashboard save calls the same core function.
- `InfoItemOut` gains `pm_org_id` and an `org` summary.
- Assignment: unrenderable → **422** (was 500); duplicate → **409**.
- Preview is dashboard-only (core function + HTMX route); an API tool route waits for a caller.

**Unchanged:** RepSpec documents, bus payloads, `info.registry`. Org identity does not go on the
bus in this epic.

### 2. Power Map integration

**Client.** The Power Map–hosted SDK generated from its OpenAPI spec, resolved like co-core
(wheelhouse) unless Power Map publishes it elsewhere. A thin adapter in `src/core/power_map/`
is the only importer, exposing `search_orgs(q, limit)` and `get_org(id, etag)` →
`Snapshot | NotModified | Merged(winner) | Gone`. Tests run against a fake; CI never calls
live Power Map.

**Config.** `ARCHIVER_POWER_MAP_BASE_URL` (`https://power-map.exe.xyz`, public HTTPS — no
tailnet hop) and `ARCHIVER_POWER_MAP_API_KEY` (read-only, no scopes). Unset → the Power Map
features are dormant and say "Power Map not configured", the `ARCHIVER_DEV_REDIS_URL` pattern.

**Type-ahead.** `GET /dashboard/power-map/orgs?q=` — 300 ms debounce, ≥ 2 characters, limit
10, archived excluded. Power Map's search is full-text with last-token prefix matching across
every name variant and acronym; its read bucket is 2 req/s, burst 120. Timeout or 429 →
"Power Map unavailable" inline; nothing else on the page is affected.

**Link.** Dashboard and `PUT …/org` share one core function: fetch → upsert snapshot → set FK →
commit.

**Follower.** `refresh_linked_orgs()`, run hourly by a systemd timer on the
`archiver-bus-health` pattern (#130). Conditional GET per linked org:

| Power Map says | Archiver does |
|---|---|
| 304 | `checked_at` |
| 200 | Update snapshot; a name/acronym change sets `renamed_from`/`renamed_at` and logs `pm_org_renamed`; later occasions render the new path |
| Merged | Upsert the winner, re-point items, set `merged_into` on the loser |
| 404 | `missing_since`; keep the last snapshot |
| Transport error / 429 / 5xx | Change nothing; log; retry next run |

`succeeded_by` (a re-key is a *different* org), archived and inactive are **notices only**.
Nothing blocks replication. When Power Map's bus stream lands, its consumer calls the same
`apply_org_snapshot()`; the timer becomes a low-frequency reconcile backstop or retires.

**Edge rule.** Power Map is called on the authoring path and by the follower — **never during
replication**. CLAUDE.md and `docs/ARCHITECTURE.md` record it beside the no-HTTP-to-Watcher rule
(#142): rendering reads only the local snapshot.

### 3. The InfoItem detail screen

**Overview — Organization row** (`editableField`). View: name (acronym) plus notice badges —
*renamed* (30 days: "was X; paths now `organizations/new_slug/…`"), *merged*, *succeeded by X*,
*archived*, *missing from Power Map*, or muted "Not linked". Edit: an accessible type-ahead
(ARIA combobox/listbox, keyboard navigation, the existing `.typeahead-results` styles), seeded
**locally** with orgs already linked to items on the same domain, then searching Power Map.
Link / Unlink.

**Linking over hand-typed keys.** If the stored `org.title`/`org.acronym` equal Power Map's,
the link drops them silently. If they differ, the link shows the path diff
(`organizations/old/…` → `organizations/new/…`) and requires confirmation — the one moment a
link can move existing output.

**"Replicator" → "Replication"**, three blocks, each its own swap target:

1. **Assignments table** (`#ii-rep-spec-assignments`) — unchanged, keeping its poll and the
   `hx-sync` contract (#212/#220). Kept separate so a two-second poll can never clobber a
   half-edited form.
2. **Fields** (`#ii-rep-fields`) — one row per required key across **assigned specs ∪ the spec
   selected in the picker**: key, raw-value input, live derived slug, source badge (*from Power
   Map* — read-only `org.*` · *stored* · *override* · *missing*). Unrequired stored keys under
   "Other fields", add/remove. `info_item.name` offers a one-click suggestion: the item name
   minus its `"<acronym> - "` prefix. A save that would break an active assignment is refused,
   naming the assignment and the key. "Edit as JSON" survives inside a `<details>`, through the
   same validated save.
3. **Add a spec** (`#ii-rep-spec-picker`) — every unassigned spec (no search; Q1) with name,
   provider, readiness (*Ready* · *Needs `info_item.name`* · *Can't render: …*) and **the path
   it would render**, against the latest revision or a labelled example occasion when there is
   none. Selecting an unready spec adds its keys to Fields and focuses them. Assign is enabled
   only when ready (the server re-checks). On success an inline "Replicate latest revision
   now?" prompt reuses the existing guarded action; with no revision it says it will replicate
   on the next one. Unwritable providers render disabled with the reason (#202). "New spec ↗"
   links out; with zero specs it is the empty state.

**Coordination.** Each action returns its own block and fires `HX-Trigger:
replicationChanged`; the sibling blocks re-fetch on it — the `watcherUpdated` pattern. Focus
moves to the swapped block's heading.

**Retired:** the ULID input, the `?tab=repspecs` redirect, `GET …/suggest-rep-fields`, and
this screen's use of `sortableChips` / `repFieldsEditor`.

**Living docs** in the same commits: `docs/INFO_ITEM_DETAIL.md`, `docs/PAGES.md`,
`docs/COMPONENTS.md`, and `docs/UI.md` (the three-block coordination pattern).

### 4. Testing and rollout

TDD throughout; no live Power Map in CI.

- **Effective bag** — precedence table (linked/unlinked × override × refused keys) and the
  `resolve_rep_fields` call-site guard.
- **Assignment** — 422 unrenderable (API + dashboard), 409 duplicate, index-level duplicate test,
  redirect.
- **`PUT rep-fields`** — shape errors, the assignment-naming refusal, success; dashboard parity.
- **Adapter** — SDK over a mocked transport; every status maps to the right outcome (200, 304,
  404, merged, 429, timeout, 5xx).
- **Follower** — one test per outcome; idempotent across two runs; merge re-points; rename sets
  `renamed_from`; **an occasion issued after a rename renders the new path** (end to end through
  issuance).
- **Timer** — `tests/deploy/` pins unit, timer and env gating, as for `archiver-bus-health`.
- **Dashboard** — type-ahead (dormant, Power Map down, results), link/unlink, fields,
  picker readiness, assign + prompt, `replicationChanged` headers; one context builder per
  partial (#219); `poll_sync_violations` still green; jsdom tests for the combobox.
- **Manual** — dev server (8001) with a read-only Power Map key: reads production Power Map,
  writes only `archiver_dev`.

**Migration** — one Alembic revision: `pm_organizations`, `info_items.pm_org_id`, the partial
unique index (pre-checked for duplicate active rows; prod holds one).

**Production cutover** — operator writes, agent verifies read-only:

1. Compare WSLCB's Power Map canonical name with the bag's
   `"Washington State Liquor and Cannabis Board"` — the WordPress title the CLI's directory
   derives from.
2. If they differ, correct Power Map first, unless moving the directory is intended.
3. Link the item; confirm the hand-typed keys dropped.
4. On the next occasion: rendered path unchanged, `public_url` beside the CLI's directory.

## Steps

⛔ = blocked on Power Map.

| Phase | # | Issue | Blocked by |
|---|---|---|---|
| 0 — defects | #301 | Assignment refusals: 422 unrenderable, 409 + partial unique index on duplicates, fixed redirect | — |
| 0 | #302 | Validated `set_rep_fields` + `PUT /info-items/{id}/rep-fields`; dashboard save through it | — |
| 1 — seam | #303 | `effective_rep_fields(bag, org)` as the single resolution point + guard test (`org=None`) | — |
| 2 — Power Map | #304 | Schema, adapter, config, `PUT …/org`, `InfoItemOut.org`, effective bag reads the org, key refusal | ⛔ SDK, key; #303 |
| 2 | #305 | Follower + timer; rename / missing handling (merge as a checkbox) | #304; ⛔ merge: power-map#607 |
| 2 | #306 | Overview Organization row: combobox, local suggestions, link/unlink, notices, path-diff confirm | #304 |
| 3 — Replication UX | #307 | Fields block + `replicationChanged` coordination | #302, #303 |
| 3 | #308 | Picker block: readiness, path preview, inline assign, replicate prompt; retire ULID input and `suggest-rep-fields` | #301, #307 |
| 4 — cutover | #309 | Production cutover (§4) | #304–#308 |

Phase 3 (#307, #308) depends only on Phases 0–1 and runs in parallel with Phase 2: the Fields block renders
"not linked" until #304 lands.

## Cross-repo

| Repo | Item | Owner |
|---|---|---|
| power-map | SDK generated from the OpenAPI spec | operator |
| power-map | Read-only API key for archiver | operator |
| power-map | **A merged org id says where it went** on `GET /orgs/{id}` (tombstone body with `merged_into`, or a 308 to the winner) — today a plain 404; only the retiring change feed carries `merged_into` | power-map#607 |
| power-map | Org changes on the bus (Q5 option C) | operator, filing |
| power-map | *Suggested:* document that `slug` is `acronym.lower()` — not unique, not a title slug, null without an acronym; archiver ignores it | — |
| power-map | *Suggested:* an `org_cannabis_observer` identifier backfilled from the CSV import, so Power Map names can be checked against WordPress titles until the CLI reads Power Map | — |

## Out of scope

- A structured editor for RepSpec documents (the RepSpec screen keeps its JSON form).
- #95 — clone + assignment migration (tier 3).
- #153 — provider sub-schema container fields.
- Org identity on bus payloads.
- **Consuming Power Map's org stream** — its own issue, blocked on that stream, outside this
  epic so the epic closes when the UX ships.

## Risks

- **Title parity is not guaranteed until the CLI reads Power Map.** The CLI's directories come
  from WordPress titles; archiver's will come from Power Map names. Cutover step 1 checks the one
  linked org; the suggested `org_cannabis_observer` identifier would make the check mechanical.
- **Automatic rename-following moves paths without an operator.** Accepted (Q4); the notice
  makes it visible for 30 days and each command's rendered destination keeps the history.
- **Hourly sweep latency.** A rename reaches replication up to an hour late; renames are rare.
- **Merge before power-map#607 ships** reads as *missing*: the last snapshot keeps rendering,
  so replication continues on the pre-merge name until the item is re-linked by hand.
