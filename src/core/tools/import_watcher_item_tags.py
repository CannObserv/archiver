"""Import Watcher's item tags into Archiver, through the API (archiver#362, D6).

Watcher's export (CannObserv/watcher ``src/ops/export_for_archiver.py``,
``schema_version: 1``) carries an ``items`` slice keyed by
``archiver_info_item_id``. Each item's ``default_tags`` are its Watcher tags.
This reads the file from stdin and writes them through ``PUT
/api/v1/info-items/{id}/tags`` (the SDK's ``set_tags``) - the operator's own
write path. It needs no production-database opt-in, so it never holds one.

    cd /srv/archiver/live
    sudo cat /root/<dir>/watcher-export-YYYY-MM-DD.json \\
      | ARCHIVER_API_KEY=… .venv/bin/python -m src.core.tools.import_watcher_item_tags \\
          --base-url http://localhost:8000 --dry-run

Then the same without ``--dry-run``. There is no default ``--base-url``, so
nothing reaches production by accident.

**Fill-if-empty.** Watcher's tags are written only where Archiver's item has
none. Since this deploy tags are edited in Archiver, so an item already tagged
here is reported as ``differs`` and left alone: overwriting would discard an
Archiver edit. An item the export names but Archiver does not hold is reported
and skipped. An archived item imports like any other: tags are not watch state.

**The real import waits for a fresh export** (D7): one taken after Watcher
deletes its tag writers (CannObserv/watcher#377, #378) and before it drops
``default_tags`` (#380). A dry run on an older export is a rehearsal.

**Refusal is all-or-nothing.** The whole file is validated before anything is
written - each item's tags through D2's rule (``normalize_tags``) - and every
problem is reported. **Only item ids and counts reach the output**, never a tag
value or name: the export is root-only and both repos are public.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from archiver_client import ArchiverClient, InformationError, NotFound
from ulid import ULID

from src.core.services.info_item_tags import TagError, normalize_tags

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_ERROR = 2

API_KEY_ENV = "ARCHIVER_API_KEY"
EXPORT_SCHEMA_VERSION = 1
_FIELD = "default_tags"


class ImportRefused(ValueError):
    """The export does not map onto Archiver's items; nothing was written."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Step:
    """What the import does to one item: ``fill``, ``differs``, ``unchanged`` or ``missing``."""

    info_item_id: str
    action: str
    tags: list[str]
    archiver_tags: list[str] | None = None


def _is_ulid(value: Any) -> bool:
    try:
        ULID.from_str(value)
    except (TypeError, ValueError):
        return False
    return True


def parse_export(document: Any) -> dict[str, list[str]]:
    """Each item's Watcher tags in stored form, for items that have any.

    Raises ``ImportRefused``, naming item ids only.
    """
    if not isinstance(document, dict):
        raise ImportRefused(["the export is not a JSON object"])
    problems: list[str] = []
    if document.get("schema_version") != EXPORT_SCHEMA_VERSION:
        problems.append(
            f"schema_version {document.get('schema_version')!r}, expected {EXPORT_SCHEMA_VERSION}"
        )
    if document.get("source") != "watcher":
        problems.append(f"source {document.get('source')!r}, expected 'watcher'")
    items = document.get("items")
    if not isinstance(items, dict):
        problems.append("no items object")
        raise ImportRefused(problems)
    wanted: dict[str, list[str]] = {}
    broken: list[str] = []
    for item_id, row in sorted(items.items()):
        if not _is_ulid(item_id):
            problems.append("an items key is not an InfoItem id")
            continue
        if not isinstance(row, dict):
            problems.append(f"{item_id}: not an object")
            continue
        if _FIELD not in row:
            problems.append(f"{item_id}: missing {_FIELD!r}")
            continue
        tags = row[_FIELD]
        if tags is None:
            continue
        if not isinstance(tags, list):
            problems.append(f"{item_id}: {_FIELD!r} is not a list")
            continue
        try:
            normalized = normalize_tags(tags)
        except TagError:
            broken.append(item_id)
            continue
        if normalized:
            wanted[item_id] = normalized
    if broken:
        problems.append(
            f"{len(broken)} item(s) with tags breaking the tag rule (archiver#362 D2); "
            f"fix them in Watcher and re-export: {', '.join(broken)}"
        )
    if problems:
        raise ImportRefused(problems)
    return wanted


