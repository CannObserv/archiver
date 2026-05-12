"""Guard against drift between archiver_client.__version__ and pyproject.toml.

Task 13 originally bumped pyproject.toml from 1.3.0 to 2.0.0 but missed
__init__.py's __version__ literal; the discrepancy shipped to the worktree
and was only caught during code review of #15.  This test makes future
version bumps fail loudly if either side is touched without the other.
"""

from __future__ import annotations

from importlib.metadata import version

import archiver_client


def test_version_matches_package_metadata():
    assert archiver_client.__version__ == version("archiver-client")
