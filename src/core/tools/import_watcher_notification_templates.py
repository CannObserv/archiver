"""Import Watcher's notification templates as subscriptions, through the API (archiver#363, D6).

Watcher's export (CannObserv/watcher ``src/ops/export_for_archiver.py``,
``schema_version: 1``) carries a ``notification_templates`` list, ordered by
Watcher's template id. This reads the file from stdin and creates one
subscription per template through ``POST /api/v1/notification-subscriptions``
- the operator's own write path. It needs no production-database opt-in, so it
never holds one. Nothing sends: dispatch is #369.

    cd /srv/archiver/live
    sudo cat /root/<dir>/watcher-export-YYYY-MM-DD.json \\
      | ARCHIVER_API_KEY=… .venv/bin/python \\
          -m src.core.tools.import_watcher_notification_templates \\
          --base-url http://localhost:8000 \\
          --channel-map WATCHER_CHANNEL=ARCHIVER_CHANNEL [--channel-map …] --dry-run

Then the same without ``--dry-run``. There is no default ``--base-url``, so
nothing reaches production by accident.

**Keyed by Watcher's template id** (``imported_watcher_id``). A template with no
subscription carrying its id is created; one that has one is ``unchanged`` or
``differs``, and a differing one is reported and **never overwritten** (the
#364 rule): Archiver's copy is the operator's now. So a re-run - Watcher
re-exports before F3 - lands on the same subscription ids, which #369's
idempotency key ``archiver:{event}:{subscription_id}:{event_id}`` depends on.

**The mapping:**

- ``remote_channel_id`` is a Watcher-tenant channel; ``--channel-map
  WATCHER_ID=ARCHIVER_ID`` (repeatable) translates it into Archiver's tenant
  (CannObserv/notifier#117 copied the channels under new ids). On a dev
  server, map onto ``dev-sink``: a production id there is a channel the dev
  key cannot reach;
- ``visibility`` ``watched_item`` becomes scope ``item``, on
  ``archiver_info_item_id``; ``domain`` keeps the host name;
- the two retired content keys (``RETIRED_CONTENT_KEYS``) are dropped;
- ``channel_hint`` is ignored: nothing reads it, and ``title`` names the row.

**Refusal is all-or-nothing.** The whole file is validated - locally, then the
domains and items it names against the server - before anything is written,
and every problem is reported: an unmapped or missing channel, an unknown
domain or item, any other unknown content key, or anything the API would 422.
**Only template ids, channel ids and counts reach stdout**: the file holds
titles and hints, and both repos are public. Keep this output off issues all
the same.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from archiver_client import ArchiverClient, InformationError, NotFound
from pydantic import ValidationError
from ulid import ULID

from src.core.models.notification_subscription import NOTIFICATION_EVENTS
from src.core.notifications.content_config import (
    RETIRED_CONTENT_KEYS,
    ContentConfig,
    normalize_content_config,
)

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_ERROR = 2

API_KEY_ENV = "ARCHIVER_API_KEY"
EXPORT_SCHEMA_VERSION = 1
_SCOPES = {"global": "global", "domain": "domain", "watched_item": "item"}
"""Watcher ``visibility`` → Archiver ``scope``."""
_COMPARED = ("title", "scope", "domain", "info_item_id", "events", "remote_channel_id")
_PAGE = 500


class ImportRefused(ValueError):
    """The export does not map onto Archiver; nothing was written."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Wanted:
    """One Watcher template, as the create body Archiver would receive."""

    watcher_id: str
    body: dict[str, Any]


def _ulid(value: Any) -> str | None:
    """The canonical spelling of a ULID, or ``None`` when ``value`` is not one."""
    if not isinstance(value, str):
        return None
    try:
        return str(ULID.from_str(value.upper()))
    except ValueError:
        return None


def parse_channel_map(pairs: Sequence[str]) -> dict[str, str]:
    """``WATCHER_ID=ARCHIVER_ID`` pairs as a dict; raises ``ValueError`` on a bad one."""
    mapping: dict[str, str] = {}
    for pair in pairs:
        watcher, _, archiver = pair.partition("=")
        source, target = _ulid(watcher), _ulid(archiver)
        if source is None or target is None:
            raise ValueError(f"--channel-map {pair!r}: expected WATCHER_ID=ARCHIVER_ID, two ULIDs")
        if mapping.get(source, target) != target:
            raise ValueError(f"--channel-map maps {source} twice")
        mapping[source] = target
    return mapping


