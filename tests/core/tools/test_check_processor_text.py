"""The D4 proof CLI (archiver#367): one read from the processor bucket, as the unit reads.

It loads one ``uri`` + ``fingerprint`` pair through the same reader the service
builds (the ``processor-text-reader`` credential, the unit's bucket) and prints
``ok <bytes>`` or the reason. **Never the text.** Read-only, no database.
"""

import io
import json

from co_core.pure.util.hashing import prefixed_sha256, sha256

from src.core.notifications import diff_loader
from src.core.notifications.diff_loader import BUCKET_ENV, CREDENTIAL_NAME
from src.core.tools.check_processor_text import main
from tests.core.notifications.builders import FakeStorage, uri

TEXT = b"Hearing Schedule\nMonday, April 6, secret-ish page text"


def _run(argv, environ):
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdout=out, stderr=err, environ=environ)
    return code, out.getvalue(), err.getvalue()


def _environ(tmp_path, monkeypatch, *texts):
    monkeypatch.setattr(diff_loader, "_storage_client", lambda *, info: FakeStorage(*texts))
    (tmp_path / CREDENTIAL_NAME).write_text(json.dumps({"type": "service_account"}))
    return {"CREDENTIALS_DIRECTORY": str(tmp_path), BUCKET_ENV: "co-gcs-processor"}


def test_ok_prints_the_size_never_the_text(tmp_path, monkeypatch):
    environ = _environ(tmp_path, monkeypatch, TEXT)
    code, out, err = _run([uri(TEXT), prefixed_sha256(sha256(TEXT))], environ)
    assert code == 0
    assert out == f"ok {len(TEXT)}\n"
    assert b"secret-ish" not in (out + err).encode()


def test_a_failed_read_prints_the_reason(tmp_path, monkeypatch):
    environ = _environ(tmp_path, monkeypatch, TEXT)
    code, out, _ = _run([uri(TEXT), prefixed_sha256(sha256(b"other"))], environ)
    assert code == 1
    assert out == "unavailable: text failed its hash check\n"


def test_no_reader_is_an_error(tmp_path):
    code, _, err = _run(["gs://co-gcs-processor/x", "sha256:" + "0" * 64], {})
    assert code == 2
    assert f"{BUCKET_ENV} unset" in err
