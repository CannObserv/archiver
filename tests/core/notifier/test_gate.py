"""The Notifier gate (archiver#368): a URL is configuration, the flag is permission.

Watcher's #277/#278 pattern in Archiver's terms. ``deploy/archiver.service``
alone sets ``ARCHIVER_NOTIFIER_ENABLED=1`` and the URL, and hands over the key
as the ``notifier-key`` credential. Every other process holds neither the flag
nor the URL and is dormant. Each half-configuration refuses startup; none is a
quiet mode. The production key is a credential only: a key from the
environment (the dev path) aimed at production's port is refused.
"""

from pathlib import Path

import pytest

from src.core.notifier import gate
from src.core.notifier.gate import (
    API_KEY_ENV,
    BASE_URL_ENV,
    CREDENTIAL_FILE,
    CREDENTIAL_NAME,
    ENABLED_ENV,
    NotifierConfig,
    NotifierCredentialMissing,
    NotifierMisconfigured,
    NotifierNotEnabled,
    NotifierRefused,
    notifier_enabled,
    resolve,
)

PROD_URL = "http://notifier:9000"
DEV_URL = "http://notifier:9001"
KEY = "nk_test-0123456789abcdef"


@pytest.fixture
def credentials(tmp_path: Path):
    """A ``$CREDENTIALS_DIRECTORY`` holding *content* as the notifier key."""

    def _write(content: str = f"{KEY}\n") -> dict[str, str]:
        (tmp_path / CREDENTIAL_NAME).write_text(content)
        return {"CREDENTIALS_DIRECTORY": str(tmp_path)}

    return _write


def test_the_names_the_unit_and_the_docs_use() -> None:
    assert BASE_URL_ENV == "ARCHIVER_NOTIFIER_BASE_URL"
    assert API_KEY_ENV == "ARCHIVER_NOTIFIER_API_KEY"
    assert ENABLED_ENV == "ARCHIVER_NOTIFIER_ENABLED"
    assert CREDENTIAL_NAME == "notifier-key"
    assert CREDENTIAL_FILE == "/etc/archiver/notifier.key"


@pytest.mark.parametrize("value", ["1"])
def test_only_the_exact_string_one_opts_in(value: str) -> None:
    assert notifier_enabled({ENABLED_ENV: value})


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "on", "01", " 1", "1 ", "TRUE"])
def test_anything_else_does_not(value: str) -> None:
    assert not notifier_enabled({ENABLED_ENV: value})


def test_nothing_set_is_dormant() -> None:
    assert resolve({}) is None


def test_a_key_alone_is_dormant(credentials) -> None:
    """A key names no Notifier, so nothing can be sent by accident."""
    assert resolve({API_KEY_ENV: KEY}) is None
    assert resolve(credentials()) is None


def test_a_url_without_the_flag_refuses() -> None:
    with pytest.raises(NotifierNotEnabled, match=ENABLED_ENV):
        resolve({BASE_URL_ENV: PROD_URL, API_KEY_ENV: KEY})


@pytest.mark.parametrize("flag", ["true", "yes", "0"])
def test_a_url_with_a_fuzzy_flag_refuses(flag: str) -> None:
    with pytest.raises(NotifierNotEnabled):
        resolve({BASE_URL_ENV: DEV_URL, ENABLED_ENV: flag, API_KEY_ENV: KEY})


def test_the_flag_without_a_url_refuses(credentials) -> None:
    with pytest.raises(NotifierCredentialMissing, match=BASE_URL_ENV):
        resolve({ENABLED_ENV: "1", **credentials()})


def test_the_flag_and_url_without_a_key_refuse() -> None:
    """The unit without its credential file, as systemd cannot see it: the message
    names the file the operator has to go and look at."""
    with pytest.raises(NotifierCredentialMissing, match=CREDENTIAL_FILE):
        resolve({BASE_URL_ENV: PROD_URL, ENABLED_ENV: "1"})


@pytest.mark.parametrize("content", ["", "\n", "   \n"])
def test_an_empty_credential_is_no_key(credentials, content: str) -> None:
    with pytest.raises(NotifierCredentialMissing):
        resolve({BASE_URL_ENV: PROD_URL, ENABLED_ENV: "1", **credentials(content)})


