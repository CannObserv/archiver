"""Structured JSON logging utilities.

`build_json_formatter()` is the single source of truth for the JSON field
contract (`timestamp`, `level`, `logger`, `message`). It is referenced both by
`configure_logging()` (app root logger) and by the uvicorn `--log-config`
dictConfig file (`src/core/log_config.json`, via its ``"()"`` factory key), so
app records and uvicorn access/error lines share one format — see archiver#115
(field contract) and archiver#122 (uvicorn unification).
"""

import logging
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


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger with JSON formatting. Call once at entry points."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(build_json_formatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Use in modules as: logger = get_logger(__name__)"""
    return logging.getLogger(name)
