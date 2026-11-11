"""A capture's image on InfoSource detail (archiver#380 slice D, D4).

Covers:
  GET /dashboard/info-sources/{id}/captures/{command_id}.png
  the image on #capture-card

1. A stored capture in the captures bucket, with the reader configured: the card
   shows the image; the route serves the PNG, private and immutable, and a
   matching If-None-Match is a 304 with no read
2. A kept capture is read from where it is kept, and the card says so
3. No image: a capture stored before the split (old store), no reader, another
   source's command, a non-PNG, a failed hash, the switch off - each a 404 with
   no read, and the card says why where there is a why
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from co_core.pure.util.hashing import sha256
from ulid import ULID

from src.core import capture_reader
from src.core.capture_reader import CaptureReader
from src.core.models import CaptureCommand, InfoSource
from src.core.services.capture import ENABLED_ENV
from tests.core.test_capture_reader import FakeBlob, FakeStorage

_HEADERS = {"X-ExeDev-UserID": "ext-image", "X-ExeDev-Email": "image@example.com"}

PNG = b"\x89PNG\r\n\x1a\n" + b"a capture" * 50
DIGEST = sha256(PNG)
TEMP = f"gs://co-gcs-captures/temp/{DIGEST}.bin"
KEPT = f"gs://co-gcs-captures/blobs/{DIGEST}.bin"
OLD_TEMP = f"gs://co-gcs-blobs/blobs/{DIGEST}.bin"


@pytest.fixture(autouse=True)
def capture_on(monkeypatch):
    monkeypatch.setenv(ENABLED_ENV, "1")


@pytest.fixture
def storage(client, monkeypatch) -> FakeStorage:
    """The reader the unit's credential would build, over a fake bucket."""
    fake = FakeStorage({TEMP: FakeBlob(PNG), KEPT: FakeBlob(PNG)})
    monkeypatch.setattr(capture_reader, "_bound", CaptureReader(fake))
    return fake


async def _stored(session, *, blob_uri: str = TEMP, **fields) -> CaptureCommand:
    source = InfoSource(url="https://example.com/imaged", source_specs=[])
    session.add(source)
    await session.flush()
    values = dict(
        command_id=str(ULID()),
        info_source_id=source.info_source_id,
        url=source.url,
        viewport_width=1280,
        viewport_height=800,
        full_page=True,
        issued_at=datetime.now(UTC) - timedelta(minutes=5),
        state="stored",
        content_fingerprint=DIGEST,
        blob_uri=blob_uri,
        media_type="image/png",
        size_bytes=len(PNG),
        image_width=1280,
        image_height=2400,
        final_url=source.url,
        captured_at=datetime.now(UTC) - timedelta(minutes=4),
        blob_expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    values.update(fields)
    command = CaptureCommand(**values)
    session.add(command)
    await session.flush()
    return command


def _image_path(command: CaptureCommand) -> str:
    return f"/dashboard/info-sources/{command.info_source_id}/captures/{command.command_id}.png"


async def _card(client, command):
    r = await client.get(
        f"/dashboard/info-sources/{command.info_source_id}/capture",
        headers={**_HEADERS, "HX-Request": "true"},
    )
    assert r.status_code == 200
    return r.text


async def _image(client, path, **headers):
    return await client.get(path, headers={**_HEADERS, **headers})


# --- 1. shown ---


async def test_the_card_shows_the_image(client, session, storage):
    command = await _stored(session)

    card = await _card(client, command)

    assert f'src="{_image_path(command)}"' in card
    assert 'alt="Viewport capture of https://example.com/imaged' in card
    assert storage.gets == []  # the card never reads; the browser asks the route


async def test_the_route_serves_the_png_private_and_immutable(client, session, storage):
    command = await _stored(session)

    r = await _image(client, _image_path(command))

    assert r.status_code == 200
    assert r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert r.headers["etag"] == f'"{DIGEST}"'
    assert r.headers["x-content-type-options"] == "nosniff"
    assert storage.gets == [("co-gcs-captures", f"temp/{DIGEST}.bin")]


async def test_a_matching_etag_is_a_304_with_no_read(client, session, storage):
    command = await _stored(session)

    r = await _image(client, _image_path(command), **{"If-None-Match": f'"{DIGEST}"'})

    assert r.status_code == 304
    assert storage.gets == []


# --- 2. kept ---


async def test_a_kept_capture_is_read_where_it_is_kept(client, session, storage):
    command = await _stored(session, persisted_at=datetime.now(UTC))

    r = await _image(client, _image_path(command))
    card = await _card(client, command)

    assert r.status_code == 200
    assert storage.gets == [("co-gcs-captures", f"blobs/{DIGEST}.bin")]
    assert KEPT in card


async def test_a_kept_capture_past_its_temp_horizon_still_shows(client, session, storage):
    command = await _stored(
        session,
        persisted_at=datetime.now(UTC) - timedelta(days=9),
        blob_expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert (await _image(client, _image_path(command))).status_code == 200


# --- 3. not shown ---


async def test_a_capture_from_before_the_split_has_no_image(client, session, storage):
    """It lives beside raw blobs, which Archiver may not read (content.blobs)."""
    command = await _stored(session, blob_uri=OLD_TEMP, persisted_at=datetime.now(UTC))

    card = await _card(client, command)
    r = await _image(client, _image_path(command))

    assert "<img" not in card
    assert "stored before captures had their own bucket" in card
    assert r.status_code == 404
    assert storage.gets == []


async def test_no_reader_no_image(client, session, monkeypatch):
    monkeypatch.setattr(capture_reader, "_bound", None)
    command = await _stored(session)

    card = await _card(client, command)

    assert "<img" not in card
    assert "not readable on this server" in card
    assert (await _image(client, _image_path(command))).status_code == 404


async def test_an_expired_unkept_capture_has_no_image(client, session, storage):
    command = await _stored(session, blob_expires_at=datetime.now(UTC) - timedelta(hours=1))

    assert "<img" not in await _card(client, command)
    assert (await _image(client, _image_path(command))).status_code == 404
    assert storage.gets == []


async def test_another_sources_command_is_404(client, session, storage):
    command = await _stored(session)
    other = InfoSource(url="https://example.com/other", source_specs=[])
    session.add(other)
    await session.flush()

    path = f"/dashboard/info-sources/{other.info_source_id}/captures/{command.command_id}.png"
    assert (await _image(client, path)).status_code == 404
    assert storage.gets == []


async def test_a_capture_not_stored_is_404(client, session, storage):
    command = await _stored(session, state="requested")
    assert (await _image(client, _image_path(command))).status_code == 404


async def test_only_a_png_is_served(client, session, storage):
    """The bytes are served inline: never under a type a browser would run."""
    command = await _stored(session, media_type="text/html")

    assert "<img" not in await _card(client, command)
    assert (await _image(client, _image_path(command))).status_code == 404
    assert storage.gets == []


async def test_a_failed_hash_check_is_404(client, session, monkeypatch):
    fake = FakeStorage({TEMP: FakeBlob(b"something else")})
    monkeypatch.setattr(capture_reader, "_bound", CaptureReader(fake))
    command = await _stored(session)

    assert (await _image(client, _image_path(command))).status_code == 404


async def test_switch_off_is_404(client, session, storage, monkeypatch):
    monkeypatch.delenv(ENABLED_ENV, raising=False)
    command = await _stored(session)

    assert (await _image(client, _image_path(command))).status_code == 404
    assert storage.gets == []
