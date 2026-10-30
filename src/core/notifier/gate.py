"""The Notifier gate (archiver#368): a URL is configuration, not permission.

Watcher's #277/#278 pattern, in Archiver's terms. Watcher's notifier client
used to read its URL and key straight from an env file every agent shell
sourced, so a suite, a hand-run server or a REPL dispatched to the production
tenant, successfully and silently: notifier's audit found ~1289 fixture
notifications delivered on that key. A notification reaches real people on
real channels and cannot be recalled.

So three things must line up before a process may build a client:

- ``ARCHIVER_NOTIFIER_ENABLED`` is exactly ``"1"``. Only
  ``deploy/archiver.service`` and ``scripts/dev_server.sh`` (beside a dev pair)
  set it. Never an env file, the rule ``ARCHIVER_ALLOW_PRODUCTION_DB`` follows.
- ``ARCHIVER_NOTIFIER_BASE_URL`` names the Notifier. The unit's own
  ``Environment=`` line, so no other unit or shell holds it.
- A key. In the unit it is the ``notifier-key`` systemd credential, read from
  ``$CREDENTIALS_DIRECTORY``: in no process environment, never logged. The dev
  server passes ``ARCHIVER_NOTIFIER_API_KEY`` instead.

Neither flag nor URL is dormant and silent: nothing is named, so nothing can be
sent. **Every half-configuration refuses startup**, since a service that came up
un-notifying would fail one dispatch at a time behind a green status.

**The production key is a credential only.** A key from the environment aimed
at production's port (:data:`PRODUCTION_PORT`) is refused, so a key pasted into
a shell cannot reach the production tenant. ``scripts/dev_server.sh`` refuses
the same URLs with the same grammar (:data:`TARGET_PATTERN`), and
``tests/scripts/test_db_guard_parity.py`` feeds one corpus through both.

This module imports no SDK: the gate is judged before any client exists.
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

BASE_URL_ENV = "ARCHIVER_NOTIFIER_BASE_URL"
API_KEY_ENV = "ARCHIVER_NOTIFIER_API_KEY"
#: Unit-only opt-in gating every Notifier client this process can build.
ENABLED_ENV = "ARCHIVER_NOTIFIER_ENABLED"
#: The ``LoadCredential=`` name ``deploy/archiver.service`` gives the key.
CREDENTIAL_NAME = "notifier-key"
#: Where the unit loads it from. Named for the refusals: it is the file an
#: operator has to go and look at (docs/NOTIFICATIONS.md § The credential).
CREDENTIAL_FILE = "/etc/archiver/notifier.key"
#: Production Notifier's port; :9001 is its development deployment.
PRODUCTION_PORT = 9000

#: ``scheme://host[:port][/?#...]``, mirrored character for character by
#: ``scripts/dev_server.sh``. Deliberately not ``urlsplit``: bash cannot import
#: it, and the two must agree on every URL, so both use one small grammar.
#: Userinfo, whitespace and non-ASCII fall outside it and are refused: the tail
#: is printable ASCII only, since bash's ``.`` would match a newline Python's won't.
TARGET_PATTERN = re.compile(
    r"([A-Za-z]+)://(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9._~%-]+)(:([0-9]*))?([/?#][!-~]*)?"
)
_DEFAULT_PORTS = {"http": 80, "https": 443}
#: One token of printable ASCII: what Notifier mints. Anything else is a bad
#: paste, refused before httpx sees it, since a header error can quote it.
_KEY = re.compile(r"[\x21-\x7e]+")


class NotifierRefused(RuntimeError):
    """This process's Notifier configuration is one the lifespan refuses to start with."""


class NotifierNotEnabled(NotifierRefused):
    """A Notifier URL held without the opt-in."""


class NotifierCredentialMissing(NotifierRefused):
    """The opt-in held without a URL or without a key."""


class NotifierMisconfigured(NotifierRefused):
    """A URL or key that cannot be used as given."""


@dataclass(frozen=True, slots=True)
class NotifierConfig:
    """What a client is built from. The key never reaches ``repr``."""

    base_url: str
    api_key: str = field(repr=False)
    key_source: Literal["credential", "environment"]


def notifier_enabled(environ: Mapping[str, str]) -> bool:
    """True only for the exact string ``"1"``: a fuzzy value must not reopen the gate."""
    return environ.get(ENABLED_ENV) == "1"


def target_port(url: str) -> int | None:
    """The port *url* reaches, or ``None`` when it is not a usable http(s) URL.

    The scheme's default port when none is written. More than five digits is
    refused rather than parsed, as bash arithmetic would overflow on it.
    """
    match = TARGET_PATTERN.fullmatch(url)
    if match is None:
        return None
    scheme, _host, _, port, _ = match.groups()
    default = _DEFAULT_PORTS.get(scheme.lower())
    if default is None:
        return None
    if not port:
        return default
    if len(port) > 5 or not 1 <= int(port) <= 65535:
        return None
    return int(port)


