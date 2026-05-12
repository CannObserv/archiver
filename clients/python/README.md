# archiver-client

Async Python SDK for the Archiver service (v2 model — InfoItem, InfoSource,
SourceRevision, RepSpec, assignments). Generated from the service's
OpenAPI schema with hand-written ergonomic wrappers on `ArchiverClient`,
pinned 1:1 with server version.

Currently at **v2.0** (breaking — unified error envelope for every non-2xx
response; `InformationError` subclasses surface `.kind`, `.message`,
`.errors`, `.data`). v0.x clients targeted the now-retired InfoSpec model
and are not compatible.

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
    result = await client.validate_source_spec({...})
    if not result.valid:
        for issue in result.errors:
            print(f"{issue.path}: {issue.message}")

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

See [CHANGELOG.md](../../CHANGELOG.md) at the repo root for service + SDK release history.
