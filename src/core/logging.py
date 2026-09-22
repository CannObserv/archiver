"""Structured JSON logging utilities.

`build_json_formatter()` is the single source of truth for the JSON field
contract (`timestamp`, `level`, `logger`, `message`). It is referenced both by
`configure_logging()` (app root logger) and by the uvicorn `--log-config`
dictConfig file (`src/core/log_config.json`, via its ``"()"`` factory key), so
app records and uvicorn access/error lines share one format — see archiver#115
(field contract) and archiver#122 (uvicorn unification).
"""

import logging
import re
import sys

from pythonjsonlogger.json import JsonFormatter


def build_json_formatter() -> JsonFormatter:
    """Build the canonical JSON formatter.

    Emits ``timestamp`` (ISO-8601 UTC), ``level``, ``logger``, and ``message``.
    Without an explicit fmt string, python-json-logger derives keys from the
    ``%(field)s`` placeholders, which default to ``"%(message)s"`` alone —
    dropping level, logger name, and timestamp (archiver#115). This factory is
    the one place that string lives, so the app logger and the uvicorn
    log-config cannot drift (archiver#122).
    """
    return JsonFormatter(
        "%(levelname)s %(name)s %(message)s",
        timestamp=True,
        rename_fields={"levelname": "level", "name": "logger"},
    )


class ColorMessageFilter(logging.Filter):
    """Drop uvicorn's `color_message` extra before anything serializes it.

    uvicorn attaches an ANSI-coloured duplicate of each lifecycle message as
    ``extra={"color_message": ...}`` for its own colour-aware formatter. Under
    our JSON formatter that extra leaks into the payload with raw escapes, so
    strip it at the record source — once, before any handler reads the record —
    rather than in a single sink (archiver#123).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Strip the extra if present. Never drops a record."""
        record.__dict__.pop("color_message", None)
        return True


REDACTED = "***"
"""The single spelling of a removed secret.

``src.core.changes.bus_client.redact_url`` imports it rather than repeating it,
so a line redacted at the call site and one redacted by the filter below are
indistinguishable to whoever greps the journal.
"""

_CREDENTIAL_URL = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<user>[^/?#\s:@]*):(?P<password>[^/?#\s@]+)@"
)
"""Userinfo carrying a password, in any scheme.

Deliberately not a URL parser: the input is an arbitrary log line, which may
hold a URL mid-sentence, several of them, or one a parser would reject. The
password group requires at least one character so a bare ``user:@host`` - no
secret to hide - is left alone.
"""


def _scrub(value: str) -> str:
    """Replace every embedded password in ``value``; cheap on the common path."""
    if "://" not in value:
        return value
    return _CREDENTIAL_URL.sub(rf"\g<scheme>\g<user>:{REDACTED}@", value)


class CredentialRedactingFilter(logging.Filter):
    """Strip passwords out of URLs anywhere in a record (archiver#251).

    The fix for a leak is to redact at the call site, where the code knows the
    field is a URL (``bus_client.redact_url``). This is the net under that: it
    catches the site nobody remembered, and the library we do not own that logs
    a DSN of its own. archiver#251 was exactly the first case - the lifespan's
    "Outbox publisher started" line put the broker credential in journald at
    every service start, two lines away from a helper that redacts.

    Mutates the record rather than a formatted string, for the same reason
    ``ColorMessageFilter`` does: once, at the source, so every handler benefits
    instead of whichever sink remembered. Wired on the *handler* rather than on
    named loggers - the site that leaks next is by definition not one we listed.

    Never drops a record. A log line with a secret in it is still a log line
    worth having; silence would trade a disclosure for an outage nobody sees.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Scrub message, args and extras in place. Always returns True."""
        for key, value in record.__dict__.items():
            if isinstance(value, str):
                record.__dict__[key] = _scrub(value)
        if isinstance(record.args, tuple):
            record.args = tuple(_scrub(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                k: _scrub(v) if isinstance(v, str) else v for k, v in record.args.items()
            }
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger with JSON formatting. Call once at entry points."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(build_json_formatter())
    # On the handler, not the root logger: a logger's filters skip records that
    # propagate up from its children, which is every record the app emits.
    handler.addFilter(CredentialRedactingFilter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Use in modules as: logger = get_logger(__name__)"""
    return logging.getLogger(name)
