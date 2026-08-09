# archiver — API & Change-Bus Surface

Every HTTP route, its SDK wrapper, and the `info.changes` event contract. The
route inventory changes with each SDK release; `AGENTS.md` carries only the
auth rule and a pointer here.

## Authoring tools + assignment endpoints (v2)

The Archiver exposes authoring helpers under `/api/v1/tools/*` and mutating sub-resource routes under `/api/v1/info-items/{id}/*`. All routes use `X-API-Key` auth (only `/health` and `/openapi.json` are open). Each route has an ergonomic SDK wrapper on `ArchiverClient` (v5.x; see [CHANGELOG.md](../CHANGELOG.md) for version history).

**Domain endpoints (v4.1+):**

| Endpoint | HTTP | SDK method |
|---|---|---|
| List Domains | `GET /domains?is_active=&archived=&limit=&offset=` | `list_domains(is_active=None, archived=None, limit=None, offset=None)` |
| Get a Domain | `GET /domains/{name}` | `get_domain(name)` |
| Upsert a Domain | `PATCH /domains/{name}` | `upsert_domain(name, notes=None, is_active=None)` |
| Delete a Domain | `DELETE /domains/{name}` | `delete_domain(name)` (409 if sources exist) |
| Archive a Domain | `POST /domains/{name}/archive` | `archive_domain(name)` |
| Restore a Domain | `POST /domains/{name}/restore` | `restore_domain(name)` |

`InfoSourceOut` gains `domain_name: str | None` (hostname auto-set from URL at create time).
`GET /info-sources` gains `?domain_name=` filter.

**Read-only tools:**

| Tool | HTTP | SDK method |
|---|---|---|
| `validate_source_spec` | `POST /tools/validate-source-spec` | `validate_source_spec(doc)` |
| `validate_rep_spec` | `POST /tools/validate-rep-spec` | `validate_rep_spec(doc)` |
| `validate_rep_fields` | `POST /tools/validate-rep-fields` | `validate_rep_fields(bag, required_fields=None)` |
| `resolve_rep_fields` | `POST /tools/resolve-rep-fields` | `resolve_rep_fields(bag)` |
| `find_info_item` | `GET /tools/find-info-items?q=…` | `find_info_item(query, limit=20)` |
| `fetch_and_render` | `POST /tools/fetch-and-render` | `fetch_and_render(url)` |
| `preview_extraction` | `POST /tools/preview-extraction` | `preview_extraction(url, source_spec)` |
| `propose_selectors` | `POST /tools/propose-selectors` | `propose_selectors(url, description, top_k=5)` |

**Mutating endpoints:**

| Endpoint | HTTP | SDK method |
|---|---|---|
| Atomic InfoItem create | `POST /info-items` | `create_info_item(name, ..., initial_url=None, initial_source_specs=None, initial_rep_spec_assignments=None, rep_fields=None)` |
| Bind a Source to an Item | `POST /info-items/{id}/info-sources` | `add_info_source(info_item_id, info_source_id)` |
| Deactivate a source binding | `DELETE /info-items/{id}/info-sources/{source_id}` | `deactivate_info_source_binding(info_item_id, info_source_id)` |
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
| Record a SourceRevision (idempotent) | `POST /source-revisions` | `post_source_revision(...)` |
| Clear cache fields | `PATCH /source-revisions/{id}` | `patch_source_revision_cache(id, content_cache_uri=None, content_cache_expires_at=None)` |

`POST /info-sources` accepts `{url, source_specs}`. Multiple InfoSources at the same URL are valid. Returns 422 on invalid URL or spec validation failure.

**Pagination:** `GET /info-items`, `GET /info-sources`, and `GET /rep-specs` return a `Page` envelope — `{items, has_more, limit, offset}`. All accept `limit` (default 100, max 500) and `offset` (default 0) query params. Ordering is stable: `(created_at, id)`. `has_more` is computed via a `limit+1` probe — no total count. SDK methods `list_info_items` / `list_info_sources` / `list_rep_specs` return `PageInfoItemOut` / `PageInfoSourceOut` / `PageRepSpecOut`; pass `limit`/`offset` to forward to the server.

**SDK version history:** see [CHANGELOG.md](../CHANGELOG.md).

