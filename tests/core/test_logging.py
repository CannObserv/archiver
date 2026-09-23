"""Regression tests for structured JSON logging (archiver#115, #122, #123)."""

import json
import logging
import logging.config
from pathlib import Path

from src.core.logging import (
    ColorMessageFilter,
    CredentialRedactingFilter,
    build_json_formatter,
    configure_logging,
    get_logger,
)

LOG_CONFIG_PATH = Path(__file__).resolve().parents[2] / "src" / "core" / "log_config.json"

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


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
    # dictConfig mutates the root logger and attaches filters to the uvicorn
    # loggers; restore both so the config load does not leak a stdout handler or
    # a color-message filter into the rest of the suite (#122, #123).
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved_filters = {name: logging.getLogger(name).filters[:] for name in UVICORN_LOGGERS}
    try:
        logging.config.dictConfig(config)
    finally:
        root.handlers, root.level = saved_handlers, saved_level
        for name in UVICORN_LOGGERS:
            logging.getLogger(name).filters = saved_filters[name]


def test_log_config_routes_uvicorn_access_to_json(capsys):
    """A uvicorn.access record renders as JSON with the full field set (#122)."""
    config = json.loads(LOG_CONFIG_PATH.read_text())
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved_filters = {name: logging.getLogger(name).filters[:] for name in UVICORN_LOGGERS}
    try:
        logging.config.dictConfig(config)
        logging.getLogger("uvicorn.access").info("GET /health 200")
    finally:
        root.handlers, root.level = saved_handlers, saved_level
        for name in UVICORN_LOGGERS:
            logging.getLogger(name).filters = saved_filters[name]

    record = json.loads(capsys.readouterr().out)
    assert record["message"] == "GET /health 200"
    assert record["level"] == "INFO"
    assert record["logger"] == "uvicorn.access"
    assert "timestamp" in record


def test_color_message_filter_strips_extra_from_record():
    """The filter removes `color_message` from the record itself, sink-independently (#123)."""
    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, __file__, 1, "Started server process [4066888]", None, None
    )
    record.color_message = "Started server process [\x1b[36m%d\x1b[0m]"

    assert ColorMessageFilter().filter(record) is True
    assert not hasattr(record, "color_message")

    parsed = json.loads(build_json_formatter().format(record))
    assert "color_message" not in parsed
    assert parsed["message"] == "Started server process [4066888]"


def test_color_message_filter_tolerates_absent_extra():
    """A record without `color_message` passes through unharmed (#123)."""
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "GET / 200", None, None)
    assert ColorMessageFilter().filter(record) is True


def test_log_config_wires_strip_color_message_on_uvicorn_loggers():
    """Each uvicorn logger lists the filter, pinning placement not just effect (#123)."""
    config = json.loads(LOG_CONFIG_PATH.read_text())
    assert config["filters"]["strip_color_message"]["()"] == "src.core.logging.ColorMessageFilter"
    for name in UVICORN_LOGGERS:
        assert "strip_color_message" in config["loggers"][name]["filters"]


def test_credential_filter_redacts_a_url_in_an_extra():
    """The net behind the call sites: no credentialed URL reaches a sink (#251).

    Call-site redaction (`bus_client.redact_url`) is the fix; this is the thing
    that holds when a *new* site forgets, or when a library we do not own logs a
    DSN of its own. Asserts the whole line, not just the password's absence: a
    filter that blanked the field would satisfy a bare `not in` while destroying
    the one datum that says which broker the line is about.
    """
    record = logging.LogRecord(
        "src.api.main", logging.INFO, __file__, 1, "Outbox publisher started", None, None
    )
    record.redis_url = "redis://archiver:hunter2@broker:6379/0"

    assert CredentialRedactingFilter().filter(record) is True
    assert record.redis_url == "redis://archiver:***@broker:6379/0"


def test_credential_filter_redacts_a_url_in_the_message_and_its_args():
    """Credentials arrive interpolated as often as they arrive as extras (#251)."""
    record = logging.LogRecord(
        "src.core.database",
        logging.ERROR,
        __file__,
        1,
        "cannot connect to %s",
        ("postgresql+asyncpg://archiver:hunter2@localhost:5432/archiver",),
        None,
    )

    assert CredentialRedactingFilter().filter(record) is True
    assert record.getMessage() == (
        "cannot connect to postgresql+asyncpg://archiver:***@localhost:5432/archiver"
    )
    assert "hunter2" not in record.getMessage()


def test_credential_filter_leaves_a_credential_free_url_alone():
    """Most URLs carry no secret; rewriting them would corrupt the line (#251)."""
    record = logging.LogRecord(
        "src.core.changes.bus_client", logging.INFO, __file__, 1, "Bus broker reachable", None, None
    )
    record.redis_url = "redis://localhost:6379/15"

    assert CredentialRedactingFilter().filter(record) is True
    assert record.redis_url == "redis://localhost:6379/15"


def test_configure_logging_wires_the_credential_filter(capsys):
    """Placement, not just effect: the app's own handler carries the net (#251)."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging()
        get_logger("src.some.module").info(
            "started", extra={"redis_url": "redis://archiver:hunter2@broker:6379/0"}
        )
    finally:
        root.handlers, root.level = saved_handlers, saved_level

    out = capsys.readouterr().out
    assert "hunter2" not in out
    assert json.loads(out)["redis_url"] == "redis://archiver:***@broker:6379/0"


def test_log_config_wires_the_credential_filter_on_the_json_handler():
    """On the *handler*, so every logger routed there is covered (#251).

    The color-message filter sits on the three uvicorn loggers because that is
    where its extra originates. This one cannot: the site that leaks next is by
    definition not one we listed, so it goes where every record passes.
    """
    config = json.loads(LOG_CONFIG_PATH.read_text())
    assert (
        config["filters"]["redact_credentials"]["()"]
        == "src.core.logging.CredentialRedactingFilter"
    )
    assert "redact_credentials" in config["handlers"]["json_stdout"]["filters"]


def test_log_config_redacts_a_credential_on_a_uvicorn_record(capsys):
    """The production path end to end: uvicorn's own loggers are covered too (#251).

    `uvicorn.*` set `propagate: false` and carry their own handler entry, so the
    filter `configure_logging()` adds to the app's root handler never sees their
    records. Both wirings are load-bearing; this is the half the app's own tests
    cannot reach.
    """
    config = json.loads(LOG_CONFIG_PATH.read_text())
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved_filters = {name: logging.getLogger(name).filters[:] for name in UVICORN_LOGGERS}
    try:
        logging.config.dictConfig(config)
        logging.getLogger("uvicorn.error").info(
            "connecting to redis://archiver:hunter2@broker:6379/0"
        )
    finally:
        root.handlers, root.level = saved_handlers, saved_level
        for name in UVICORN_LOGGERS:
            logging.getLogger(name).filters = saved_filters[name]

    out = capsys.readouterr().out
    assert "hunter2" not in out
    assert json.loads(out)["message"] == "connecting to redis://archiver:***@broker:6379/0"
