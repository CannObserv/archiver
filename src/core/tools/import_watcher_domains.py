"""Import Watcher's domains into Archiver, through the API (archiver#360, design D4).

Watcher's export (CannObserv/watcher ``src/ops/export_for_archiver.py``,
``schema_version: 1``) carries a ``domains`` slice keyed by host. This reads
the file from stdin, diffs each host against Archiver's row, and upserts by
host through ``PATCH /api/v1/domains/{name}`` and archive/restore. It needs no
production-database opt-in, so it never holds one, and its writes take the
same announce path as an operator's.

    cd /srv/archiver/live
    sudo cat /root/<dir>/watcher-export-YYYY-MM-DD.json \\
      | ARCHIVER_API_KEY=… .venv/bin/python -m src.core.tools.import_watcher_domains \\
          --base-url http://localhost:8000 --dry-run

Then the same without ``--dry-run``. There is no default ``--base-url``, so
nothing reaches production by accident.

**Until the flips, Watcher's value wins** for ``min_interval`` (until F1,
#366), the cadence (until F2, #364), ``is_active`` and archived-ness. Watcher
re-exports before each flip, and the import is re-run then: it is idempotent,
and a host already matching is not written. **Notes** fill an empty field only.
A note that differs from Archiver's is reported and left alone, since Archiver
has always edited its own.

Archive and restore go through the API, so a newly archived host carries
Archiver's ``archived_at``, not Watcher's.

**Refusal is all-or-nothing.** The whole file is validated before anything is
written, and every problem is reported. A cadence that is not Watcher's
``{"interval": "<n><smhd>"}`` is refused rather than stored in Watcher's shape.

**Only the domains slice is printed.** The file also holds notifier channel
ids, and both repos are public. Host names do reach stdout, so keep this
output off issues.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from archiver_client import ArchiverClient, InformationError

from src.core.models.domain import DEFAULT_MIN_INTERVAL_SECONDS
from src.core.watch_spec_schema.validator import validate_domain_watch_spec

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_ERROR = 2

API_KEY_ENV = "ARCHIVER_API_KEY"
EXPORT_SCHEMA_VERSION = 1
_FIELDS = ("min_interval", "default_schedule_config", "notes", "is_active", "archived_at")
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_PAGE = 500


class ImportRefused(ValueError):
    """The export does not map onto Archiver's domains; nothing was written."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Current:
    """A host's state in Archiver, as far as the import compares it."""

    notes: str | None
    is_active: bool
    archived: bool
    min_interval_seconds: float
    default_watch_spec: dict | None


_ABSENT = Current(
    notes=None,
    is_active=True,
    archived=False,
    min_interval_seconds=DEFAULT_MIN_INTERVAL_SECONDS,
    default_watch_spec=None,
)


@dataclass(frozen=True)
class _Desired:
    min_interval_seconds: float
    default_watch_spec: dict | None
    notes: str | None
    is_active: bool
    archived: bool


@dataclass
class Step:
    """What the import does to one host."""

    name: str
    create: bool = False
    patch: dict[str, Any] = field(default_factory=dict)
    archive: str | None = None  # "archive" | "restore"
    notes_conflict: bool = False

    @property
    def changed(self) -> bool:
        """Whether this host is written."""
        return self.create or bool(self.patch) or self.archive is not None


def _cadence(raw: Any, problems: list[str], host: str) -> dict | None:
    """Watcher's ``{"interval": …}`` as a WatchSpec v1 document, or a problem."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"interval"}:
        problems.append(f"{host}: default_schedule_config {raw!r} is not {{'interval': …}}")
        return None
    doc = {"schema_version": 1, "interval": raw["interval"]}
    ok, errors = validate_domain_watch_spec(doc)
    if not ok:
        detail = "; ".join(e["message"] for e in errors)
        problems.append(f"{host}: default_schedule_config: {detail}")
        return None
    return doc


def _seconds(raw: Any) -> float | None:
    """``raw`` as finite seconds ``>= 0``, or ``None``. A JSON integer too big for
    a float is refused, not a traceback (CR 19)."""
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    try:
        value = float(raw)
    except OverflowError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _brief(raw: Any) -> str:
    text = repr(raw)
    return text if len(text) <= 40 else f"{text[:37]}..."


def _desired(host: str, row: Any, problems: list[str]) -> _Desired | None:
    before = len(problems)
    if not isinstance(host, str) or not _HOST.match(host):
        problems.append(f"{host!r}: not a host name")
    if not isinstance(row, dict):
        problems.append(f"{host}: not an object")
        return None
    missing = [f for f in _FIELDS if f not in row]
    if missing:
        problems.append(f"{host}: missing {missing}")
        return None
    interval = _seconds(row["min_interval"])
    if interval is None:
        problems.append(
            f"{host}: min_interval {_brief(row['min_interval'])} is not a finite number >= 0"
        )
    cadence = _cadence(row["default_schedule_config"], problems, host)
    if row["notes"] is not None and not isinstance(row["notes"], str):
        problems.append(f"{host}: notes {row['notes']!r} is not a string")
    if not isinstance(row["is_active"], bool):
        problems.append(f"{host}: is_active {row['is_active']!r} is not a boolean")
    if row["archived_at"] is not None and not isinstance(row["archived_at"], str):
        problems.append(f"{host}: archived_at {row['archived_at']!r} is not a timestamp")
    if len(problems) > before:
        return None
    return _Desired(
        min_interval_seconds=interval,
        default_watch_spec=cadence,
        notes=row["notes"] or None,
        is_active=row["is_active"],
        archived=row["archived_at"] is not None,
    )


def parse_export(document: Any) -> dict[str, _Desired]:
    """Each host's desired state; raises ``ImportRefused`` listing every problem."""
    if not isinstance(document, dict):
        raise ImportRefused(["the export is not a JSON object"])
    problems: list[str] = []
    if document.get("schema_version") != EXPORT_SCHEMA_VERSION:
        problems.append(
            f"schema_version {document.get('schema_version')!r}, expected {EXPORT_SCHEMA_VERSION}"
        )
    if document.get("source") != "watcher":
        problems.append(f"source {document.get('source')!r}, expected 'watcher'")
    domains = document.get("domains")
    if not isinstance(domains, dict):
        problems.append("no domains object")
        raise ImportRefused(problems)
    desired = {host: _desired(host, row, problems) for host, row in sorted(domains.items())}
    if problems:
        raise ImportRefused(problems)
    return desired