**Change-bus producer (co-core bus, archiver#106):** Writes rows to
`information.changes_outbox` in the same transaction (the **outbox stays
archiver-owned** — it is the producer-side delivery guarantee); the publisher
background task (`src/core/changes/publisher.py`) drains the outbox and publishes
each row to the Redis Stream `info.changes` **through the shared co-core bus
driver** — `co_core_aio.bus.AsyncBusPublisher.execute(BusPublish(...))`, with the
wire envelope built by `co_core.pure.adapters.bus.envelope.to_wire`. Publisher
only starts when `ARCHIVER_REDIS_URL` is set. Two event types:

| Event type | Trigger | Payload type (co-core) |
|---|---|---|
| `source_revision_captured` | New `SourceRevision` insert — from `POST /source-revisions` **or** from a `content.revisions` observation, on the non-idempotent path either way | `co_core.pure.models.changes.SourceRevisionCapturedEvent` |
| `info_item_primary_changed` | New active `InfoItemSource` binding created (`POST /info-items/{id}/info-sources`) | `co_core.pure.models.changes.InfoItemPrimaryChangedEvent` |

The payload models live in **co-core** (`co_core.pure.models.changes`) — lifted
from archiver in cannobserv#261 so the whole cluster shares one contract. Emit
sites construct the **strict `*Emit` subclasses** (`SourceRevisionCapturedEmit` /
`InfoItemPrimaryChangedEmit`, `extra="forbid"`) for emit-time typo-catch; the
canonical classes are `extra="ignore"` (consumer-safe forward-compat). The
**wire envelope** is the XADD field map `key` / `payload` (full event JSON) /
`event_type` / `schema_version` / `occurred_at` / `content_type`; the idempotency
`key` is derived per type by co-core (`source_revision_id`; the
`{info_item_id}:{new_info_source_id}` composite).

`source_revision_captured` schema_version is now **2** — `bindings[*].role` field removed. Consumers must branch on `schema_version` before destructuring. `info_item_primary_changed` carries `old_info_source_id` (null on first assignment, non-null on succession) and `new_info_source_id`. Subscribers use it to discover URL succession.

**Bus event versioning convention.** Every bus event payload carries
`schema_version: int` (start at `1`, monotonic). Bump only on *incompatible*
reshapes — field removal, type change, semantic redefinition. Additive
fields are not a bump; consumers must tolerate them. Apply the same
convention to any future event type added to `info.changes`.

Consumer rule: parsers must accept extra fields. With a Pydantic model,
use `ConfigDict(extra="ignore")` (or `model_construct`) on the
consumer-side mirror so additive producer fields do not raise
`ValidationError`. Branch on `schema_version` before destructuring when
the version is one the consumer recognises differently.

## Change-bus consumer — `content.revisions` (archiver#139)

Archiver's **only** consumer role. It reads `source_revision_observed` facts
(`co_core.pure.models.changes.SourceRevisionObservedEvent`, cannobserv#301) from
`content.revisions` under the group **`archiver.revisions`**, one group per
consuming service as the fact-stream posture requires.
`src/core/changes/consumer.py` holds the loop; it runs under the FastAPI
lifespan and is dormant unless **both** `ARCHIVER_REDIS_URL` and
`ARCHIVER_BUS_CONSUMER=1` are set.

Watcher observes; the registry decides. Per message:

1. `info_source_id` is resolved against the registry. Unknown → **ack and drop**
   with a WARNING. The registry is the authority on what exists, and redelivery
   cannot make a missing InfoSource appear.
2. The row is written through
   `src.core.services.source_revision.record_revision` — the same call
   `POST /source-revisions` makes. The existing `INSERT … ON CONFLICT …` on
   `(info_source_id, content_fingerprint)` makes at-least-once redelivery a
   no-op.
3. On a genuinely new row, the `changes_outbox` row is written **in the same
   transaction**, so `source_revision_captured` reaches `info.changes` with
   semantics unchanged for existing subscribers. The event is Archiver's own
   fact, keyed as it always was on `source_revision_id`.
4. The message is acked **after** the commit. A crash in between redelivers and
   the retry is idempotent; the other order would lose a revision.

Field mapping, and the two traps in it:

| Wire field | Column | Note |
|---|---|---|
| `extracted_fingerprint` | `content_fingerprint` | **Never** cross-match with `BlobAvailableEvent.content_fingerprint` — that is Replicator's sha256 of the *raw bytes*, this is sha256 of the text extracted under `source_specs`. Different inputs, different services; a cross-match fails silently as "no revision for this blob" |
| `content_size_bytes` / `content_media_type` | same | measure the **extracted** content |
| `source_media_type` | `source_media_type` | what the **origin** served; inherits `BlobAvailableEvent.media_type`'s normalization |
| `blob_uri` | `content_cache_uri` | **a cache, not durable storage** — a VM-local `file://` on Replicator's host. Durable bytes are RepSpec replication's job |
| `blob_expires_at` | `content_cache_expires_at` | `None` records *absence*; never substitute a TTL guessed from Replicator's policy |
| `spec_fingerprint` | `spec_fingerprint` | recorded **and compared** — see below |
| `command_id` | `command_id` | correlation back to the fetch |
| *(absent)* | `source_revision_id` | **Archiver allocates.** A service that does not own the registry does not mint registry ids |

**The `spec_fingerprint` comparison.** At ingest the value is looked up in an index of the
InfoSource's own specs, built with co-core's shared derivation
(`co_core.pure.extract.spec_fingerprint_index`, cannobserv#309, co-core ≥0.8.1). The outcome lands
in `spec_match` / `spec_position` (see [docs/SCHEMA.md](SCHEMA.md) — they track the *most recent*
observation, refreshed on re-observation) and is **never** a rejection —
archiver#140 makes spec delivery eventually consistent, so a producer one announcement behind is
expected, and its observation is real. Two rules come from the contract rather than from registry
policy: an **absent** fingerprint is not a mismatch (the field is optional, and a producer that has
not adopted it yet would otherwise flag on every revision), and an **unrecognised derivation tag**
is incomparable — flagging against a derivation you cannot reproduce is the false positive the tag
exists to prevent.

Failure routing: a well-formed observation the registry cannot use — a
fingerprint outside `sha256:<64 hex>`, an `info_source_id` that is not a ULID —
is quarantined to `content.revisions.dlq`, because redelivery reproduces it
exactly. A frame that does not decode at all is quarantined too, via a raw pass
over the group's pending list (`from_wire` raises before any message id reaches
the caller, so there is nothing to `dead_letter` with — see
`quarantine_undecodable`). Anything transient — the database down — leaves the
message **pending**, and it is redelivered or reclaimed by `XAUTOCLAIM`.

The HTTP write path (`POST` / `PATCH /source-revisions`) stays for authoring and
backfill; retiring it is a separate call from retiring Watcher's *use* of it
(CannObserv/watcher#253).
