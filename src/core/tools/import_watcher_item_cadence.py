"""Import Watcher's own item cadences into Archiver, through the API (archiver#364, D3).

Watcher's export (CannObserv/watcher ``src/ops/export_for_archiver.py``,
``schema_version: 1``) carries an ``items`` slice keyed by
``archiver_info_item_id``. Each item's ``default_schedule_config`` is Watcher's
own cadence for it, the second tier of Watcher's chain. This reads the file
from stdin and writes that cadence through ``PUT
/api/v1/info-items/{id}/watch-spec`` - the operator's own write path, so the
item announces like any other cadence edit. It needs no production-database
opt-in, so it never holds one.

    cd /srv/archiver/live
    sudo cat /root/<dir>/watcher-export-YYYY-MM-DD.json \\
      | ARCHIVER_API_KEY=… .venv/bin/python -m src.core.tools.import_watcher_item_cadence \\
          --base-url http://localhost:8000 --dry-run

Then the same without ``--dry-run``. There is no default ``--base-url``, so
nothing reaches production by accident.

**Fill-if-absent.** Watcher's cadence is written only where Archiver's item has
no ``interval``. Where it has one, that is what Watcher already runs - the
announced interval is the top tier of Watcher's chain - so a differing Watcher
value is reported and left alone: overwriting it would change a live cadence.
A filled item therefore announces the interval Watcher applies today, and its
``watch_status.applied_interval`` does not move.

An item the export names but Archiver does not hold is reported and skipped.
Temporal profiles and the throttle floor are #365's, not read here.

**An archived Watcher item refuses the file** (archiver#361, D5). This used to
import it like any other (#364: its cadence is still intent). Archive is now
Archiver's own state, authored here, and an item Watcher archived locally would
come across as an unarchived item - announced active at the next write. The
refusal names the count and the ids; restore the item in Watcher or archive it
in Archiver, then re-export. 0 at the 2026-10-14 export; the pre-F2 re-export
runs this check again.

**Refusal is all-or-nothing.** The whole file is validated before anything is
written, and every problem is reported. **Only item ids reach stdout**: the file
holds names and notifier channel ids, and both repos are public. Keep this
output off issues all the same.
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

from src.core.tools.import_watcher_domains import watcher_cadence

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_ERROR = 2

API_KEY_ENV = "ARCHIVER_API_KEY"
EXPORT_SCHEMA_VERSION = 1
_FIELD = "default_schedule_config"


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
    watcher_interval: str
    archiver_interval: str | None = None

    @property
    def document(self) -> dict:
        """The WatchSpec v1 document a ``fill`` writes."""
        return {"schema_version": 1, "interval": self.watcher_interval}


def _is_ulid(value: Any) -> bool:
    try:
        ULID.from_str(value)
    except (TypeError, ValueError):
        return False
    return True


def parse_export(document: Any) -> dict[str, str]:
    """Each item's Watcher interval, for items that have one; raises ``ImportRefused``."""
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
    wanted: dict[str, str] = {}
    archived: list[str] = []
    for item_id, row in sorted(items.items()):
        if not _is_ulid(item_id):
            problems.append(f"{item_id!r}: not an InfoItem id")
            continue
        if not isinstance(row, dict):
            problems.append(f"{item_id}: not an object")
            continue
        if row.get("archived_at") is not None:
            archived.append(item_id)
        if _FIELD not in row:
            problems.append(f"{item_id}: missing {_FIELD!r}")
            continue
        spec = watcher_cadence(row[_FIELD], problems, item_id)
        if spec is not None:
            wanted[item_id] = spec["interval"]
    if archived:
        problems.append(
            f"{len(archived)} archived item(s), not imported: archive is authored in "
            f"Archiver (archiver#361): {', '.join(archived)}"
        )
    if problems:
        raise ImportRefused(problems)
    return wanted


def plan(wanted: Mapping[str, str], current: Mapping[str, dict | None]) -> list[Step]:
    """One ``Step`` per item with a Watcher cadence; ``current`` maps id to Archiver's
    ``watch_spec`` (``None``: not in Archiver)."""
    steps = []
    for item_id, interval in sorted(wanted.items()):
        spec = current.get(item_id)
        if spec is None:
            steps.append(Step(item_id, "missing", interval))
            continue
        have = spec.get("interval")
        if have is None:
            steps.append(Step(item_id, "fill", interval))
        elif have == interval:
            steps.append(Step(item_id, "unchanged", interval, have))
        else:
            steps.append(Step(item_id, "differs", interval, have))
    return steps


def _describe(step: Step) -> str:
    if step.action == "fill":
        return f"fill {step.info_item_id}: interval {step.watcher_interval!r}"
    if step.action == "differs":
        return (
            f"differs on {step.info_item_id}: kept Archiver's {step.archiver_interval!r}"
            f" (Watcher {step.watcher_interval!r})"
        )
    if step.action == "missing":
        return f"missing {step.info_item_id}: not in Archiver, skipped"
    return f"unchanged {step.info_item_id}"


async def _current(client: Any, item_ids: list[str]) -> dict[str, dict | None]:
    rows: dict[str, dict | None] = {}
    for item_id in item_ids:
        try:
            rows[item_id] = (await client.get_info_item(item_id)).watch_spec.to_dict()
        except NotFound:
            rows[item_id] = None
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
                await client.set_watch_spec(step.info_item_id, step.document)
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
    parser = argparse.ArgumentParser(description="Import Watcher's item cadences (archiver#364).")
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
