"""One reader for the ``.skills/`` list files ``doc-check.sh`` consumes.

Upstream parses ``.skills/doc-sensitive-paths`` and ``.skills/doc-sections``
through a single ``read_list_file`` so a grammar fix lands on both
(gregoryfoster/skills#261). The tests pinning archiver's copies of those files
share this reader for the same reason: two parsers could drift into disagreeing
with each other and with the script.
"""

import subprocess
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def read_list_file(path: Path) -> tuple[str, ...]:
    """Entries of a ``.skills/`` list file, parsed the way ``doc-check.sh`` parses it.

    Blank lines and lines whose first non-space character is ``#`` are dropped and
    the rest stripped; a ``#`` later in a line is content. An absent file yields
    ``()`` so a caller's parametrized tests still collect and one readable
    assertion fails instead.
    """
    if not path.is_file():
        return ()
    lines = path.read_text().splitlines()
    return tuple(
        stripped for line in lines if (stripped := line.strip()) and not stripped.startswith("#")
    )


@cache
def tracked_files() -> tuple[str, ...]:
    """Every tracked path, as ``doc-check.sh`` sees them."""
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return tuple(result.stdout.splitlines())