def plan(wanted: Mapping[str, list[str]], current: Mapping[str, list[str] | None]) -> list[Step]:
    """One ``Step`` per item with Watcher tags; ``current`` maps id to Archiver's
    tags (``None``: not in Archiver)."""
    steps = []
    for item_id, tags in sorted(wanted.items()):
        have = current.get(item_id)
        if have is None:
            steps.append(Step(item_id, "missing", tags))
        elif not have:
            steps.append(Step(item_id, "fill", tags))
        elif list(have) == tags:
            steps.append(Step(item_id, "unchanged", tags, list(have)))
        else:
            steps.append(Step(item_id, "differs", tags, list(have)))
    return steps


def _describe(step: Step) -> str:
    if step.action == "fill":
        return f"fill {step.info_item_id}: {len(step.tags)} tag(s)"
    if step.action == "differs":
        return (
            f"differs on {step.info_item_id}: kept Archiver's {len(step.archiver_tags or [])}"
            f" tag(s) (Watcher {len(step.tags)})"
        )
    if step.action == "missing":
        return f"missing {step.info_item_id}: not in Archiver, skipped"
    return f"unchanged {step.info_item_id}"


async def _current(client: Any, item_ids: list[str]) -> dict[str, list[str] | None]:
    rows: dict[str, list[str] | None] = {}
    for item_id in item_ids:
        try:
            tags = (await client.get_info_item(item_id)).tags
        except NotFound:
            rows[item_id] = None
            continue
        # The SDK leaves it UNSET for a server older than archiver#362.
        rows[item_id] = list(tags) if isinstance(tags, list) else []
    return rows


async def _run(document: Any, client: Any, *, dry_run: bool, stdout, stderr) -> int:
    try:
        wanted = parse_export(document)  # refuse before touching the server
    except ImportRefused as e:
        for problem in e.problems:
            print(f"refused: {problem}", file=stderr)
        return EXIT_REFUSED
    async with client:
        steps = plan(wanted, await _current(client, list(wanted)))
        for step in steps:
            print(_describe(step), file=stdout)
        counts = {a: sum(s.action == a for s in steps) for a in ("fill", "differs", "unchanged")}
        missing = sum(s.action == "missing" for s in steps)
        tail = f"{counts['differs']} differ, {counts['unchanged']} unchanged, {missing} missing"
        if dry_run:
            print(f"{counts['fill']} to fill, {tail} (dry run)", file=stdout)
            return EXIT_OK
        for step in steps:
            if step.action == "fill":
                await client.set_tags(step.info_item_id, step.tags)
        print(f"{counts['fill']} filled, {tail}", file=stdout)
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    stdin=None,
    stdout=None,
    stderr=None,
    environ: Mapping[str, str] | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> int:
    """Import the export on stdin. Exit 0 done, 1 refused (nothing written), 2 error.

    An error part-way through a real run leaves the items before it written; the
    re-run finishes the rest, since a filled item is then ``unchanged``.
    """
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    environ = os.environ if environ is None else environ
    client_factory = ArchiverClient if client_factory is None else client_factory
    parser = argparse.ArgumentParser(description="Import Watcher's item tags (archiver#362).")
    parser.add_argument("--base-url", required=True, help="Archiver to write to")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = parser.parse_args(argv)

    api_key = environ.get(API_KEY_ENV)
    if not api_key:
        print(f"{API_KEY_ENV} is not set", file=stderr)
        return EXIT_ERROR
    try:
        document = json.load(stdin)
    except json.JSONDecodeError as e:
        print(f"not a JSON export: {e}", file=stderr)
        return EXIT_ERROR
    if not isinstance(document, dict):
        print("not a JSON export: expected an object", file=stderr)
        return EXIT_ERROR
    client = client_factory(base_url=args.base_url, api_key=api_key)
    try:
        return asyncio.run(
            _run(document, client, dry_run=args.dry_run, stdout=stdout, stderr=stderr)
        )
    except (InformationError, httpx.HTTPError) as e:
        print(f"import failed: {e}", file=stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
