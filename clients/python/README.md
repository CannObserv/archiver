# archiver-client

Async Python SDK for the Archiver service. Generated from the service's
OpenAPI schema, pinned 1:1 with server version.

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
    spec = await client.get_primary_info_spec("01HZZZ...")
    print(spec.document)
```

## Regenerate after a server schema change

```bash
bash clients/python/scripts/regen.sh
```
