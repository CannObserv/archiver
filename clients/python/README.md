# archiver-client

Async Python SDK for the Archiver service (v2 model — InfoItem, InfoSource,
SourceRevision, RepSpec, assignments). Generated from the service's
OpenAPI schema with hand-written ergonomic wrappers on `ArchiverClient`,
pinned 1:1 with server version.

Currently at **v1.3** (adds RepSpec authoring — `create_rep_spec`,
`get_rep_spec`, `list_rep_specs`; backwards compatible with v1.2).
v0.x clients targeted the now-retired InfoSpec model and are not compatible.

## Install (path dependency, prototype phase)

In the consuming repo's `pyproject.toml`:

```toml
[project]
dependencies = [
    "archiver-client",
]

[tool.uv.sources]
archiver-client = { path = "/home/exedev/archiver/clients/python", editable = true }
```

(Watcher and Replicator both pin via the absolute path on this VM. Once the
service relocates off-VM the SDK publishes to a real index.)

## Usage

```python
from archiver_client import ArchiverClient

async with ArchiverClient(base_url="http://localhost:8020", api_key="...") as client:
    # Atomically create an InfoItem with a root InfoSource
    item = await client.create_info_item(
        name="WSLCB board meeting agenda 2026-04-15",
        rep_fields={
            "org": {"acronym": "WSLCB", "title": "Washington State Liquor and Cannabis Board"},
            "event": {"date_segment": "2026_04_15", "year": "2026"},
            "file": {"label": "Agenda", "ext": "pdf"},
        },
        initial_source_spec={
            "schema_version": 1,
            "target": {"url": "https://lcb.wa.gov/board/2026-04-15/agenda.pdf"},
            "extraction": {"algorithm": "full_page"},
            "fingerprint": {},
        },
    )

    # Validate a candidate SourceSpec before binding it
    ok, errors = await client.validate_source_spec({...})

    # Record a content-addressed snapshot (idempotent on (source_id, fingerprint))
    rev = await client.post_source_revision(
        info_source_id=item.info_item_sources[0].info_source_id,
        content_fingerprint="sha256:" + "a" * 64,
        captured_at="2026-05-09T12:00:00Z",
    )
```

## Regenerate after a server schema change

```bash
bash clients/python/scripts/regen.sh
```

## Changelog

### v1.2 (2026-05-11)

**Breaking** — list endpoints now return a `Page` envelope instead of a bare list.

**Changed SDK signatures:**
- `list_info_items(*, limit=None, offset=None) -> PageInfoItemOut`
- `list_info_sources(*, parent_info_source_id=None, limit=None, offset=None) -> PageInfoSourceOut`

Both envelopes carry `items`, `has_more`, `limit`, `offset`. `limit` defaults to
100 server-side (max 500); `offset` defaults to 0. Pass `None` from the SDK to
accept server defaults. `has_more` is derived via a `limit+1` probe — no total
count is computed. Ordering is stable across pages via a unique tiebreaker on
the row id, so offset-paged iteration is safe.

**New typed exports:** `PageInfoItemOut`, `PageInfoSourceOut`.

**Migration for callers:**
```python
# v1.1
items = await client.list_info_items()
for it in items: ...

# v1.2
page = await client.list_info_items()
for it in page.items: ...
while page.has_more:
    page = await client.list_info_items(offset=page.offset + page.limit)
    for it in page.items: ...
```

### v1.1 (2026-05-10)

Additive over v1.0 — every v1.0 method retains its signature and return type.

**New SDK methods:**
- `create_info_source(source_spec, *, parent_info_source_id=None) -> InfoSourceOut`
- `get_info_source(info_source_id) -> InfoSourceOut`
- `list_info_sources(*, parent_info_source_id=None) -> list[InfoSourceOut]` *(return shape updated to `PageInfoSourceOut` in v1.2)*

**New typed export:** `InfoSourceOut`.

**Implicit server behaviour change:** `POST /info-items` with an
`initial_source_spec.target.url` that already has an InfoSource row now
returns **409 Conflict** (with `existing_info_source_id` and `url` in
`detail`). Previously the duplicate would surface as a 500
`IntegrityError`. SDK callers that pattern-match on status codes (Watcher
retry logic in particular) should treat 409 as "InfoSource already
exists; bind via `add_info_source` instead of recreating."

### v1.0 (2026-05-09)

Phase 4 cutover. Replaces the retired v0.x `InfoSpec` model with the
`InfoItem`/`InfoSource`/`SourceRevision`/`RepSpec` v2 model. Not
compatible with v0.x clients.
