"""path_template parsing and the create/update-time contract (archiver#168).

One parser serves both the validation gate and the renderer, so a template that
validates is a template that renders — the drift these tests exist to prevent.
"""

import pytest

from src.core.replication.errors import ReplicationRenderError
from src.core.replication.template import (
    OCCASION_KEYS,
    OCCASION_NAMESPACE,
    MalformedTemplateError,
    parse_placeholders,
    validate_path_template,
)

# --- parsing ---


def test_parses_namespaced_placeholders_in_order():
    """Every {ns.key} is returned as an (namespace, key) pair, left to right."""
    found = parse_placeholders("archive/{info_item.slug}/{source_revision.fingerprint}.html")
    assert found == [("info_item", "slug"), ("source_revision", "fingerprint")]


def test_literal_only_template_has_no_placeholders():
    """A template with no braces parses to an empty list, not an error."""
    assert parse_placeholders("archive/fixed.html") == []


def test_placeholder_without_namespace_is_malformed():
    """{slug} cannot resolve: the bag is namespaced and required_fields is 'ns.key'."""
    with pytest.raises(MalformedTemplateError):
        parse_placeholders("archive/{slug}.html")


def test_unbalanced_brace_is_malformed():
    """An unclosed placeholder is a typo that must not reach a frozen document."""
    with pytest.raises(MalformedTemplateError):
        parse_placeholders("archive/{info_item.slug/x.html")


def test_stray_closing_brace_is_malformed():
    """A closing brace with no opener is equally a typo."""
    with pytest.raises(MalformedTemplateError):
        parse_placeholders("archive/info_item.slug}/x.html")


def test_stray_braces_on_both_sides_are_malformed():
    """Counting braces balances here; the template is still a typo (CR #1).

    A stray opener and a stray closer cancel in the count, so the check has to
    be 'nothing outside a well-formed placeholder', not 'equal counts'. Left
    unchecked these render literally into a permanent path, under a document
    that freezes on assignment.
    """
    with pytest.raises(MalformedTemplateError):
        parse_placeholders("}{info_item.slug}{")


def test_stray_braces_reported_by_the_validation_gate():
    errors = validate_path_template("}{source_revision.id}{", required_fields=[])
    assert any(e["path"] == "/path_template" for e in errors)


def test_malformed_template_error_is_a_replication_render_error():
    """One base the issuance path can catch (CR #4).

    archiver#169 records an unrenderable assignment as a skip; an error class
    outside that hierarchy would escape into the content.revisions consumer loop
    instead.
    """
    assert issubclass(MalformedTemplateError, ReplicationRenderError)


# --- the occasion namespace ---


def test_occasion_namespace_keys_are_the_declared_four():
    """The occasion vocabulary is closed — a renderer supplies exactly these."""
    assert OCCASION_NAMESPACE == "source_revision"
    assert OCCASION_KEYS == frozenset({"id", "date", "fingerprint", "captured_at"})


def test_unknown_occasion_key_rejected():
    """{source_revision.slug} names nothing the renderer can supply."""
    errors = validate_path_template(
        "archive/{source_revision.slug}/{source_revision.id}", required_fields=[]
    )
    assert any("source_revision.slug" in e["message"] for e in errors)


def test_occasion_key_needs_no_required_fields_entry():
    """The occasion is supplied per replication, not from the InfoItem's bag."""
    errors = validate_path_template(
        "archive/{source_revision.date}/{source_revision.id}", required_fields=[]
    )
    assert errors == []


def test_occasion_namespace_in_required_fields_rejected():
    """Listing it would demand a bag entry no InfoItem can hold."""
    errors = validate_path_template(
        "archive/{source_revision.date}/{source_revision.id}",
        required_fields=["source_revision.date"],
    )
    assert any(e["path"] == "/required_fields" for e in errors)


# --- placeholder / required_fields divergence ---


def test_bag_placeholder_absent_from_required_fields_rejected():
    """The divergence that freezes into an unrenderable document."""
    errors = validate_path_template(
        "archive/{org.acronym_slug}/{source_revision.id}", required_fields=["info_item.slug"]
    )
    assert any("org.acronym_slug" in e["message"] for e in errors)


def test_bag_placeholder_declared_in_required_fields_ok():
    errors = validate_path_template(
        "archive/{info_item.slug}/{source_revision.id}.html",
        required_fields=["info_item.slug"],
    )
    assert errors == []


def test_required_field_unused_by_template_is_allowed():
    """required_fields may exceed the template — it also gates assignment."""
    errors = validate_path_template(
        "archive/{info_item.slug}/{source_revision.id}",
        required_fields=["info_item.slug", "org.acronym_slug"],
    )
    assert errors == []


# --- R2: the per-occasion discriminator ---


def test_template_without_discriminator_rejected():
    """A date-only template collides for two revisions captured the same day."""
    errors = validate_path_template(
        "archive/{info_item.slug}/{source_revision.date}.html",
        required_fields=["info_item.slug"],
    )
    assert any("discriminator" in e["message"] for e in errors)


def test_fingerprint_satisfies_the_discriminator():
    errors = validate_path_template(
        "archive/{info_item.slug}/{source_revision.fingerprint}.html",
        required_fields=["info_item.slug"],
    )
    assert errors == []


def test_revision_id_satisfies_the_discriminator():
    errors = validate_path_template(
        "archive/{info_item.slug}/{source_revision.id}.html",
        required_fields=["info_item.slug"],
    )
    assert errors == []


# --- malformed templates arrive as errors, not exceptions ---


def test_malformed_template_reported_as_validation_error():
    """The create/update gate reports; it does not raise at the caller."""
    errors = validate_path_template("archive/{slug}.html", required_fields=[])
    assert errors
    assert all(e["path"] == "/path_template" for e in errors)
