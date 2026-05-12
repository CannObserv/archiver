"""Pydantic-level tests for ErrorEnvelope + FieldError."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError as PydanticValidationError

from src.api.errors import ErrorEnvelope, FieldError, raise_422, raise_envelope


def test_field_error_minimal():
    fe = FieldError(path="/document/provider", message="must be one of: gcs, gdrive, ia")
    dumped = fe.model_dump(exclude_none=True)
    assert dumped == {"path": "/document/provider", "message": "must be one of: gcs, gdrive, ia"}


def test_field_error_with_code():
    fe = FieldError(path="", message="required", code="required")
    dumped = fe.model_dump(exclude_none=True)
    assert dumped == {"path": "", "message": "required", "code": "required"}


def test_envelope_minimal_omits_data_and_empty_errors_list_stays():
    env = ErrorEnvelope(kind="lookup", message="InfoItem not found")
    dumped = env.model_dump(exclude_none=True)
    # `errors` is always present (even when empty); `data` omitted.
    assert dumped == {"kind": "lookup", "message": "InfoItem not found", "errors": []}


def test_envelope_with_errors():
    env = ErrorEnvelope(
        kind="schema",
        message="invalid rep_spec",
        errors=[
            FieldError(path="/document/provider", message="missing required key"),
            FieldError(path="/document/path_template", message="must be non-empty"),
        ],
    )
    dumped = env.model_dump(exclude_none=True)
    assert dumped["kind"] == "schema"
    assert len(dumped["errors"]) == 2
    assert dumped["errors"][0]["path"] == "/document/provider"


def test_envelope_with_data():
    env = ErrorEnvelope(
        kind="conflict",
        message="an InfoSource already exists for this URL",
        data={"url": "https://example.com", "existing_info_source_id": "01HXX..."},
    )
    dumped = env.model_dump(exclude_none=True)
    assert dumped["data"]["existing_info_source_id"] == "01HXX..."


def test_envelope_rejects_unknown_kind():
    with pytest.raises(PydanticValidationError):
        ErrorEnvelope(kind="not-a-real-kind", message="x")


def test_raise_envelope_raises_http_exception_with_envelope_detail():
    with pytest.raises(HTTPException) as exc_info:
        raise_envelope(404, "lookup", "InfoItem not found")
    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail == {"kind": "lookup", "message": "InfoItem not found", "errors": []}


def test_raise_envelope_preserves_cause_via_source_exc():
    """raise_envelope must chain via `from source_exc` so ruff B904 is satisfied."""
    src = ValueError("bad ulid")
    with pytest.raises(HTTPException) as exc_info:
        raise_envelope(422, "domain", "info_item_id is not a valid ULID", source_exc=src)
    assert exc_info.value.__cause__ is src


def test_raise_envelope_with_errors_and_data():
    fes = [{"path": "/foo", "message": "required", "code": "required"}]
    with pytest.raises(HTTPException) as exc_info:
        raise_envelope(
            409,
            "conflict",
            "duplicate",
            errors=fes,
            data={"existing_id": "01HXX..."},
        )
    detail = exc_info.value.detail
    assert detail["errors"] == fes
    assert detail["data"] == {"existing_id": "01HXX..."}


def test_raise_422_is_shorthand_for_kind_schema():
    """raise_422 defaults kind to 'schema'; can be overridden."""
    with pytest.raises(HTTPException) as exc_info:
        raise_422("invalid rep_spec", errors=[{"path": "/x", "message": "bad"}])
    detail = exc_info.value.detail
    assert exc_info.value.status_code == 422
    assert detail["kind"] == "schema"
    assert detail["message"] == "invalid rep_spec"


def test_raise_422_kind_override():
    with pytest.raises(HTTPException) as exc_info:
        raise_422("rep_fields incomplete", kind="domain", errors=[{"path": "/", "message": "x"}])
    assert exc_info.value.detail["kind"] == "domain"


def test_raise_422_preserves_cause_via_source_exc():
    src = ValueError("bad provider")
    with pytest.raises(HTTPException) as exc_info:
        raise_422("invalid rep_spec", source_exc=src)
    assert exc_info.value.__cause__ is src