def is_allowed_dev_target(url: str) -> bool:
    """True when a key from the environment may be sent to *url*: usable, not :9000."""
    port = target_port(url)
    return port is not None and port != PRODUCTION_PORT


def resolve(environ: Mapping[str, str]) -> NotifierConfig | None:
    """This process's Notifier configuration, ``None`` when dormant, or a refusal.

    Takes ``environ`` explicitly so the caller decides what is judged, and a test
    can call it although ``tests/conftest.py`` clears the real variables.
    """
    url = environ.get(BASE_URL_ENV, "")
    enabled = notifier_enabled(environ)
    if not url and not enabled:
        return None
    if not enabled:
        raise NotifierNotEnabled(
            f"refusing to start: {BASE_URL_ENV} is set but {ENABLED_ENV} is not 1, so "
            "this process holds a Notifier address it is not authorised to use.\n"
            f"  Only deploy/archiver.service notifies production; it sets {ENABLED_ENV}=1. "
            "If this IS the service, that line is missing from the installed unit.\n"
            "  For a dev server use: bash scripts/dev_server.sh (it maps "
            "ARCHIVER_DEV_NOTIFIER_BASE_URL and ARCHIVER_DEV_NOTIFIER_API_KEY).\n"
            f"  For anything else, unset {BASE_URL_ENV}."
        )
    if not url:
        raise NotifierCredentialMissing(
            f"refusing to start: {ENABLED_ENV} is 1 but {BASE_URL_ENV} is unset, so this "
            "process is opted into a Notifier it cannot reach.\n"
            f"  deploy/archiver.service sets both as Environment= lines. For anything "
            f"else, unset {ENABLED_ENV}."
        )
    port = target_port(url)
    if port is None:
        raise NotifierMisconfigured(
            f"refusing to start: {BASE_URL_ENV} is not an http(s)://host[:port] URL"
        )
    credential = _read_credential(environ.get("CREDENTIALS_DIRECTORY"))
    env_key = environ.get(API_KEY_ENV, "").strip()
    if credential and env_key:
        raise NotifierMisconfigured(
            f"refusing to start: both the {CREDENTIAL_NAME} credential and {API_KEY_ENV} "
            f"are set. The unit's key is the credential alone; remove {API_KEY_ENV} from "
            "wherever this process inherited it (never /etc/archiver/.env)."
        )
    if credential:
        return NotifierConfig(base_url=url, api_key=_checked(credential), key_source="credential")
    if not env_key:
        raise NotifierCredentialMissing(
            f"refusing to start: {ENABLED_ENV} is 1 but there is no key: no "
            f"{CREDENTIAL_NAME} credential and no {API_KEY_ENV}.\n"
            f"  The unit loads it from {CREDENTIAL_FILE} (LoadCredential=). Check that the "
            "file exists, is root:root 0600 and is not empty."
        )
    if port == PRODUCTION_PORT:
        raise NotifierMisconfigured(
            f"refusing to start: {API_KEY_ENV} is aimed at port {PRODUCTION_PORT}, "
            "production Notifier. Production's key is the unit's credential only, never "
            "an environment variable. A dev server uses port 9001 (the development "
            "deployment)."
        )
    return NotifierConfig(base_url=url, api_key=_checked(env_key), key_source="environment")


def _read_credential(directory: str | None) -> str:
    """The key credential, stripped; ``""`` outside a unit or when absent or unreadable."""
    if not directory:
        return ""
    try:
        return (Path(directory) / CREDENTIAL_NAME).read_text().strip()
    except (OSError, ValueError):
        return ""


def _checked(key: str) -> str:
    if not _KEY.fullmatch(key):
        raise NotifierMisconfigured(
            "refusing to start: the Notifier key is not one token of printable ASCII; "
            f"reinstall it ({CREDENTIAL_FILE} for the unit, docs/NOTIFICATIONS.md)"
        )
    return key


def resolve_from_process() -> NotifierConfig | None:
    """:func:`resolve` over ``os.environ``, read by name so the outbound-env audit sees them."""
    environ = {
        BASE_URL_ENV: os.environ.get(BASE_URL_ENV),
        API_KEY_ENV: os.environ.get(API_KEY_ENV),
        ENABLED_ENV: os.environ.get(ENABLED_ENV),
        "CREDENTIALS_DIRECTORY": os.environ.get("CREDENTIALS_DIRECTORY"),
    }
    return resolve({name: value for name, value in environ.items() if value is not None})
