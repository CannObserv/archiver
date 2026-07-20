"""Keep ``pyproject.toml`` version in lockstep with ``CHANGELOG.md``.

The service version drifted silently (#85): ``pyproject.toml`` said 3.2.0
while ``CHANGELOG.md`` (and hence ``/openapi.json``, which reads the installed
package version) had moved on to 4.2.2. The CHANGELOG is the single source of
truth for the service version: the newest ``## vX.Y.Z`` heading names the
current release. This checker parses that heading and compares it against
``[project].version`` in ``pyproject.toml``; any mismatch is a red build.

Fix a failure by bumping ``[project].version`` in ``pyproject.toml`` to the
newest CHANGELOG heading (then ``uv sync`` to refresh the lockfile).

Usage::

    python scripts/check_version_lockstep.py

Exit: 0 in lockstep · 1 mismatch (or unparseable CHANGELOG/pyproject).
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# A release heading is exactly "## vX.Y.Z" at line start, optionally followed
# by trailing text such as the release date: "## v4.2.2 (2026-07-19)".
_HEADING_RE = re.compile(r"^## v(\d+\.\d+\.\d+)(?:\s|$)", re.MULTILINE)


def newest_changelog_version(text: str) -> str | None:
    """Return the version of the first ``## vX.Y.Z`` heading, or None.

    CHANGELOG.md is newest-first, so the first matching heading is the
    current release.
    """
    match = _HEADING_RE.search(text)
    return match.group(1) if match else None


def pyproject_version(path: Path) -> str:
    """Return ``[project].version`` from the given pyproject.toml."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def check(repo_root: Path) -> int:
    """Compare pyproject and CHANGELOG versions; return a process exit code."""
    pyproject_path = repo_root / "pyproject.toml"
    changelog_path = repo_root / "CHANGELOG.md"

    try:
        project_version = pyproject_version(pyproject_path)
    except (OSError, KeyError, tomllib.TOMLDecodeError) as e:
        print(
            f"version lockstep FAIL: cannot read [project].version from {pyproject_path}: {e!r}",
            file=sys.stderr,
        )
        return 1

    try:
        changelog_version = newest_changelog_version(changelog_path.read_text())
    except OSError as e:
        print(
            f"version lockstep FAIL: cannot read {changelog_path}: {e!r}",
            file=sys.stderr,
        )
        return 1

    if changelog_version is None:
        print(
            f"version lockstep FAIL: no '## vX.Y.Z' release heading found in {changelog_path}",
            file=sys.stderr,
        )
        return 1

    if project_version != changelog_version:
        print(
            "version lockstep FAIL: pyproject.toml [project].version is "
            f"{project_version} but the newest CHANGELOG.md heading is v{changelog_version}.\n"
            f"Fix: set version = \"{changelog_version}\" in pyproject.toml, then run 'uv sync'.",
            file=sys.stderr,
        )
        return 1

    print(f"version lockstep OK: {project_version}")
    return 0


def main() -> int:
    """CLI entry point."""
    return check(REPO_ROOT)


if __name__ == "__main__":
    sys.exit(main())
