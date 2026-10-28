"""What a notification carries: Watcher's ``ContentConfig``, validated at write time (#363, D4).

``default`` applies to every event unless ``overrides`` holds that event's
options. The fields and defaults are Watcher's (``src/api/schemas/content_config.py``
at ``ebd1be5``); the validation is stricter:

- **an unknown key is refused** at every level. Watcher ignores them so rows
  holding its two retired keys still load; those never reach this table,
  because the importer drops them (``RETIRED_CONTENT_KEYS``) and refuses any other;
- an override key must be a known event;
- ``title_template`` / ``body_template`` must **parse** in Jinja's
  ``SandboxedEnvironment``. Only syntax: the variables are #367's render
  context, which does not exist yet. #367 renders in the sandbox too.

``include_tags`` is stored and inert until tags exist (#362).
"""

from typing import Annotated, Any

from jinja2 import TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import AfterValidator, BaseModel, Field, StrictBool, StrictInt, ValidationError

from src.core.models.notification_subscription import NotificationEvent

RETIRED_CONTENT_KEYS = frozenset({"include_significance", "include_change_dashboard_url"})
"""Watcher's two retired option keys (watcher #222): dropped on import, refused on the API."""

_SANDBOX = SandboxedEnvironment()


def _parses(source: str | None) -> str | None:
    """Refuse a template the sandbox cannot parse; keep it verbatim otherwise."""
    if source is None:
        return None
    try:
        _SANDBOX.parse(source)
    except TemplateSyntaxError as e:
        raise ValueError(f"not a valid Jinja template: {e.message} (line {e.lineno})") from e
    return source


JinjaTemplate = Annotated[str | None, AfterValidator(_parses)]


class ContentOptions(BaseModel):
    """Field toggles for one event's notification body, and optional Jinja overrides."""

    model_config = {"extra": "forbid"}

    include_diff_snippet: StrictBool = True
    """The first ``diff_snippet_lines`` lines of the change diff."""
    diff_snippet_lines: StrictInt = Field(default=25, ge=1, le=200)
    include_diff_full: StrictBool = False
    """Every change; supersedes the snippet when both are set."""
    include_temporal_context: StrictBool = False
    include_domain: StrictBool = False
    include_last_changed_at: StrictBool = False
    include_tags: StrictBool = False
    include_description: StrictBool = False
    title_template: JinjaTemplate = None
    """Replaces the default title. Not editable on the dashboard until #367's preview."""
    body_template: JinjaTemplate = None
    """Replaces the default body. Not editable on the dashboard until #367's preview."""


class ContentConfig(BaseModel):
    """Default options, with per-event overrides keyed by event name."""

    model_config = {"extra": "forbid"}

    default: ContentOptions = Field(default_factory=ContentOptions)
    overrides: dict[NotificationEvent, ContentOptions] = Field(default_factory=dict)


def validate_content_config(document: Any) -> tuple[bool, list[dict[str, str]]]:
    """``(ok, errors)`` in the stored-document sweep's shape (``audit_stored_documents``)."""
    try:
        ContentConfig.model_validate(document)
    except ValidationError as e:
        return False, [
            {"path": "/" + "/".join(str(part) for part in err["loc"]), "message": err["msg"]}
            for err in e.errors()
        ]
    return True, []


def normalize_content_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """``raw`` with every default filled in, so equal intent compares equal.

    ``None`` (all defaults) and ``{}`` normalize alike. Raises pydantic's
    ``ValidationError`` on a config the API would refuse.
    """
    return ContentConfig.model_validate(raw or {}).model_dump()
