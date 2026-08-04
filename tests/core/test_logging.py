"""Regression tests for structured JSON logging (archiver#115, #122)."""

import json
import logging
import logging.config
from pathlib import Path

from src.core.logging import build_json_formatter, configure_logging, get_logger

LOG_CONFIG_PATH = Path(__file__).resolve().parents[2] / "src" / "core" / "log_config.json"


def test_log_record_includes_structured_fields(capsys):
    """A JSON record carries message, level, logger name, and timestamp (#115)."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging()
        get_logger("src.some.module").warning("hello %s", "world")
    finally:
        root.handlers, root.level = saved_handlers, saved_level

    record = json.loads(capsys.readouterr().out)
    assert record["message"] == "hello world"
    assert record["level"] == "WARNING"
    assert record["logger"] == "src.some.module"
    assert "timestamp" in record


def test_build_json_formatter_emits_structured_fields():
    """The factory is the single source of truth for the field contract (#122)."""
    formatter = build_json_formatter()
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "GET / 200", None, None)
    parsed = json.loads(formatter.format(record))
    assert parsed["message"] == "GET / 200"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "uvicorn.access"
    assert "timestamp" in parsed


def test_log_config_file_single_sources_the_formatter():
    """The uvicorn --log-config file loads under dictConfig and reuses the factory (#122)."""
    config = json.loads(LOG_CONFIG_PATH.read_text())
    assert config["formatters"]["json"]["()"] == "src.core.logging.build_json_formatter"
    # dictConfig mutates the root logger; restore it so the config load does not
    # leak a stdout handler into the rest of the suite.
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        logging.config.dictConfig(config)
    finally:
        root.handlers, root.level = saved_handlers, saved_level


def test_log_config_routes_uvicorn_access_to_json(capsys):
    """A uvicorn.access record renders as JSON with the full field set (#122)."""
    config = json.loads(LOG_CONFIG_PATH.read_text())
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        logging.config.dictConfig(config)
        logging.getLogger("uvicorn.access").info("GET /health 200")
    finally:
        root.handlers, root.level = saved_handlers, saved_level

    record = json.loads(capsys.readouterr().out)
    assert record["message"] == "GET /health 200"
    assert record["level"] == "INFO"
    assert record["logger"] == "uvicorn.access"
    assert "timestamp" in record
