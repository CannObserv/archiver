"""Pydantic-level tests for ErrorEnvelope + FieldError."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.api.errors import ErrorEnvelope, FieldError


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
