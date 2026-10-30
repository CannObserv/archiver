"""Reading a change's two texts from the processor bucket (archiver#367, D4).

Watcher's ``diff_loader`` guards, without its ``process_commands`` lookup: the
URI arrives on the event. Every read is bucket-checked, size-capped and
hash-checked against the fingerprint. The client is built from the unit's own
credential, never ambient. Nothing raises: a failure is a ``ChangeDiff`` naming
why, and the notification still goes.
"""

import json
import logging

import pytest
from co_core.pure.util.hashing import prefixed_sha256, sha256
from google.api_core.exceptions import Forbidden, NotFound

from src.core.notifications import diff_loader
from src.core.notifications.diff_loader import (
    BUCKET_ENV,
    CREDENTIAL_NAME,
    MAX_INPUT_BYTES_ENV,
    TextReader,
    load_change_diff,
    read_stored_text,
    text_reader_from_environ,
)
from tests.core.notifications.builders import FakeStorage, make_event

BUCKET = "co-gcs-processor"
PREVIOUS = b"Hours\nMon-Fri: 9:00 - 17:00\nContact us"
CURRENT = b"Hours\nMon-Sat: 9:00 - 18:00\nContact us"


def address(text: bytes) -> str:
    return prefixed_sha256(sha256(text))


def uri(text: bytes, bucket: str = BUCKET) -> str:
    return f"gs://{bucket}/blobs/{address(text).removeprefix('sha256:')}.bin"


def change(previous: bytes | None = PREVIOUS, current: bytes = CURRENT, **fields):
    return make_event(
        previous_fingerprint=address(previous or b"gone"),
        current_fingerprint=address(current),
        previous_text_uri=uri(previous) if previous is not None else None,
        current_text_uri=uri(current),
        **fields,
    )


def reader(storage: FakeStorage, cap: int = 1024 * 1024) -> TextReader:
    return TextReader(storage, BUCKET, max_input_bytes=cap)


