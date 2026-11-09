"""InfoItem tags (archiver#362, epic #359 A6): the one tag rule, and its writes.

Tags replace Watcher's ``default_tags`` and feed the notification composer
(``ItemFacts.tags``). They are Archiver-local: nothing announces them.

**D2, one rule in one function** - ``normalize_tags``, used by the API, the
dashboard and the Watcher importer. Each tag is stripped; an empty tag, one
over 255 characters (Watcher's limit, so an import loses nothing), one holding
a comma (the dashboard editor splits on it) or a control character is refused.
Case is kept and duplicates go exactly (case-sensitive), so the result is
sorted and at most 32 long. A refusal names every problem with its position.

**Writes** (the caller commits): ``set_tags`` replaces the whole set - the API's
``PUT``, last writer wins by design. ``add_tags`` and ``remove_tag`` are the
dashboard's read-modify-write, so they lock the item row ``FOR NO KEY UPDATE``
first (D4): two quick adds serialize and neither loses the other's tag. The
lock conflicts with no ``FOR KEY SHARE``, so an FK insert never waits on it.
Tags are allowed on an archived item: archive is watch-only (archiver#361).
"""

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItem

MAX_TAG_LENGTH = 255
MAX_TAGS = 32


@dataclass(frozen=True)
class TagProblem:
    """One refused tag: its position in the input (``None``: the set) and why."""

    index: int | None
    message: str


class TagError(ValueError):
    """The tags break D2's rule; nothing was stored."""

    def __init__(self, problems: list[TagProblem]):
        super().__init__("; ".join(_describe(p) for p in problems))
        self.problems = problems


class InfoItemNotFoundError(LookupError):
    """No InfoItem has that id."""


def _describe(problem: TagProblem) -> str:
    if problem.index is None:
        return problem.message
    return f"tag {problem.index + 1}: {problem.message}"


def _tag_problem(tag: object) -> str | None:
    if not isinstance(tag, str):
        return "not a string"
    if not tag:
        return "empty"
    if len(tag) > MAX_TAG_LENGTH:
        return f"over {MAX_TAG_LENGTH} characters"
    if "," in tag:
        return "holds a comma"
    if any(unicodedata.category(c) == "Cc" for c in tag):
        return "holds a control character"
    return None


def normalize_tags(tags: Iterable[object]) -> list[str]:
    """The stored form of ``tags``: stripped, exactly de-duplicated, sorted.

    Raises ``TagError`` naming every tag that breaks the rule, or the set when
    more than ``MAX_TAGS`` distinct tags remain.
    """
    problems: list[TagProblem] = []
    kept: set[str] = set()
    for index, raw in enumerate(tags):
        tag = raw.strip() if isinstance(raw, str) else raw
        problem = _tag_problem(tag)
        if problem is not None:
            problems.append(TagProblem(index, problem))
        else:
            kept.add(tag)
    if not problems and len(kept) > MAX_TAGS:
        problems.append(TagProblem(None, f"{len(kept)} tags; at most {MAX_TAGS} per item"))
    if problems:
        raise TagError(problems)
    return sorted(kept)


def split_tags(text: str) -> list[str]:
    """The dashboard input's tags: split on commas, blank pieces dropped."""
    return [piece.strip() for piece in text.split(",") if piece.strip()]


async def _item(session: AsyncSession, info_item_id: ULID, *, lock: bool) -> InfoItem:
    stmt = select(InfoItem).where(InfoItem.info_item_id == info_item_id)
    if lock:
        # FOR NO KEY UPDATE (key_share without read). The session may hold a
        # stale copy; the lock's read must win.
        stmt = stmt.with_for_update(key_share=True).execution_options(populate_existing=True)
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise InfoItemNotFoundError(str(info_item_id))
    return item


async def _store(session: AsyncSession, item: InfoItem, tags: list[str]) -> InfoItem:
    if tags != list(item.tags):
        item.tags = tags
        await session.flush()
    return item


async def set_tags(session: AsyncSession, info_item_id: ULID, tags: Iterable[object]) -> InfoItem:
    """Replace the item's whole tag set. Validated before the item is read."""
    wanted = normalize_tags(tags)
    item = await _item(session, info_item_id, lock=False)
    return await _store(session, item, wanted)


async def add_tags(session: AsyncSession, info_item_id: ULID, tags: Iterable[object]) -> InfoItem:
    """Add ``tags`` to the item's set, under the row lock."""
    new = list(tags)
    normalize_tags(new)  # refuse a bad tag before taking the lock
    item = await _item(session, info_item_id, lock=True)
    return await _store(session, item, normalize_tags([*item.tags, *new]))


async def remove_tag(session: AsyncSession, info_item_id: ULID, tag: str) -> InfoItem:
    """Remove exactly ``tag`` from the item's set, under the row lock."""
    item = await _item(session, info_item_id, lock=True)
    return await _store(session, item, [t for t in item.tags if t != tag])
