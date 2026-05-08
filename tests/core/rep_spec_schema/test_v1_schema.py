"""RepSpec v1 envelope + provider sub-schema shape tests."""

import json
from pathlib import Path

import jsonschema
import pytest

_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "src/core/rep_spec_schema"

ENVELOPE_PATH = _SCHEMA_DIR / "v1.json"
GCS_PATH = _SCHEMA_DIR / "providers/gcs/v1.json"
GDRIVE_PATH = _SCHEMA_DIR / "providers/gdrive/v1.json"
IA_PATH = _SCHEMA_DIR / "providers/ia/v1.json"


@pytest.fixture(scope="module")
def envelope_schema():
    return json.loads(ENVELOPE_PATH.read_text())


@pytest.fixture(scope="module")
def envelope_validator(envelope_schema):
    return jsonschema.Draft202012Validator(envelope_schema)


@pytest.fixture(scope="module")
def gcs_schema():
    return json.loads(GCS_PATH.read_text())


@pytest.fixture(scope="module")
def gcs_validator(gcs_schema):
    return jsonschema.Draft202012Validator(gcs_schema)


def _valid_gcs_rep_spec(**overrides):
    doc = {
        "provider": "gcs",
        "credentials_alias": "gcs-cannobserv-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.date}.html",
        "required_fields": ["info_item.slug", "source_revision.date"],
        "object_options": {
            "storage_class": "STANDARD",
            "cache_control": "public, max-age=3600",
        },
    }
    doc.update(overrides)
    return doc


def test_envelope_accepts_complete_gcs_rep_spec(envelope_validator):
    """Complete, valid GCS RepSpec passes envelope validation."""
    envelope_validator.validate(_valid_gcs_rep_spec())


def test_envelope_rejects_missing_path_template(envelope_validator):
    """Omitting required field path_template triggers a ValidationError."""
    doc = _valid_gcs_rep_spec()
    del doc["path_template"]
    with pytest.raises(jsonschema.ValidationError):
        envelope_validator.validate(doc)


def test_envelope_rejects_unknown_provider(envelope_validator):
    """Provider value not in {gcs, gdrive, ia} is rejected."""
    doc = _valid_gcs_rep_spec(provider="ftp")
    with pytest.raises(jsonschema.ValidationError):
        envelope_validator.validate(doc)


def test_gcs_sub_schema_rejects_bad_storage_class(gcs_validator):
    """GCS object_options with an invalid storage_class enum value is rejected."""
    doc = {"storage_class": "BANANA", "cache_control": "no-cache"}
    with pytest.raises(jsonschema.ValidationError):
        gcs_validator.validate(doc)


def test_envelope_accepts_gdrive_provider():
    """gdrive provider with minimal fields validates."""
    schema = json.loads(ENVELOPE_PATH.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    doc = {
        "provider": "gdrive",
        "credentials_alias": "gdrive-cannobserv",
        "path_template": "archive/{info_item.slug}",
        "required_fields": ["info_item.slug"],
    }
    validator.validate(doc)


def test_envelope_accepts_ia_provider():
    """ia provider with minimal fields validates."""
    schema = json.loads(ENVELOPE_PATH.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    doc = {
        "provider": "ia",
        "credentials_alias": "ia-cannobserv",
        "path_template": "archive/{info_item.slug}",
        "required_fields": ["info_item.slug"],
        "object_options": {"collection": "cannabis-observer", "mediatype": "web"},
    }
    validator.validate(doc)


def test_gcs_sub_schema_accepts_valid_object_options(gcs_validator):
    """Full valid GCS object_options passes the sub-schema."""
    doc = {
        "storage_class": "NEARLINE",
        "cache_control": "public, max-age=86400",
        "content_disposition": "inline",
    }
    gcs_validator.validate(doc)


def test_gcs_sub_schema_rejects_unknown_property(gcs_validator):
    """additionalProperties: false rejects unknown keys in GCS object_options."""
    doc = {"storage_class": "STANDARD", "unexpected_key": "value"}
    with pytest.raises(jsonschema.ValidationError):
        gcs_validator.validate(doc)