def _strip_retired(config: Any) -> Any:
    """``config`` without the retired keys, at the default and every override."""
    if not isinstance(config, dict):
        return config
    out = dict(config)
    if isinstance(out.get("default"), dict):
        out["default"] = {k: v for k, v in out["default"].items() if k not in RETIRED_CONTENT_KEYS}
    if isinstance(out.get("overrides"), dict):
        out["overrides"] = {
            event: (
                {k: v for k, v in opts.items() if k not in RETIRED_CONTENT_KEYS}
                if isinstance(opts, dict)
                else opts
            )
            for event, opts in out["overrides"].items()
        }
    return out


def _wanted(row: dict, tid: str, channels: Mapping[str, str], problems: list[str]) -> Wanted | None:
    """One template's create body; appends a problem for each thing that does not map."""
    found: list[str] = []
    title = row.get("title")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
        found.append("title must be 1-100 characters")
    scope = _SCOPES.get(row.get("visibility"))
    if scope is None:
        found.append(f"unknown visibility {row.get('visibility')!r}")
    domain, item = row.get("domain_name"), row.get("archiver_info_item_id")
    if (scope == "domain") != (domain is not None):
        found.append("domain_name must be set exactly for domain visibility")
    if (scope == "item") != (item is not None):
        found.append("archiver_info_item_id must be set exactly for watched_item visibility")
    if item is not None and _ulid(item) is None:
        found.append("archiver_info_item_id is not an InfoItem id")
    events = row.get("events")
    if (
        not isinstance(events, list)
        or not events
        or not all(isinstance(e, str) and e in NOTIFICATION_EVENTS for e in events)
    ):
        found.append(f"events must be a non-empty list of {', '.join(NOTIFICATION_EVENTS)}")
        events = []
    if not isinstance(row.get("is_active"), bool):
        found.append("is_active is not a boolean")
    channel = row.get("remote_channel_id")
    if channel is None:
        found.append("no channel (remote_channel_id is null)")
    elif not isinstance(channel, str):
        found.append("remote_channel_id is not a channel id")
    elif channel not in channels:
        found.append(f"channel {channel} is not in --channel-map")
    config = _strip_retired(row.get("content_config"))
    if config is not None:
        try:
            # Not normalize_content_config: its ``raw or {}`` would pass a falsy
            # non-object, which the API then refuses mid-run (CR 5a).
            ContentConfig.model_validate(config)
        except ValidationError as e:
            where = ", ".join("/".join(map(str, err["loc"])) for err in e.errors())
            found.append(f"content_config does not validate ({where})")
    problems.extend(f"{tid}: {problem}" for problem in found)
    if found:
        return None
    body: dict[str, Any] = {
        "title": title.strip(),
        "scope": scope,
        "events": [e for e in NOTIFICATION_EVENTS if e in events],
        "remote_channel_id": channels[channel],
        "is_active": row["is_active"],
        "content_config": config,
        "imported_watcher_id": tid,
    }
    if domain is not None:
        body["domain"] = domain
    if item is not None:
        body["info_item_id"] = _ulid(item)
    return Wanted(tid, body)


def parse_export(document: Any, channels: Mapping[str, str]) -> list[Wanted]:
    """Each template as a create body, in Watcher's id order; raises ``ImportRefused``."""
    if not isinstance(document, dict):
        raise ImportRefused(["the export is not a JSON object"])
    problems: list[str] = []
    if document.get("schema_version") != EXPORT_SCHEMA_VERSION:
        problems.append(
            f"schema_version {document.get('schema_version')!r}, expected {EXPORT_SCHEMA_VERSION}"
        )
    if document.get("source") != "watcher":
        problems.append(f"source {document.get('source')!r}, expected 'watcher'")
    templates = document.get("notification_templates")
    if not isinstance(templates, list):
        problems.append("no notification_templates list")
        raise ImportRefused(problems)
    wanted: list[Wanted] = []
    seen: set[str] = set()
    for index, row in enumerate(templates):
        if not isinstance(row, dict):
            problems.append(f"template {index}: not an object")
            continue
        tid = _ulid(row.get("id"))
        if tid is None:
            problems.append(f"template {index}: {row.get('id')!r} is not a template id")
            continue
        if tid in seen:
            problems.append(f"{tid}: duplicate template id")
            continue
        seen.add(tid)
        one = _wanted(row, tid, channels, problems)
        if one is not None:
            wanted.append(one)
    if problems:
        raise ImportRefused(problems)
    return sorted(wanted, key=lambda w: w.watcher_id)


