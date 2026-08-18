"""RepSpec validator — envelope + provider dispatch tests."""

from src.core.rep_spec_schema.validator import validate_rep_spec


def _valid_gcs(**overrides):
    doc = {
        "provider": "gcs",
        "credentials_alias": "gcs-cannobserv-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.fingerprint}.html",
        "required_fields": ["info_item.slug"],
        "object_options": {
            "storage_class": "STANDARD",
            "cache_control": "public, max-age=3600",
        },
    }
    doc.update(overrides)
    return doc


def _valid_gdrive(**overrides):
    doc = {
        "provider": "gdrive",
        "credentials_alias": "gdrive-cannobserv",
        "path_template": "archive/{info_item.slug}/{source_revision.id}",
        "required_fields": ["info_item.slug"],
        "object_options": {"folder_id": "abc123"},
    }
    doc.update(overrides)
    return doc


def _valid_ia(**overrides):
    doc = {
        "provider": "ia",
        "credentials_alias": "ia-cannobserv",
        "path_template": "archive/{info_item.slug}/{source_revision.id}",
        "required_fields": ["info_item.slug"],
        "object_options": {"collection": "cannabis-observer", "mediatype": "web"},
    }
    doc.update(overrides)
    return doc


# --- happy paths ---


def test_valid_gcs_ok():
    """Complete valid GCS RepSpec → ok=True, errs=[]."""
    ok, errs = validate_rep_spec(_valid_gcs())
    assert ok is True
    assert errs == []


def test_valid_gdrive_ok():
    """Complete valid gdrive spec → ok=True, errs=[]."""
    ok, errs = validate_rep_spec(_valid_gdrive())
    assert ok is True
    assert errs == []


def test_valid_ia_ok():
    """Complete valid ia spec → ok=True, errs=[]."""
    ok, errs = validate_rep_spec(_valid_ia())
    assert ok is True
    assert errs == []


# --- envelope-level failures ---


def test_unknown_provider_rejected():
    """provider='ftp' → ok=False, error mentions provider."""
    doc = _valid_gcs(provider="ftp")
    ok, errs = validate_rep_spec(doc)
    assert ok is False
    assert errs
    messages = " ".join(e["message"] for e in errs)
    assert "provider" in messages or "ftp" in messages


def test_missing_path_template_rejected():
    """Omit path_template → ok=False, error path includes 'path_template' or '/'."""
    doc = _valid_gcs()
    del doc["path_template"]
    ok, errs = validate_rep_spec(doc)
    assert ok is False
    assert errs
    paths = " ".join(e["path"] for e in errs)
    assert "path_template" in paths or paths.strip("/") == "" or "/" in paths


# --- provider sub-schema failures ---


def test_gcs_bad_storage_class_rejected():
    """GCS object_options.storage_class='BANANA' → ok=False, error mentions storage_class."""
    doc = _valid_gcs()
    doc["object_options"] = {"storage_class": "BANANA"}
    ok, errs = validate_rep_spec(doc)
    assert ok is False
    assert errs
    messages = " ".join(e["message"] for e in errs)
    paths = " ".join(e["path"] for e in errs)
    assert "storage_class" in messages or "storage_class" in paths
    assert "/object_options/" in paths


# --- path_template contract (archiver#168) ---


def test_template_without_occasion_discriminator_rejected():
    """R2: a date-only template renders one key for two revisions captured that day."""
    doc = _valid_gcs(
        path_template="archive/{info_item.slug}/{source_revision.date}.html",
        required_fields=["info_item.slug"],
    )
    ok, errs = validate_rep_spec(doc)
    assert ok is False
    assert any("discriminator" in e["message"] for e in errs)


def test_template_placeholder_absent_from_required_fields_rejected():
    """The divergence that freezes into an unrenderable document (#83)."""
    doc = _valid_gcs(
        path_template="archive/{org.acronym_slug}/{source_revision.id}.html",
        required_fields=["info_item.slug"],
    )
    ok, errs = validate_rep_spec(doc)
    assert ok is False
    assert any("org.acronym_slug" in e["message"] for e in errs)


def test_occasion_namespace_in_required_fields_rejected():
    """source_revision.* is supplied per occasion; no bag can hold it."""
    doc = _valid_gcs(
        path_template="archive/{source_revision.date}/{source_revision.id}.html",
        required_fields=["source_revision.date"],
    )
    ok, errs = validate_rep_spec(doc)
    assert ok is False
    assert any(e["path"] == "/required_fields" for e in errs)


def test_malformed_placeholder_rejected():
    """{slug} has no namespace, so nothing can resolve it."""
    doc = _valid_gcs(path_template="archive/{slug}/{source_revision.id}.html")
    ok, errs = validate_rep_spec(doc)
    assert ok is False
    assert any(e["path"] == "/path_template" for e in errs)


def test_template_checks_skipped_when_the_envelope_already_failed():
    """A missing path_template reports once, not twice under two vocabularies."""
    doc = _valid_gcs()
    del doc["path_template"]
    ok, errs = validate_rep_spec(doc)
    assert ok is False
    assert not any("discriminator" in e["message"] for e in errs)


def test_template_errors_reported_alongside_an_unrelated_envelope_error():
    """An unrelated envelope failure must not hide the template's (CR #8).

    Suppressing template checks on *any* envelope error costs the author a
    round trip: fix the alias, resubmit, learn the template is wrong too.
    """
    doc = _valid_gcs(path_template="archive/{info_item.slug}/{source_revision.date}.html")
    del doc["credentials_alias"]
    ok, errs = validate_rep_spec(doc)
    assert ok is False
    assert any("credentials_alias" in e["message"] for e in errs)
    assert any("discriminator" in e["message"] for e in errs)


# --- required_fields pattern violation ---


def test_required_fields_pattern_violation():
    """required_fields item 'orgacronym' (no dot) → ok=False."""
    doc = _valid_gcs(required_fields=["info_item.slug", "orgacronym"])
    ok, errs = validate_rep_spec(doc)
    assert ok is False
    assert errs
