"""Direct unit tests for error_from_response parsing + status → exception mapping."""

from __future__ import annotations

import json

from archiver_client.errors import (
    AuthError,
    InformationError,
    NotFound,
    ServerError,
    ValidationError,
    error_from_response,
)


def _envelope(kind: str, message: str, errors=None, data=None) -> bytes:
    body = {"kind": kind, "message": message, "errors": errors or []}
    if data is not None:
        body["data"] = data
    return json.dumps({"detail": body}).encode("utf-8")


# --- Envelope-parsing tests ---


def test_404_envelope_populates_typed_attrs():
    err = error_from_response(404, _envelope("lookup", "InfoItem not found"))
    assert isinstance(err, NotFound)
    assert err.status_code == 404
    assert err.kind == "lookup"
    assert err.message == "InfoItem not found"
    assert err.errors == []
    assert err.data is None


def test_422_schema_envelope_populates_errors():
    body = _envelope(
        "schema",
        "invalid rep_spec",
        errors=[{"path": "/document/provider", "message": "missing", "code": "required"}],
    )
    err = error_from_response(422, body)
    assert isinstance(err, ValidationError)
    assert err.kind == "schema"
    assert len(err.errors) == 1
    assert err.errors[0]["path"] == "/document/provider"


def test_409_conflict_envelope_populates_data():
    body = _envelope(
        "conflict",
        "duplicate",
        data={"existing_info_source_id": "01HXX..."},
    )
    err = error_from_response(409, body)
    assert isinstance(
        err, InformationError
    )  # 409 maps to base class (or Conflict subclass if added)
    assert err.kind == "conflict"
    assert err.data == {"existing_info_source_id": "01HXX..."}


def test_500_envelope():
    body = _envelope("server", "internal server error")
    err = error_from_response(500, body)
    assert isinstance(err, ServerError)
    assert err.kind == "server"


def test_401_envelope():
    body = _envelope("auth", "Invalid API key")
    err = error_from_response(401, body)
    assert isinstance(err, AuthError)
    assert err.kind == "auth"


def test_malformed_envelope_falls_back_to_unknown_kind():
    """Defensive: a body that doesn't match the envelope shape gets kind='unknown'."""
    err = error_from_response(500, b"not json at all")
    assert isinstance(err, ServerError)
    assert err.kind == "unknown"
    assert err.message  # something non-empty


def test_body_attr_still_populated_for_debugging():
    body = _envelope("lookup", "x")
    err = error_from_response(404, body)
    assert isinstance(err.body, str)
    assert "lookup" in err.body


# --- Status → exception class mapping (preserved from prior suite) ---


def test_403_returns_auth_error():
    err = error_from_response(403, _envelope("auth", "forbidden"))
    assert isinstance(err, AuthError)
    assert err.status_code == 403


def test_503_returns_server_error():
    err = error_from_response(503, _envelope("server", "unavailable"))
    assert isinstance(err, ServerError)


def test_unknown_status_returns_base_information_error():
    err = error_from_response(418, _envelope("teapot", "short and stout"))
    assert type(err) is InformationError
    assert err.status_code == 418
    assert err.kind == "teapot"


def test_body_decode_replaces_invalid_utf8():
    err = error_from_response(500, b"\xff\xfe broken")
    assert err.body is not None
    # Should not raise — replacement chars in body, not an exception.


def test_body_truncated_at_2000_chars():
    huge = b"x" * 5000
    err = error_from_response(500, huge)
    assert len(err.body) == 2000
