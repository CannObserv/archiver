# archiver — HTTP API surface

Every HTTP route and its SDK wrapper. The route inventory changes with each SDK
release; `AGENTS.md` carries only the auth rule and a pointer here. The bus
contracts Archiver produces and consumes are in [BUS.md](BUS.md) and
[BUS_CONSUMERS.md](BUS_CONSUMERS.md).

## Authoring tools + assignment endpoints (v2)

The Archiver exposes authoring helpers under `/api/v1/tools/*` and mutating sub-resource routes under `/api/v1/info-items/{id}/*`. All routes use `X-API-Key` auth (only `/health` and `/openapi.json` are open). Each route has an ergonomic SDK wrapper on `ArchiverClient` (v5.x; see [CHANGELOG.md](../CHANGELOG.md) for version history).

**Domain endpoints (v4.1+):**

| Endpoint | HTTP | SDK method |
|---|---|---|
| List Domains | `GET /domains?is_active=&archived=&limit=&offset=` | `list_domains(is_active=None, archived=None, limit=None, offset=None)` |
| Get a Domain | `GET /domains/{name}` | `get_domain(name)` |
| Upsert a Domain | `PATCH /domains/{name}` | `upsert_domain(name, notes=None, is_active=None, min_interval_seconds=None, default_watch_spec=UNSET)` |
| Delete a Domain | `DELETE /domains/{name}` | `delete_domain(name)` (409 if sources exist) |
| Archive a Domain | `POST /domains/{name}/archive` | `archive_domain(name)` |
| Restore a Domain | `POST /domains/{name}/restore` | `restore_domain(name)` |

