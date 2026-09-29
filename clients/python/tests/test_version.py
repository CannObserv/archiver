"""Guard against drift between archiver_client.__version__ and pyproject.toml.

Task 13 originally bumped pyproject.toml from 1.3.0 to 2.0.0 but missed
__init__.py's __version__ literal; the discrepancy shipped to the worktree
and was only caught during code review of #15.  This test makes future
version bumps fail loudly if either side is touched without the other.

Since archiver#248 ``__version__`` reads the installed distribution's metadata,
so there is no literal to keep in step; the literal had sat at 5.0.0 through
seven releases while this test failed in a suite CI never ran. It now guards
against a hand-maintained literal coming back.
"""

from __future__ import annotations

from importlib.metadata import version

import archiver_client


def test_version_matches_package_metadata():
    assert archiver_client.__version__ == version("archiver-client")
