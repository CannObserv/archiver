"""Cross-implementation parity for the production-database guard.

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
