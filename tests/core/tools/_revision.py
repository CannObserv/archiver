"""A captured revision behind an item, for the move-preview tests (archiver#333).

The save 409, the link 409 and the follower's move log all render against the
item's latest revision; each test file needs the same bound, captured item, so
the helper lives beside them rather than in one of them.
"""

from datetime import UTC, datetime

from ulid import ULID

from src.core.models import InfoItem, InfoItemSource, InfoSource, SourceRevision

# Production's spec shape (read via #348, 2026-10-12): every revision field
# that differs between the example occasion and a real one.
REVISION_PATH = (
    "organizations/{org.title_slug}/{source_revision.year}/"
    "{source_revision.datetime_time_segment}-{source_revision.id}.{source_revision.ext}"
)
_CAPTURED_AT = datetime(2025, 5, 2, 10, 11, 12, tzinfo=UTC)


async def capture_revision(session, item: InfoItem) -> SourceRevision:
    """Bind ``item`` to a fresh source and capture one PDF revision under it."""
    source = InfoSource(
        url=f"https://example.com/{ULID()}",
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )
    session.add(source)
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )
    revision = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:" + "c" * 64,
        captured_at=_CAPTURED_AT,
        content_cache_uri="file:///var/lib/replicator/blobs/cc.bin",
        source_media_type="application/pdf",
    )
    session.add(revision)
    await session.flush()
    return revision


def revision_path(slug: str, revision: SourceRevision) -> str:
    """``REVISION_PATH`` for ``slug`` and ``revision``, spelled out by hand."""
    return f"organizations/{slug}/2025/2025_05_02-10_11_12-{revision.source_revision_id}.pdf"