class TestLoadChangeDiff:
    async def test_the_diff_of_the_two_texts(self):
        diff = await load_change_diff(reader(FakeStorage(PREVIOUS, CURRENT)), change())
        assert diff.unavailable is None
        assert any("+ Mon-Sat:" in line for hunk in diff.hunks for line in hunk)

    async def test_no_reader_is_unavailable(self):
        diff = await load_change_diff(None, change())
        assert diff.unavailable == "previous text unreadable"

    async def test_a_null_previous_uri_is_not_stored(self):
        storage = FakeStorage(CURRENT)
        diff = await load_change_diff(reader(storage), change(previous=None))
        assert diff.unavailable == "previous text not stored"
        assert storage.gets == []

    @pytest.mark.parametrize(
        "bad",
        ["gs://co-gcs-blobs/blobs/x.bin", "s3://co-gcs-processor/x", "gs://co-gcs-processor/"],
    )
    async def test_another_bucket_or_scheme_is_never_read(self, bad):
        """The identity reads the processor bucket only; raw blobs stay out of reach."""
        storage = FakeStorage(PREVIOUS, CURRENT)
        event = change().model_copy(update={"previous_text_uri": bad})
        diff = await load_change_diff(reader(storage), event)
        assert diff.unavailable == "previous text not in the processor bucket"
        assert storage.gets == []

    async def test_a_reaped_object_is_unavailable_at_info(self, caplog):
        """A lifecycle 404 is not an error worth paging on, and never a retry."""
        storage = FakeStorage(CURRENT)  # the previous text is gone
        with caplog.at_level(logging.INFO, logger=diff_loader.__name__):
            diff = await load_change_diff(reader(storage), change())
        assert diff.unavailable == "previous text unreadable"
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    async def test_a_404_raised_by_the_client_is_the_same(self):
        storage = FakeStorage(PREVIOUS, CURRENT)
        storage.error = NotFound("gone")
        diff = await load_change_diff(reader(storage), change())
        assert diff.unavailable == "previous text unreadable"

    async def test_a_refused_read_warns(self, caplog):
        storage = FakeStorage(PREVIOUS, CURRENT)
        storage.error = Forbidden("no")
        with caplog.at_level(logging.WARNING, logger=diff_loader.__name__):
            diff = await load_change_diff(reader(storage), change())
        assert diff.unavailable == "previous text unreadable"
        assert [r for r in caplog.records if r.levelno == logging.WARNING]

    async def test_an_object_over_the_cap_is_not_downloaded(self):
        storage = FakeStorage(PREVIOUS, CURRENT)
        diff = await load_change_diff(reader(storage, cap=10), change())
        assert diff.unavailable == "content too large"
        assert all(not b.downloads for b in storage.objects.values())

    async def test_the_download_itself_is_capped(self):
        """An object whose metadata understates its size still can't overrun the cap."""
        storage = FakeStorage(PREVIOUS, CURRENT)
        for blob in storage.objects.values():
            blob.size = 1
        diff = await load_change_diff(reader(storage, cap=10), change())
        assert diff.unavailable == "content too large"
        blob = storage.objects[(BUCKET, uri(PREVIOUS).removeprefix(f"gs://{BUCKET}/"))]
        assert blob.downloads[0]["end"] == 10

    async def test_a_hash_mismatch_is_unavailable(self, caplog):
        storage = FakeStorage(PREVIOUS, CURRENT)
        event = change().model_copy(update={"current_fingerprint": address(b"other")})
        with caplog.at_level(logging.WARNING, logger=diff_loader.__name__):
            diff = await load_change_diff(reader(storage), event)
        assert diff.unavailable == "current text failed its hash check"
        assert [r for r in caplog.records if r.levelno == logging.WARNING]

    async def test_a_whitespace_only_change_says_so(self):
        current = PREVIOUS.replace(b"\n", b"\n\n")
        diff = await load_change_diff(
            reader(FakeStorage(PREVIOUS, current)), change(current=current)
        )
        assert diff.unavailable == "whitespace-only change"

    async def test_anything_else_is_error_and_never_raises(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("bug")

        monkeypatch.setattr(diff_loader, "compute_change_diff", boom)
        diff = await load_change_diff(reader(FakeStorage(PREVIOUS, CURRENT)), change())
        assert diff.unavailable == "error"

    async def test_no_text_reaches_a_log(self, caplog):
        storage = FakeStorage(PREVIOUS, CURRENT)
        event = change().model_copy(update={"current_fingerprint": address(b"other")})
        with caplog.at_level(logging.DEBUG):
            await load_change_diff(reader(storage), event)
            await load_change_diff(reader(storage), change())
        logged = " ".join(str(r.__dict__) for r in caplog.records)
        assert "Mon-Sat" not in logged
        assert "Mon-Fri" not in logged


class TestReadStoredText:
    async def test_ok_returns_the_bytes(self):
        assert await read_stored_text(
            reader(FakeStorage(CURRENT)), uri(CURRENT), address(CURRENT)
        ) == (
            CURRENT,
            None,
        )

    async def test_unavailable_returns_the_reason(self):
        out = await read_stored_text(reader(FakeStorage()), uri(CURRENT), address(CURRENT))
        assert out == (None, "text unreadable")


class TestFromEnviron:
    KEY = {
        "type": "service_account",
        "project_id": "co-test",
        "private_key_id": "k",
        "client_email": "processor-text-reader@co-test.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }

    def creds(self, tmp_path, text: str | None) -> dict[str, str]:
        if text is not None:
            (tmp_path / CREDENTIAL_NAME).write_text(text)
        return {"CREDENTIALS_DIRECTORY": str(tmp_path), BUCKET_ENV: BUCKET}

    def test_unset_bucket_is_dormant(self):
        reader_, reason = text_reader_from_environ({})
        assert reader_ is None
        assert reason == f"{BUCKET_ENV} unset"

    @pytest.mark.parametrize("text", [None, "", "\n"])
    def test_a_missing_or_empty_credential_is_none(self, tmp_path, text):
        """``SetCredential=processor-text-reader:\\n`` is the unit's fallback."""
        reader_, reason = text_reader_from_environ(self.creds(tmp_path, text))
        assert reader_ is None
        assert reason == f"no {CREDENTIAL_NAME} credential"

    def test_an_unreadable_key_is_none_and_names_no_content(self, tmp_path):
        reader_, reason = text_reader_from_environ(self.creds(tmp_path, "not json {secret}"))
        assert reader_ is None
        assert "secret" not in reason

    def test_the_client_is_built_from_the_credential_explicitly(self, tmp_path, monkeypatch):
        built = {}

        def fake_client(*, info):
            built["info"] = info
            return FakeStorage()

        monkeypatch.setattr(diff_loader, "_storage_client", fake_client)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/ambient.json")
        env = self.creds(tmp_path, json.dumps(self.KEY)) | {MAX_INPUT_BYTES_ENV: "2048"}
        reader_, reason = text_reader_from_environ(env)
        assert reason is None
        assert reader_.bucket == BUCKET
        assert reader_.max_input_bytes == 2048
        assert built["info"]["client_email"] == self.KEY["client_email"]

    @pytest.mark.parametrize("raw", ["0", "-5", "lots"])
    def test_a_bad_cap_keeps_the_default(self, tmp_path, monkeypatch, raw):
        monkeypatch.setattr(diff_loader, "_storage_client", lambda *, info: FakeStorage())
        env = self.creds(tmp_path, json.dumps(self.KEY)) | {MAX_INPUT_BYTES_ENV: raw}
        reader_, _ = text_reader_from_environ(env)
        assert reader_.max_input_bytes == 1024 * 1024

    def test_close_closes_the_client(self):
        storage = FakeStorage()
        reader(storage).close()
        assert storage.closed
