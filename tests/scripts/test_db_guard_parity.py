"""Cross-implementation parity for the production-database guard, and the Notifier one.

The ``_test``/``_dev`` suffix rule is enforced twice, in two languages:

  - ``src/core/db_safety.py``  — application lifespan guard (``urlsplit``)
  - ``scripts/dev_server.sh``  — launch-path guard (bash parameter expansion)

Bash cannot import the Python, so the duplication is unavoidable. What is
avoidable is the two drifting apart silently — CR finding 10. This module
feeds one shared corpus through both and asserts they reach the same verdict,
so a change to either implementation that alters its judgement fails here.

The corpus deliberately includes the shapes that differ between a URL parser
and string munging: escaped slashes in passwords, query strings, missing
ports, and suffix near-misses.
"""

import subprocess
from pathlib import Path

import pytest

from src.core.db_safety import is_non_production_database
from src.core.notifier.gate import (
    API_KEY_ENV,
    BASE_URL_ENV,
    ENABLED_ENV,
    TARGET_PATTERN,
    NotifierRefused,
    is_allowed_dev_target,
    resolve,
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev_server.sh"

# (url, accepted) — accepted=True means "this is a disposable dev/test database".
CORPUS: list[tuple[str, bool]] = [
    # Plain accepts.
    ("postgresql+asyncpg://archiver:archiver@localhost:5432/archiver_test", True),
    ("postgresql+asyncpg://archiver:archiver@localhost:5432/archiver_dev", True),
    ("postgresql://u:p@host/archiver_test", True),
    # Driver prefix and host spelling are not a safety boundary — the name is.
    ("postgresql://archiver:archiver@127.0.0.1:5432/archiver_test", True),
    ("postgresql+psycopg://u:p@otherhost:5432/x_dev", True),
    # Plain rejects.
    ("postgresql+asyncpg://archiver:archiver@localhost:5432/archiver", False),
    ("postgresql://u:p@host/archiver", False),
    # Suffix near-misses — substring matching would wrongly accept these.
    ("postgresql://u:p@host/test_archiver", False),
    ("postgresql://u:p@host/archiver_testing", False),
    ("postgresql://u:p@host/devious", False),
    ("postgresql://u:p@host/dev", False),
    # Query string must not bleed into the name either way.
    ("postgresql://u:p@host:5432/archiver_test?sslmode=require", True),
    ("postgresql://u:p@host:5432/archiver?sslmode=require", False),
    # Escaped slash in the password must not be read as the path.
    ("postgresql://u:p%2Fw@host:5432/archiver", False),
    ("postgresql://u:p%2Fw@host:5432/archiver_test", True),
    # An '@' inside the query string, on a CREDENTIAL-LESS URL, must not be
    # mistaken for the credentials delimiter (archiver#99, found in watcher's
    # CR). The old bash db_name() stripped credentials before the query, so
    # `#*@` ate through the query's '@' and returned its tail 'b_test' as the
    # name — bash-accepting a URL that names the production database 'archiver'.
    ("postgresql://host:5432/archiver?options=endpoint%3Da@b_test", False),
    # …and the verdict must survive an '@' in the query for a legit test DB too.
    ("postgresql://host:5432/archiver_test?options=endpoint%3Da@b", True),
    # A bare non-URL has no scheme: fail closed. The old bash version returned
    # the string unchanged (no '://' to strip) and accepted it.
    ("archiver_test", False),
    # Unparseable — both must fail closed.
    ("not-a-url", False),
]


def _bash_accepts(url: str) -> bool:
    """True when scripts/dev_server.sh would serve this database."""
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            "PATH": "/usr/bin:/bin",
            "ARCHIVER_DEV_SERVER_DRY_RUN": "1",
            "ARCHIVER_DEV_SERVER_SKIP_ENV_FILES": "1",
            "TEST_DATABASE_URL": url,
        },
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


@pytest.fixture(scope="module")
def bash_verdicts() -> dict[str, bool]:
    """One bash invocation per corpus entry, shared by every test below.

    Each call spawns a subprocess, so evaluating the corpus per-test made
    subprocess spawning the dominant cost of this module and scaled
    multiplicatively with corpus size.
    """
    return {url: _bash_accepts(url) for url, _ in CORPUS}


@pytest.mark.parametrize(("url", "accepted"), CORPUS, ids=[c[0] for c in CORPUS])
def test_python_guard_matches_corpus(url: str, accepted: bool) -> None:
    assert is_non_production_database(url) is accepted


@pytest.mark.parametrize(("url", "accepted"), CORPUS, ids=[c[0] for c in CORPUS])
def test_bash_guard_matches_corpus(
    url: str, accepted: bool, bash_verdicts: dict[str, bool]
) -> None:
    assert bash_verdicts[url] is accepted


@pytest.mark.parametrize("url", [c[0] for c in CORPUS])
def test_both_implementations_agree(url: str, bash_verdicts: dict[str, bool]) -> None:
    """The parity assertion itself, independent of the expected column.

    If someone changes one implementation and updates CORPUS to match, the two
    tests above still pass. This one fails unless *both* moved together.
    """
    assert is_non_production_database(url) is bash_verdicts[url]