**Suspension (archiver#360):** `is_active=false` on `PATCH`, or `archive`, suspends the host. Every item announced on it goes out on `info.registry` with `active=false`, in the write's transaction. `restore`, or `is_active=true`, resumes it, unless the other state still suspends it. A write that flips nothing announces nothing. `min_interval_seconds` (finite, `>= 0`, default `1.0`; `null` is a 422) is the host's `content.fetch-policy` frame (live since F1, #366/#438); `default_watch_spec` (WatchSpec v1 with `interval`, or `null` to clear) is the domain tier of the announced cadence (live since #364). An omitted field is left as it is. `PATCH` refuses a non-canonical name (uppercase, port, userinfo) with a 422. The contract: [DOMAINS.md](DOMAINS.md).

`InfoSourceOut` gains `domain_name: str | None` (hostname auto-set from URL at create time).
`GET /info-sources` gains `?domain_name=` filter.

**Tools:** read-only authoring helpers, plus operator controls that write - the
registry republish, DLQ discard/reprocess (#238) and outbox rearm/discard (#191).
Those take production action on 8000 and run only when the operator asks. The
operator can also triage both from the dashboard's Bus triage screen (#271),
which calls the same core functions without these routes.

| Tool | HTTP | SDK method |
|---|---|---|
| `validate_source_spec` | `POST /tools/validate-source-spec` | `validate_source_spec(doc)` |
| `validate_rep_spec` | `POST /tools/validate-rep-spec` | `validate_rep_spec(doc)` |
| `validate_rep_fields` | `POST /tools/validate-rep-fields` | `validate_rep_fields(bag, required_fields=None)` — a required `<key>_slug` is satisfied by its raw field (archiver#206); a raw value that normalizes to nothing derives no companion and stays missing |
| `validate_watch_spec` | `POST /tools/validate-watch-spec` | generated only (no hand-written wrapper — no SDK consumer yet) |
| Republish registry announcements | `POST /tools/republish-registry-announcements` | generated only (no hand-written wrapper — operator control, 202; 409 when the bus is dormant) |
| List a DLQ | `GET /tools/dead-letters/{dlq}` | generated only (operator control, archiver#238): paginated `{items, has_more, limit, offset}`, oldest first, each entry decoded against the running co-core, with its `provenance` (original `source_id`, parking `group`/`consumer`, `reason`), `parked_as` (`handler_poison` / `undecodable`, from the reason's prefix) and `owned` (archiver's own group parked it); `{dlq}` outside `content.revisions.dlq` / `content.artifacts.dlq` is a 422, a dormant bus a 409, an unreadable broker a 503 |
| Reprocess DLQ entries | `POST /tools/dead-letters/{dlq}/reprocess` | generated only (operator control, archiver#238): same body as discard → `{results: [{entry_id, outcome, detail}]}`. Runs each owned entry through the queue's own handler and deletes what it settles (`reprocessed`); `not_found`, `not_owned`, `undecodable`, `rejected` (handler poison), `failed` and `deferred` stay. A broker failure part-way through is a 503 whose `data` carries `results` and `in_doubt`. Runbook: [BUS_CONSUMERS.md](BUS_CONSUMERS.md#triaging-the-two-dlqs-archiver238) |
| Discard DLQ entries | `POST /tools/dead-letters/{dlq}/discard` | generated only (operator control, archiver#238): `{"entry_ids": [...]}` (1-500 exact `<ms>-<seq>`, each half a uint64) → `{discarded, not_found}`; each frame logged to journald, then `XDEL`ed; a broker failure part-way through is a 503 whose `data` carries `discarded`, `not_found` and `in_doubt` (the id whose delete was in flight, or null). Runbook: [BUS_CONSUMERS.md](BUS_CONSUMERS.md#triaging-the-two-dlqs-archiver238) |
| List dead-lettered outbox rows | `GET /tools/outbox/dead-lettered` | generated only (operator control, archiver#191): paginated `{items, has_more, limit, offset}`, oldest dead-lettering first; each item `{row_id, topic, event_type, payload, last_error, publish_attempts, created_at, dead_lettered_at, rearmable}`. A database read, so it works bus-dormant. Runbook: [BUS.md](BUS.md) |
| Rearm dead-lettered outbox rows | `POST /tools/outbox/dead-lettered/rearm` | generated only (operator control, archiver#191): `{"row_ids": [...]}` (1-500 ULIDs) → `{results: [{row_id, outcome, detail}]}`, one per distinct id in request order. `rearmed` clears `dead_lettered_at` and resets `publish_attempts`; `not_found`, `refused` (topic not `info.changes`) and `rejected` (payload still does not build) change nothing |
| Discard dead-lettered outbox rows | `POST /tools/outbox/dead-lettered/discard` | generated only (operator control, archiver#191): `{"row_ids": [...]}` (1-500 ULIDs) → `{discarded, not_found}`; each row logged in full to journald, then deleted, in one transaction. A live or published row is never deleted and comes back in `not_found` |
| `resolve_rep_fields` | `POST /tools/resolve-rep-fields` | `resolve_rep_fields(bag)` |
| `find_info_item` | `GET /tools/find-info-items?q=…` | `find_info_item(query, limit=20)` |
| `fetch_and_render` | `POST /tools/fetch-and-render` | `fetch_and_render(url)` |
| `preview_extraction` | `POST /tools/preview-extraction` | `preview_extraction(url, source_spec)` |
| `propose_selectors` | `POST /tools/propose-selectors` | `propose_selectors(url, description, top_k=5)` |

**Mutating endpoints:**

| Endpoint | HTTP | SDK method |
|---|---|---|
| Atomic InfoItem create | `POST /info-items` | `create_info_item(name, ..., initial_url=None, initial_source_specs=None, initial_rep_spec_assignments=None, rep_fields=None, pm_org_id=None)` |
| Bind a Source to an Item | `POST /info-items/{id}/info-sources` | `add_info_source(info_item_id, info_source_id)` |
| Deactivate a source binding | `DELETE /info-items/{id}/info-sources/{source_id}` | `deactivate_info_source_binding(info_item_id, info_source_id)` |
| Replace an item's primary source (the swap) | `PUT /info-items/{id}/primary-source` | `replace_primary_source(info_item_id, info_source_id)` |
| Delete an InfoItem | `DELETE /info-items/{id}` | `delete_info_item(info_item_id)` |
| Author a top-level InfoSource | `POST /info-sources` | `create_info_source(url, source_specs)` |
| Update InfoSource specs | `PATCH /info-sources/{id}/source-specs` | `update_info_source_specs(info_source_id, source_specs)` |
| Get an InfoSource | `GET /info-sources/{id}` | `get_info_source(id)` |
| List InfoSources (filter by URL or domain, paginated) | `GET /info-sources?url=…&domain_name=…&limit=&offset=` | `list_info_sources(url=None, domain_name=None, limit=None, offset=None)` |
| Author a RepSpec | `POST /rep-specs` | `create_rep_spec(provider, name, document)` |
| Get a RepSpec | `GET /rep-specs/{id}` | `get_rep_spec(id)` |
| Update a RepSpec (name always; document only while draft) | `PATCH /rep-specs/{id}` | `update_rep_spec(id, name=None, document=None)` |
| List RepSpecs (filter by provider, paginated) | `GET /rep-specs?provider=…&limit=&offset=` | `list_rep_specs(provider=None, limit=None, offset=None)` |
| Assign a RepSpec | `POST /info-items/{id}/rep-spec-assignments` | `assign_rep_spec(info_item_id, rep_spec_id, activated_at=None)` |
| Deactivate an assignment | `DELETE /info-items/{id}/rep-spec-assignments/{aid}` | `deactivate_rep_spec_assignment(info_item_id, assignment_id)` |
| Public-URL writeback | `PATCH /info-items/{id}/rep-spec-assignments/{aid}` | `set_public_url(info_item_id, assignment_id, public_url)` |
| Replace an item's rep_fields bag | `PUT /info-items/{id}/rep-fields` | `set_rep_fields(info_item_id, rep_fields, allow_destination_change=False)` |
| Link / unlink a Power Map org | `PUT /info-items/{id}/org` | `set_org(info_item_id, pm_org_id, allow_destination_change=False)` |
| Replace an item's cadence policy | `PUT /info-items/{id}/watch-spec` | `set_watch_spec` (SDK 5.13.0, archiver#364) |
| Pause / resume an item | `PUT /info-items/{id}/watch-active` | generated only (no hand-written wrapper — no SDK consumer yet) |
| Archive an item's watch | `POST /info-items/{id}/archive` | `archive_info_item(info_item_id)` (SDK 5.14.0, archiver#361) |
| Restore an item's watch | `POST /info-items/{id}/restore` | `restore_info_item(info_item_id)` (SDK 5.14.0, archiver#361) |
| Get an item's temporal profile | `GET /info-items/{id}/temporal-profile` | `get_temporal_profile(info_item_id)` (SDK 5.15.0, archiver#365) |
| Create or replace it | `PUT /info-items/{id}/temporal-profile` | `set_temporal_profile(info_item_id, profile)` (SDK 5.15.0) |
| Delete it | `DELETE /info-items/{id}/temporal-profile` | `delete_temporal_profile(info_item_id)` (SDK 5.15.0) |
| Record a SourceRevision (idempotent) | `POST /source-revisions` | `post_source_revision(...)` |
| Clear cache fields | `PATCH /source-revisions/{id}` | `patch_source_revision_cache(id, content_cache_uri=None, content_cache_expires_at=None)` |

`POST /info-sources` accepts `{url, source_specs}`. Multiple InfoSources at the same URL are valid. Returns 422 on invalid URL or spec validation failure.

`PUT /info-items/{id}/primary-source` accepts `{info_source_id}` and **is the swap** (archiver#45).
In one transaction it deactivates the current primary, binds the new one, emits
`info_item_primary_changed` and announces once on `info.registry`, with the final state.
**`DELETE …/info-sources/{source_id}` then `POST …/info-sources` is not a swap.** It is two
flows and two announcements, revoked then live, so the consumer destroys its row and recreates it,
losing every local column. Use the DELETE only to leave an item with no primary. The InfoItem row
is locked `FOR UPDATE`, as `POST …/info-sources` also locks it, so a swap serializes against
another swap or a bind. The dashboard's two swap routes run the same
core tool (`src/core/tools/swap_primary_source.py`). Outcomes:

- **201**: the item had no active primary.
- **200**: replaced; or the source was already primary, in which case nothing is written,
  emitted or announced.
- **404** `kind="lookup"`: no such InfoItem or InfoSource.

**A revert starts a new tenure** (archiver#392). Each `info_item_sources` row is one tenure with
its own `id` (`InfoItemSourceOut.id`), so swapping back to an earlier primary - or binding one with
`POST …/info-sources` - inserts a row, and the earlier tenure keeps its `created_at` and
`deactivated_at`. `include_deactivated=true` therefore lists a source once per tenure, oldest
first. The revert's `info_item_primary_changed` gets a fresh key: see [BUS.md](BUS.md).

**Every bind emits `info_item_primary_changed` once** (archiver#390): `POST /info-items` with
`initial_url`, `POST …/info-sources` and the PUT all bind through `bind_info_source`, which emits.
`old_info_source_id` is the item's latest closed tenure, `null` when it has none: so a PUT on an
item whose primary was DELETEd names that primary, though the response is a 201.

`POST /info-items/{id}/rep-spec-assignments` refuses before the RepSpec document freezes (#83),
because afterwards nothing can fix it: **422** `code="rep_spec_invalid"` when the document itself
fails `validate_rep_spec` (one error per problem, path under `/document`, `data.rep_spec_id`;
archiver#334 - judged before the bag, since no bag fixes it, and the same on `POST /info-items` and
the dashboard picker; existing assignments and issuance are never re-judged),
`code="rep_fields_incomplete"` (one error per missing
`required_fields` key) or `code="rep_fields_unrenderable"` (path `/rep_fields`; the bag is present
but cannot render `path_template`, e.g. `"WA LCB"` as a path segment - this was a 500 until
archiver#301). A required `_slug` whose raw value slugs to nothing is the second kind wherever the
bag is checked against a spec - here, `POST /info-items` and `PUT …/rep-fields` - and its message
names the raw field: `org.title "!!!" slugs to nothing (org.title_slug)` (archiver#312); **409** `kind="conflict"` when the spec is already actively assigned to the item, with
`data.existing_assignment_id` - deactivate it first. `POST /info-items` refuses the same spec listed
twice in `initial_rep_spec_assignments` (422, `code="duplicate_assignment"`). One active row per
`(item, spec)` is a database invariant ([SCHEMA.md](SCHEMA.md) § `InfoItemRepSpec`).

`PUT /info-items/{id}/rep-fields` accepts `{rep_fields, allow_destination_change=false}` and
**replaces** the bag whole (archiver#302). It is the only way to change a bag after create, and it
holds every later bag to the standard assignment did, so it cannot break an active assignment. The
InfoItem row is locked `FOR UPDATE`, and `assign_rep_spec` takes the same lock, so a save and a
concurrent assign cannot each pass on their own snapshot. Refusals leave the stored bag untouched:

- **422** `code="rep_fields_invalid"`: not Rep Fields v1 (`src/core/rep_fields_schema/v1.json`).
  `POST /info-items` now refuses the same, assignments or not.
- **422** `kind="domain"`, `code="rep_fields_incomplete"` / `"rep_fields_unrenderable"`: the bag
  would break an active assignment. Every broken assignment is reported, not just the first:
  `data.refusals` is `[{assignment_id, rep_spec_id, rep_spec_name, code, errors}]`, and each
  `FieldError` message names its RepSpec.
- **409** `kind="conflict"`, `code="rep_fields_moves_destination"`: the bag is valid, but an active
  assignment would render to a different path from now on, beside everything already published at
  the old one in a permanent bucket. `data.moves` is `[{assignment_id, rep_spec_id, rep_spec_name,
  before, after}]`, both rendered against one occasion, so they differ only where the bags do: the
  item's latest revision, the one *Replicate now* would use, or, with none or one that cannot
  render, an example (revision id of zeros, `text/html`; archiver#333). Resend with
  `allow_destination_change: true` to store it; the move is logged at WARNING.
  Repairing a bag that could not render is not a move.

Error paths point into the request body (`/rep_fields/org/title_slug`). Nothing is announced:
`rep_fields` rides no bus stream. **`POST /info-items` uses two path conventions:** its new
`rep_fields_invalid` paths are body-relative like these, but its `rep_fields_incomplete` paths
stay bag-relative (`/org/title_slug`), as they were before #302. Changing them would break
existing callers.

`PUT /info-items/{id}/org` accepts `{pm_org_id, allow_destination_change=false}` (archiver#304);
`pm_org_id` is required, and `null` unlinks. Linking fetches the org from Power Map **now**, upserts
its local `pm_organizations` snapshot and sets `info_items.pm_org_id`; a merged id links the org it
was merged into. The effective bag's `org.title`/`org.acronym` then come from the snapshot, so the
link drops any stored copies; other `org.*` keys stay as overrides. Unlinking writes the org's
values back into the bag, so nothing moves. Same InfoItem row lock as the save. Refusals link nothing:

- **503** `kind="server"`: Power Map not configured (`data.reason="not configured"`) or unreachable
  (timeout, 429, 5xx, rejected key; `data.reason`, `data.retry_after`, and `Retry-After` when Power
  Map sent one). Unlinking never calls Power Map.
- **422** `kind="domain"`, path `/pm_org_id`: `code="pm_org_not_found"` (unknown, deleted, or merged
  into an org that is gone) or `code="pm_org_unnamed"` (no canonical name to supply `org.title`).
- **422** `rep_fields_incomplete` / `rep_fields_unrenderable` with `data.refusals`, and **409**
  `rep_fields_moves_destination` with `data.moves`, exactly as `PUT …/rep-fields`: one
  move-confirmation contract. Linking over a hand-typed `org.title` that differs from Power Map's is
  a move whenever an active assignment renders from it.

**While linked**, `PUT …/rep-fields` refuses a stored `org.title` or `org.acronym` (**422**
`rep_fields_invalid`, path `/rep_fields/org/title`). `POST /info-items` takes an optional
`pm_org_id` with the same fetch, refusals and 503, before anything is written. `InfoItemOut` carries
`pm_org_id` and `org` - the snapshot: `name`, `acronym`, `active`, and the notices `archived_at`,
`succeeded_by`, `merged_into`, `renamed_from`/`renamed_at`, `missing_since`, plus `checked_at` -
or `null` when unlinked.

`DELETE /info-items/{id}` returns 204 and cascades the item's source bindings and rep-spec
assignments; the InfoSource and its SourceRevisions survive (the physical layer is shared). 404 on
an already-deleted item, not a silent 204. It exists to give the registry's exit a **transactional
home** (archiver#141): "gone from the registry" is announced as a `revoked` tombstone that has to be
written in the deletion's own transaction, which raw SQL cannot do — and the periodic full republish
does not repair a missed one, since absence-from-a-full-set is deliberately not the delete signal.
The deletion is announced as a tombstone on `info.registry` ([BUS.md](BUS.md)), but watcher#254 does not document
tombstone handling, so an orphaned WatchedItem may still need removing there by hand. Deleting an
item that Watcher has reported on (a `watch_status` row exists) logs a WARNING naming it, so the
cleanup is discoverable from journald rather than only from this paragraph.

`PUT /info-items/{id}/watch-spec` accepts `{document}` and **replaces** the cadence document whole
— it is not a merge, because omitting `interval` is the only way to say "inherit" (the host's
default cadence, else Watcher's own) and a merge would make that state unreachable once an interval
had been set. The stored document is the item's own intent; `info.registry` carries the resolved
interval (archiver#364, [BUS.md](BUS.md)). Invalid
documents return the 422 envelope with per-field errors and leave the stored policy untouched,
including a pre-rework document that still nests `active` (rejected, not silently dropped).

**Both policy PUTs store on any item but announce only an announceable one** (archiver#167): an
active binding whose source has non-empty `source_specs`. Pause and cadence cannot change
announceability, so on an unbound or spec-less item the write is stored and `info.registry` stays
silent, with no tombstone and no generation bump. The first live announcement after a bind carries
the stored policy, so configuring an item before binding it works.

`PUT /info-items/{id}/watch-active` accepts `{active: bool}` — required, idempotent. **Two routes
rather than one body** because the two fields need opposite absence rules: an omitted `interval`
means "consumer default", while pause state has no omitted case at all (`NULL` is reachable only by
never having written). Splitting them also keeps a dashboard pause from becoming a read-modify-write
of a cadence document it does not otherwise touch. `watch_spec` and `watch_active` are both additive
on `InfoItemOut`. Contract and rationale: [SCHEMA.md](SCHEMA.md).

**Watch lifecycle (archiver#361):** `POST /info-items/{id}/archive` and `/restore`, the Domain
routes' shape, return the `InfoItemOut`; a missing item is a 404 envelope. Archive sets
`archived_at` and announces `active=false`; restore clears it and announces the item's own
`watch_active`, so a paused item stays paused. Both are idempotent - archive keeps its first
timestamp, and a call that changes nothing announces nothing - and announce only an announceable
item, like the policy PUTs. `PUT /watch-active` on an archived item is accepted and stored; the wire
stays `active=false` until restore. Archive is watch-only and does not gate delete.
`GET /info-items?archived=true|false` filters on it; omitted returns both.

**Temporal profiles (archiver#365):** one per item, a singular resource. `PUT` is a whole-document
create-or-replace (no 409), evaluated for today (UTC): `resolved_interval` is the top tier of the
announced cadence, announced when it moved. Shape errors and a window that has already ended (every
write re-arms `fired_at`) are 422 envelopes with paths; a missing item, or a missing profile on
`GET`/`DELETE`, is a 404. The daily boundary and the post-actions: [SCHEMA.md](SCHEMA.md).

**Pagination:** `GET /info-items`, `GET /info-sources`, and `GET /rep-specs` return a `Page` envelope — `{items, has_more, limit, offset}`. All accept `limit` (default 100, max 500) and `offset` (default 0) query params. Ordering is stable: `(created_at, id)`. `has_more` is computed via a `limit+1` probe — no total count. SDK methods `list_info_items` / `list_info_sources` / `list_rep_specs` return `PageInfoItemOut` / `PageInfoSourceOut` / `PageRepSpecOut`; pass `limit`/`offset` to forward to the server.

**SDK version history:** see [CHANGELOG.md](../CHANGELOG.md).
