"""Structured JSON logging utilities."""

import logging
import sys

from pythonjsonlogger.json import JsonFormatter


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger with JSON formatting. Call once at entry points.

    The fmt string is required: without it python-json-logger derives keys from
    the ``%(field)s`` placeholders, which default to ``"%(message)s"`` alone —
    so records serialize as just ``{"message": ...}`` with no level, logger
    name, or timestamp (archiver#115). ``timestamp=True`` emits ISO-8601 UTC.
    The key set (timestamp, level, logger, message) matches structlog defaults.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            "%(levelname)s %(name)s %(message)s",
            timestamp=True,
            rename_fields={"levelname": "level", "name": "logger"},
        )
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Use in modules as: logger = get_logger(__name__)"""
    return logging.getLogger(name)