# --- The Notifier target guard (archiver#368) -------------------------------
#
# The same discipline for a second guard. src/core/notifier/gate.py refuses an
# environment key (the dev path) aimed at production Notifier's port, and
# scripts/dev_server.sh refuses a dev URL there. Both judge a URL with one small
# grammar (gate.TARGET_PATTERN, the script's NOTIFIER_TARGET_RE) rather than
# urlsplit, so they can agree on every URL; this corpus is where they must.
# accepted=True means "a dev key may be sent here".

NOTIFIER_CORPUS: list[tuple[str, bool]] = [
    # The dev deployment, and spellings of it.
    ("http://notifier:9001", True),
    ("http://notifier:9001/", True),
    ("http://100.64.0.7:9001/api/v1?x=1#f", True),
    ("http://[::1]:9001", True),
    ("http://127.0.0.1:09001", True),
    # A scheme's default port is not 9000.
    ("http://notifier", True),
    ("https://notifier.example", True),
    ("HTTPS://notifier.example", True),
    # Production, however written.
    ("http://notifier:9000", False),
    ("http://notifier:9000/", False),
    ("http://notifier:09000", False),
    ("HTTP://Notifier:9000", False),
    ("http://[::1]:9000", False),
    ("https://notifier.taild0fb76.ts.net:9000/api?x#y", False),
    # Unusable: fail closed, both.
    ("notifier:9001", False),
    ("ftp://notifier:9001", False),
    ("http://", False),
    ("http://:9001", False),
    ("http://notifier:abc", False),
    ("http://notifier:0", False),
    ("http://notifier:65536", False),
    ("http://notifier:000009001", False),  # past five digits: bash would overflow
    ("http://u@notifier:9001", False),  # userinfo
    ("http://u:9000@notifier:9001", False),
    ("http://notifier:9001:9000", False),
    ("http://[::1]x:9001", False),
    ("http://[::1:9001", False),
    ("http://notifier:9001/a b", False),  # whitespace
    ("http://notifier:9001/é", False),  # non-ASCII
    ("http://notifier:9001/\nx", False),  # bash's '.' matches a newline
]


def _bash_notifier_accepts(url: str) -> bool:
    """True when scripts/dev_server.sh would map this dev Notifier URL."""
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            "PATH": "/usr/bin:/bin",
            "ARCHIVER_DEV_SERVER_DRY_RUN": "1",
            "ARCHIVER_DEV_SERVER_SKIP_ENV_FILES": "1",
            "TEST_DATABASE_URL": "postgresql://u:p@host/archiver_test",
            "ARCHIVER_DEV_NOTIFIER_BASE_URL": url,
            "ARCHIVER_DEV_NOTIFIER_API_KEY": "nk_dev-parity",
        },
        text=True,
        capture_output=True,
    )
    mapped = f"NOTIFIER={url} (dev key)" in result.stdout.splitlines()
    assert mapped is (result.returncode == 0), (result.stdout, result.stderr)
    return mapped


def _gate_accepts(url: str) -> bool:
    """True when the Python gate starts with *url* and a key from the environment."""
    try:
        resolve({BASE_URL_ENV: url, ENABLED_ENV: "1", API_KEY_ENV: "nk_dev-parity"})
    except NotifierRefused:
        return False
    return True


@pytest.fixture(scope="module")
def bash_notifier_verdicts() -> dict[str, bool]:
    return {url: _bash_notifier_accepts(url) for url, _ in NOTIFIER_CORPUS}


_IDS = [repr(c[0]) for c in NOTIFIER_CORPUS]


@pytest.mark.parametrize(("url", "accepted"), NOTIFIER_CORPUS, ids=_IDS)
def test_notifier_python_guard_matches_corpus(url: str, accepted: bool) -> None:
    assert is_allowed_dev_target(url) is accepted
    assert _gate_accepts(url) is accepted


@pytest.mark.parametrize(("url", "accepted"), NOTIFIER_CORPUS, ids=_IDS)
def test_notifier_bash_guard_matches_corpus(
    url: str, accepted: bool, bash_notifier_verdicts: dict[str, bool]
) -> None:
    assert bash_notifier_verdicts[url] is accepted


@pytest.mark.parametrize("url", [c[0] for c in NOTIFIER_CORPUS], ids=_IDS)
def test_notifier_implementations_agree(url: str, bash_notifier_verdicts: dict[str, bool]) -> None:
    assert is_allowed_dev_target(url) is bash_notifier_verdicts[url]


def test_the_two_grammars_are_one_string() -> None:
    """The cheap half of parity: the pattern is copied, not paraphrased."""
    (line,) = [ln for ln in SCRIPT.read_text().splitlines() if ln.startswith("NOTIFIER_TARGET_RE=")]
    assert line == f"NOTIFIER_TARGET_RE='^{TARGET_PATTERN.pattern}$'"
