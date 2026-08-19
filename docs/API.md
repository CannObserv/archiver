# archiver — HTTP API surface

Every HTTP route and its SDK wrapper. The route inventory changes with each SDK
release; `AGENTS.md` carries only the auth rule and a pointer here. The bus
contracts Archiver produces and consumes are in [BUS.md](BUS.md).

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
| `validate_watch_spec` | `POST /tools/validate-watch-spec` | generated only (no hand-written wrapper — no SDK consumer yet) |
| Republish registry announcements | `POST /tools/republish-registry-announcements` | generated only (no hand-written wrapper — operator control, 202; 409 when the bus is dormant) |
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
| Replace an item's cadence policy | `PUT /info-items/{id}/watch-spec` | generated only (no hand-written wrapper — no SDK consumer yet) |
| Pause / resume an item | `PUT /info-items/{id}/watch-active` | generated only (no hand-written wrapper — no SDK consumer yet) |
| Record a SourceRevision (idempotent) | `POST /source-revisions` | `post_source_revision(...)` |
| Clear cache fields | `PATCH /source-revisions/{id}` | `patch_source_revision_cache(id, content_cache_uri=None, content_cache_expires_at=None)` |

`POST /info-sources` accepts `{url, source_specs}`. Multiple InfoSources at the same URL are valid. Returns 422 on invalid URL or spec validation failure.

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
— it is not a merge, because omitting `interval` is the only way to say "the consumer applies its
own default" and a merge would make that state unreachable once an interval had been set. Invalid
documents return the 422 envelope with per-field errors and leave the stored policy untouched,
including a pre-rework document that still nests `active` (rejected, not silently dropped).

`PUT /info-items/{id}/watch-active` accepts `{active: bool}` — required, idempotent. **Two routes
rather than one body** because the two fields need opposite absence rules: an omitted `interval`
means "consumer default", while pause state has no omitted case at all (`NULL` is reachable only by
never having written). Splitting them also keeps a dashboard pause from becoming a read-modify-write
of a cadence document it does not otherwise touch. `watch_spec` and `watch_active` are both additive
on `InfoItemOut`. Contract and rationale: [SCHEMA.md](SCHEMA.md).

**Pagination:** `GET /info-items`, `GET /info-sources`, and `GET /rep-specs` return a `Page` envelope — `{items, has_more, limit, offset}`. All accept `limit` (default 100, max 500) and `offset` (default 0) query params. Ordering is stable: `(created_at, id)`. `has_more` is computed via a `limit+1` probe — no total count. SDK methods `list_info_items` / `list_info_sources` / `list_rep_specs` return `PageInfoItemOut` / `PageInfoSourceOut` / `PageRepSpecOut`; pass `limit`/`offset` to forward to the server.

**SDK version history:** see [CHANGELOG.md](../CHANGELOG.md).
