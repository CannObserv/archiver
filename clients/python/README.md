# archiver-client

Async Python SDK for the Archiver service (v2 model — InfoItem, InfoSource,
SourceRevision, RepSpec, assignments). Generated from the service's
OpenAPI schema with hand-written ergonomic wrappers on `ArchiverClient`.
Versioned independently of the server: the version is `[project].version` in
`pyproject.toml` (also `archiver_client.__version__`), and `CHANGELOG.md`
records each `[sdk]` change.

Since v2.0 every non-2xx response surfaces as an `InformationError` subclass
carrying `.kind`, `.message`, `.errors`, `.data` (the unified error envelope).
v0.x clients targeted the now-retired InfoSpec model and are not compatible.

## Install

Off this VM, pin a release tag. The repo is public, so no credential is needed, and
`uv.lock` pins the tag's commit:

```toml
[project]
dependencies = [
    "archiver-client",
]

[tool.uv.sources]
archiver-client = { git = "https://github.com/CannObserv/archiver", tag = "sdk-v5.19.0", subdirectory = "clients/python" }
```

On this VM, a path dependency follows the checkout instead:
`archiver-client = { path = "/home/exedev/archiver/clients/python", editable = true }`.
No cohort service depends on the SDK: Watcher and Replicator reach Archiver over the
bus only (archiver#513). Publishing to a package index waits until the service
relocates off-VM.

## Releases and tags (archiver#409)

Each SDK version is released as an annotated git tag, `sdk-v<version>`, where the
version is `[project].version` in `pyproject.toml`. The `sdk-` prefix keeps it apart
from the service's `v<version>`, which is versioned independently.

- **The tag marks the commit on `main`'s first-parent line where `pyproject.toml`'s
  version changes, which is the PR's merge commit.** For example, `sdk-v5.19.0` marks
  `dce5e3f9`, the merge of #549, not `dfe19ca2`, the commit inside the PR that bumped
  the version. The merge is the commit CI verified. It is also the line `deploy.sh`
  deploys, and it includes every fix the PR made after its bump commit.
- **Tagging is a release step.** Once a PR that bumps the version merges, run this
  from the main checkout. The operator approves the push, because a tag on a public
  repo is outward-facing:

  ```bash
  python3 scripts/sdk_tag.py tag          # annotate; prints the push line
  python3 scripts/sdk_tag.py tag --push   # annotate and push
  ```

  The script reads `origin/main` and tags every untagged release since `FLOOR`. It
  refuses a tag that already exists on another commit.
- **It can't be skipped.** CI's `changelog` job runs `sdk_tag.py check` against each
  PR's base. It fails while any release since `FLOOR` lacks an annotated tag on
  `origin` that marks the right commit. A bump PR and its merge push stay green,
  because their base is the previous release. Every PR after that is red until the
  tag is pushed.
- **A tag is never moved or deleted.** Consumers' `uv.lock` files pin its commit.
  If a tag is wrong, release a new version, tag it, and raise `FLOOR` in
  `scripts/sdk_tag.py` past the bad one, with a note. Versions before 5.19.0 are
  not tagged.

## Usage

```python
from archiver_client import ArchiverClient

async with ArchiverClient(base_url="http://localhost:8000", api_key="...") as client:
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
        for err in result.errors:  # err: archiver_client.FieldError
            print(f"{err.path}: {err.message}")

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
