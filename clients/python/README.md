# archiver-client

Async Python SDK for the Archiver service. Generated from the service's
OpenAPI schema, pinned 1:1 with server version.

## Install (path dependency, prototype phase)

In the consuming repo's `pyproject.toml`:

```toml
[tool.uv.sources]
archiver-client = { path = "../watcher/clients/python", editable = true }
```

## Usage

```python
from archiver_client import ArchiverClient

async with ArchiverClient(base_url="http://localhost:8020", api_key="...") as client:
    spec = await client.get_primary_info_spec("01HZZZ...")
    print(spec.document)
```

## Regenerate after a server schema change

```bash
bash clients/python/scripts/regen.sh
```