def test_the_unit_shape_resolves_from_the_credential(credentials) -> None:
    config = resolve({BASE_URL_ENV: PROD_URL, ENABLED_ENV: "1", **credentials()})
    assert config == NotifierConfig(base_url=PROD_URL, api_key=KEY, key_source="credential")


def test_the_dev_shape_resolves_from_the_environment() -> None:
    config = resolve({BASE_URL_ENV: DEV_URL, ENABLED_ENV: "1", API_KEY_ENV: KEY})
    assert config == NotifierConfig(base_url=DEV_URL, api_key=KEY, key_source="environment")


@pytest.mark.parametrize(
    "url",
    [
        PROD_URL,
        "http://notifier:9000/",
        "http://100.64.0.7:09000",
        "HTTPS://notifier.taild0fb76.ts.net:9000/api",
    ],
)
def test_an_environment_key_aimed_at_production_refuses(url: str) -> None:
    """The production key is a credential, never an environment variable: a pasted
    key in a hand-run server's shell cannot reach the production tenant."""
    with pytest.raises(NotifierMisconfigured, match="9000"):
        resolve({BASE_URL_ENV: url, ENABLED_ENV: "1", API_KEY_ENV: KEY})


def test_a_credential_and_an_environment_key_together_refuse(credentials) -> None:
    """One key source per process. An environment key in the unit means one was put
    in /etc/archiver/.env, which three other units load whole."""
    with pytest.raises(NotifierMisconfigured, match=API_KEY_ENV):
        resolve({BASE_URL_ENV: PROD_URL, ENABLED_ENV: "1", API_KEY_ENV: KEY, **credentials()})


@pytest.mark.parametrize(
    "url", ["notifier:9001", "ftp://notifier:9001", "http://", "http://notifier:abc", "x y"]
)
def test_an_unusable_url_refuses(url: str) -> None:
    with pytest.raises(NotifierMisconfigured):
        resolve({BASE_URL_ENV: url, ENABLED_ENV: "1", API_KEY_ENV: KEY})


@pytest.mark.parametrize("bad", ["nk two tokens", "nk_é", "nk_\x00"])
def test_a_key_that_is_not_one_printable_token_refuses_without_quoting_it(bad: str) -> None:
    """A bad paste is refused before httpx sees it, since a header error can quote it."""
    with pytest.raises(NotifierMisconfigured) as excinfo:
        resolve({BASE_URL_ENV: DEV_URL, ENABLED_ENV: "1", API_KEY_ENV: bad})
    assert bad not in str(excinfo.value)


def _refusals(credentials) -> list[dict[str, str]]:
    cred = credentials()
    return [
        {BASE_URL_ENV: PROD_URL, API_KEY_ENV: KEY},
        {ENABLED_ENV: "1", API_KEY_ENV: KEY},
        {BASE_URL_ENV: PROD_URL, ENABLED_ENV: "1", API_KEY_ENV: KEY},
        {BASE_URL_ENV: PROD_URL, ENABLED_ENV: "1", API_KEY_ENV: KEY, **cred},
        {BASE_URL_ENV: "ftp://x", ENABLED_ENV: "1", API_KEY_ENV: KEY},
    ]


def test_no_refusal_names_the_key(credentials) -> None:
    for environ in _refusals(credentials):
        with pytest.raises(NotifierRefused) as excinfo:
            resolve(environ)
        assert KEY not in str(excinfo.value), environ


def test_every_refusal_is_a_runtime_error() -> None:
    for exc in (NotifierNotEnabled, NotifierCredentialMissing, NotifierMisconfigured):
        assert issubclass(exc, NotifierRefused)
    assert issubclass(NotifierRefused, RuntimeError)


def test_the_config_never_shows_its_key() -> None:
    config = NotifierConfig(base_url=DEV_URL, api_key=KEY, key_source="environment")
    assert KEY not in repr(config)
    assert KEY not in str(config)


def test_the_gate_imports_no_sdk() -> None:
    """The gate is judged before any client exists, and the dev-server parity test
    imports it: it must not need the SDK."""
    assert "notifier_client" not in Path(gate.__file__).read_text()