async def _missing_refs(client: Any, wanted: list[Wanted]) -> list[str]:
    """A problem for each domain or item the file names that Archiver does not hold."""
    problems = []
    for one in wanted:
        if "domain" in one.body:
            try:
                await client.get_domain(one.body["domain"])
            except NotFound:
                problems.append(f"{one.watcher_id}: no Domain row for its domain")
        if "info_item_id" in one.body:
            try:
                await client.get_info_item(one.body["info_item_id"])
            except NotFound:
                problems.append(
                    f"{one.watcher_id}: InfoItem {one.body['info_item_id']} not in Archiver"
                )
    return problems


async def _existing(client: Any) -> dict[str, dict]:
    """Every subscription carrying an ``imported_watcher_id``, keyed by it."""
    rows: dict[str, dict] = {}
    offset = 0
    while True:
        page = await client.list_notification_subscriptions(limit=_PAGE, offset=offset)
        for sub in page.items:
            row = sub.to_dict()
            if row.get("imported_watcher_id"):
                rows[row["imported_watcher_id"]] = row
        if not page.has_more:
            return rows
        offset += _PAGE


def differences(body: Mapping[str, Any], existing: Mapping[str, Any]) -> list[str]:
    """The fields where Archiver's subscription no longer matches Watcher's template."""
    fields = [f for f in _COMPARED if body.get(f) != existing.get(f)]
    if body["is_active"] != existing.get("is_active"):
        fields.append("is_active")
    if normalize_content_config(body["content_config"]) != normalize_content_config(
        existing.get("content_config")
    ):
        fields.append("content_config")
    return fields


async def _run(document: Any, client: Any, channels, *, dry_run: bool, stdout, stderr) -> int:
    try:
        wanted = parse_export(document, channels)  # refuse before touching the server
    except ImportRefused as e:
        return _refused(e.problems, stderr)
    async with client:
        missing = await _missing_refs(client, wanted)
        if missing:
            return _refused(missing, stderr)
        existing = await _existing(client)
        creates, differ, unchanged = [], 0, 0
        for one in wanted:
            have = existing.get(one.watcher_id)
            if have is None:
                creates.append(one)
                print(f"create {one.watcher_id}: {one.body['scope']} scope", file=stdout)
            elif fields := differences(one.body, have):
                differ += 1
                print(
                    f"differs on {one.watcher_id} (as {have['id']}): kept Archiver's"
                    f" {', '.join(fields)}",
                    file=stdout,
                )
            else:
                unchanged += 1
                print(f"unchanged {one.watcher_id} (as {have['id']})", file=stdout)
        tail = f"{differ} differ, {unchanged} unchanged"
        if dry_run:
            print(f"{len(creates)} to create, {tail} (dry run)", file=stdout)
            return EXIT_OK
        for one in creates:
            created = await client.create_notification_subscription(one.body)
            print(f"created {one.watcher_id} as {created.id}", file=stdout)
        print(f"{len(creates)} created, {tail}", file=stdout)
    return EXIT_OK


def _refused(problems: list[str], stderr) -> int:
    for problem in problems:
        print(f"refused: {problem}", file=stderr)
    return EXIT_REFUSED


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

    An error part-way through a real run leaves the templates before it
    created; the re-run finishes the rest, since a created one is then
    ``unchanged``.
    """
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    environ = os.environ if environ is None else environ
    client_factory = ArchiverClient if client_factory is None else client_factory
    parser = argparse.ArgumentParser(
        description="Import Watcher's notification templates (archiver#363)."
    )
    parser.add_argument("--base-url", required=True, help="Archiver to write to")
    parser.add_argument(
        "--channel-map",
        action="append",
        default=[],
        metavar="WATCHER_ID=ARCHIVER_ID",
        help="translate a Watcher-tenant channel into Archiver's (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = parser.parse_args(argv)

    api_key = environ.get(API_KEY_ENV)
    if not api_key:
        print(f"{API_KEY_ENV} is not set", file=stderr)
        return EXIT_ERROR
    try:
        channels = parse_channel_map(args.channel_map)
    except ValueError as e:
        print(str(e), file=stderr)
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
            _run(document, client, channels, dry_run=args.dry_run, stdout=stdout, stderr=stderr)
        )
    except (InformationError, httpx.HTTPError) as e:
        print(f"import failed: {e}", file=stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
