"""Reading a capture's PNG from the captures bucket (archiver#380 slice D, D4).

The processor-text reader's guards (``diff_loader``), for images: the captures
bucket only, so raw blobs stay out of reach; size-capped; hash-checked against
the capture's digest; the client built from the unit's own credential, never
ambient.
"""

import json
import logging

import pytest
from co_core.pure.util.hashing import sha256
from google.api_core.exceptions import Forbidden, NotFound

from src.core import capture_reader
from src.core.capture_reader import (
    CREDENTIAL_NAME,
    MAX_IMAGE_BYTES_ENV,
    CaptureReader,
    CaptureUnavailable,
    announced_capture_reader,
    capture_reader_from_environ,
    read_capture,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 100
DIGEST = sha256(PNG)
KEPT = f"gs://co-gcs-captures/blobs/{DIGEST}.bin"


class FakeBlob:
    def __init__(self, data: bytes, size: int | None = None):
        self.data = data
        self.size = len(data) if size is None else size
        self.ranges: list[int | None] = []

    def download_as_bytes(self, *, end=None, checksum=None, timeout=None):
        self.ranges.append(end)
        return self.data if end is None else self.data[: end + 1]


class FakeBucket:
    def __init__(self, storage, name):
        self.storage, self.name = storage, name

    def get_blob(self, key, timeout=None):
        self.storage.gets.append((self.name, key))
        if self.storage.error is not None:
            raise self.storage.error
        return self.storage.objects.get((self.name, key))


class FakeStorage:
    def __init__(self, objects: dict[str, FakeBlob] | None = None):
        self.objects = {
            (u.split("/")[2], u.split("/", 3)[3]): blob for u, blob in (objects or {}).items()
        }
        self.gets: list[tuple[str, str]] = []
        self.error: Exception | None = None
        self.closed = False

    def bucket(self, name):
        return FakeBucket(self, name)

    def close(self):
        self.closed = True


def reader(storage: FakeStorage, cap: int = 1024 * 1024) -> CaptureReader:
    return CaptureReader(storage, max_image_bytes=cap)


class TestRead:
    async def test_a_kept_capture_is_read(self):
        storage = FakeStorage({KEPT: FakeBlob(PNG)})
        assert await read_capture(reader(storage), KEPT, DIGEST) == PNG
        assert storage.gets == [("co-gcs-captures", f"blobs/{DIGEST}.bin")]

    @pytest.mark.parametrize(
        "bad",
        [
            f"gs://co-gcs-replicator/blobs/{DIGEST}.bin",
            f"gs://co-gcs-blobs/blobs/{DIGEST}.bin",
            f"gs://co-gcs-captures-other/blobs/{DIGEST}.bin",
            "gs://co-gcs-captures/",
            f"file:///var/blobs/{DIGEST}.bin",
        ],
    )
    async def test_nothing_outside_the_captures_bucket_is_ever_read(self, bad):
        """Archiver's content.blobs boundary: raw blobs share the other buckets."""
        storage = FakeStorage({bad: FakeBlob(PNG)} if bad.count("/") > 3 else {})
        with pytest.raises(CaptureUnavailable, match="not in the captures bucket"):
            await read_capture(reader(storage), bad, DIGEST)
        assert storage.gets == []

    async def test_a_missing_object_is_unavailable(self, caplog):
        caplog.set_level(logging.INFO)
        with pytest.raises(CaptureUnavailable, match="not found"):
            await read_capture(reader(FakeStorage()), KEPT, DIGEST)

    async def test_a_404_raised_by_the_client_is_the_same(self):
        storage = FakeStorage({KEPT: FakeBlob(PNG)})
        storage.error = NotFound("gone")
        with pytest.raises(CaptureUnavailable, match="not found"):
            await read_capture(reader(storage), KEPT, DIGEST)

    async def test_a_refused_read_warns_without_naming_the_key(self, caplog):
        storage = FakeStorage({KEPT: FakeBlob(PNG)})
        storage.error = Forbidden("no")
        with pytest.raises(CaptureUnavailable, match="unreadable"):
            await read_capture(reader(storage), KEPT, DIGEST)
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    async def test_an_object_over_the_cap_is_not_downloaded(self):
        blob = FakeBlob(PNG)
        storage = FakeStorage({KEPT: blob})
        with pytest.raises(CaptureUnavailable, match="too large"):
            await read_capture(reader(storage, cap=10), KEPT, DIGEST)
        assert blob.ranges == []

    async def test_the_download_itself_is_capped(self):
        """A wrong reported size can't overrun the cap: the download is ranged."""
        blob = FakeBlob(PNG, size=5)
        storage = FakeStorage({KEPT: blob})
        with pytest.raises(CaptureUnavailable):
            await read_capture(reader(storage, cap=10), KEPT, DIGEST)
        assert blob.ranges == [10]

    async def test_a_hash_mismatch_is_unavailable(self, caplog):
        storage = FakeStorage({KEPT: FakeBlob(b"not the capture")})
        with pytest.raises(CaptureUnavailable, match="hash check"):
            await read_capture(reader(storage), KEPT, DIGEST)
        assert any(r.levelno == logging.WARNING for r in caplog.records)


class TestFromEnviron:
    def test_no_credentials_directory_is_dormant(self):
        assert capture_reader_from_environ({}) == (None, f"no {CREDENTIAL_NAME} credential")

    def test_no_credential_file_is_dormant(self, tmp_path):
        r, why = capture_reader_from_environ({"CREDENTIALS_DIRECTORY": str(tmp_path)})
        assert r is None
        assert why == f"no {CREDENTIAL_NAME} credential"

    def test_the_empty_fallback_is_none(self, tmp_path):
        (tmp_path / CREDENTIAL_NAME).write_text("\n")
        r, why = capture_reader_from_environ({"CREDENTIALS_DIRECTORY": str(tmp_path)})
        assert r is None
        assert why == f"empty {CREDENTIAL_NAME} credential"

    def test_an_unreadable_key_is_none_and_names_no_content(self, tmp_path):
        (tmp_path / CREDENTIAL_NAME).write_text("{not json secret-ish")
        r, why = capture_reader_from_environ({"CREDENTIALS_DIRECTORY": str(tmp_path)})
        assert r is None
        assert "secret" not in why
        assert why.startswith(f"unusable {CREDENTIAL_NAME} credential")

    def test_the_client_is_built_from_the_credential_explicitly(self, tmp_path, monkeypatch):
        info = {"type": "service_account", "project_id": "p"}
        (tmp_path / CREDENTIAL_NAME).write_text(json.dumps(info))
        built = []
        monkeypatch.setattr(
            capture_reader, "_storage_client", lambda *, info: built.append(info) or FakeStorage()
        )
        r, why = capture_reader_from_environ({"CREDENTIALS_DIRECTORY": str(tmp_path)})
        assert why is None
        assert isinstance(r, CaptureReader)
        assert built == [info]

    @pytest.mark.parametrize("raw", ["0", "-5", "lots"])
    def test_a_bad_cap_keeps_the_default(self, tmp_path, monkeypatch, raw):
        (tmp_path / CREDENTIAL_NAME).write_text(json.dumps({"project_id": "p"}))
        monkeypatch.setattr(capture_reader, "_storage_client", lambda *, info: FakeStorage())
        r, _ = capture_reader_from_environ(
            {"CREDENTIALS_DIRECTORY": str(tmp_path), MAX_IMAGE_BYTES_ENV: raw}
        )
        assert r.max_image_bytes == capture_reader.DEFAULT_MAX_IMAGE_BYTES

    def test_close_closes_the_client(self):
        storage = FakeStorage()
        reader(storage).close()
        assert storage.closed


class TestAnnounced:
    def test_dormant_is_info(self, caplog):
        caplog.set_level(logging.INFO)
        assert announced_capture_reader({}) is None
        assert [r.levelno for r in caplog.records] == [logging.INFO]

    def test_a_loaded_but_empty_credential_warns(self, tmp_path, caplog):
        """The unit meant to read (it loads the credential) and can't: say so once."""
        (tmp_path / CREDENTIAL_NAME).write_text("")
        assert announced_capture_reader({"CREDENTIALS_DIRECTORY": str(tmp_path)}) is None
        assert [r.levelno for r in caplog.records] == [logging.WARNING]

    def test_configured_is_info(self, tmp_path, monkeypatch, caplog):
        caplog.set_level(logging.INFO)
        (tmp_path / CREDENTIAL_NAME).write_text(json.dumps({"project_id": "p"}))
        monkeypatch.setattr(capture_reader, "_storage_client", lambda *, info: FakeStorage())
        assert announced_capture_reader({"CREDENTIALS_DIRECTORY": str(tmp_path)}) is not None
        assert [r.levelno for r in caplog.records] == [logging.INFO]