def plan(document: Any, current: Mapping[str, Current]) -> list[Step]:
    """One ``Step`` per exported host, in host order."""
    steps = []
    for host, want in parse_export(document).items():
        have = current.get(host)
        step = Step(name=host, create=have is None)
        have = have or _ABSENT
        if step.create or want.min_interval_seconds != have.min_interval_seconds:
            step.patch["min_interval_seconds"] = want.min_interval_seconds
        if want.default_watch_spec != have.default_watch_spec:
            step.patch["default_watch_spec"] = want.default_watch_spec
        if want.is_active != have.is_active:
            step.patch["is_active"] = want.is_active
        if want.notes is not None and want.notes != have.notes:
            if have.notes is None:
                step.patch["notes"] = want.notes
            else:
                step.notes_conflict = True
        if want.archived != have.archived:
            step.archive = "archive" if want.archived else "restore"
        steps.append(step)
    return steps


def _describe(step: Step, current: Mapping[str, Current]) -> list[str]:
    have = current.get(step.name, _ABSENT)
    lines = []
    if step.create:
        fields = ", ".join(f"{k}={v!r}" for k, v in step.patch.items())
        lines.append(f"create {step.name}: {fields}")
    elif step.patch:
        fields = ", ".join(f"{k} {getattr(have, k)!r} -> {v!r}" for k, v in step.patch.items())
        lines.append(f"update {step.name}: {fields}")
    if step.archive:
        lines.append(f"{step.archive} {step.name}")
    if step.notes_conflict:
        lines.append(f"notes differ on {step.name}: kept Archiver's")
    if not step.changed:
        lines.append(f"unchanged {step.name}")
    return lines


async def _current(client: Any) -> dict[str, Current]:
    rows: dict[str, Current] = {}
    offset = 0
    while True:
        page = await client.list_domains(limit=_PAGE, offset=offset)
        for d in page.items:
            spec = d.default_watch_spec
            rows[d.name] = Current(
                notes=d.notes or None,
                is_active=d.is_active,
                archived=d.archived_at is not None,
                min_interval_seconds=d.min_interval_seconds,
                default_watch_spec=None if spec is None else spec.to_dict(),
            )
        if not page.has_more:
            return rows
        offset += _PAGE


async def _apply(client: Any, step: Step) -> None:
    if step.create or step.patch:
        await client.upsert_domain(step.name, **step.patch)
    if step.archive == "archive":
        await client.archive_domain(step.name)
    elif step.archive == "restore":
        await client.restore_domain(step.name)


async def _run(document: Any, client: Any, *, dry_run: bool, stdout, stderr) -> int:
    try:
        parse_export(document)  # refuse before touching the server
    except ImportRefused as e:
        for problem in e.problems:
            print(f"refused: {problem}", file=stderr)
        return EXIT_REFUSED
    async with client:
        current = await _current(client)
        steps = plan(document, current)
        for step in steps:
            for line in _describe(step, current):
                print(line, file=stdout)
        created = sum(s.create for s in steps)
        updated = sum(s.changed and not s.create for s in steps)
        unchanged = len(steps) - created - updated
        if dry_run:
            print(
                f"{created} to create, {updated} to update, {unchanged} unchanged (dry run)",
                file=stdout,
            )
            return EXIT_OK
        for step in steps:
            if step.changed:
                await _apply(client, step)
        print(f"{created} created, {updated} updated, {unchanged} unchanged", file=stdout)
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

    An error part-way through a real run leaves the hosts before it written; the
    re-run finishes the rest, since a host already matching is not written.
    """
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    environ = os.environ if environ is None else environ
    client_factory = ArchiverClient if client_factory is None else client_factory
    parser = argparse.ArgumentParser(description="Import Watcher's domains (archiver#360).")
    parser.add_argument("--base-url", required=True, help="Archiver to write to")
    parser.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
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
