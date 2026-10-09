"""The build id is the release's ``REVISION`` (archiver#330 D8, status R10).

``scripts/deploy.sh`` writes ``REVISION`` last into each release, so the code
that runs reports itself - no ``ExecStartPre`` git stamp, no git in a release.
Until the units move to releases, the unit's ``BUILD_ID`` stamp is the
fallback, so ``/health`` does not go null between the two PRs.
"""

from src.core import build


def test_the_release_revision_is_the_build_id(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_ID", "abc1234-dirty")
    (tmp_path / "REVISION").write_text("0123456789ab\n")
    assert build.build_id(tmp_path) == "0123456789ab"


def test_without_a_revision_the_unit_stamp_is_the_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_ID", "abc1234-dirty")
    assert build.build_id(tmp_path) == "abc1234-dirty"


def test_outside_a_release_and_unstamped_it_is_none(tmp_path, monkeypatch):
    monkeypatch.delenv("BUILD_ID", raising=False)
    assert build.build_id(tmp_path) is None


def test_an_empty_revision_is_not_a_build(tmp_path, monkeypatch):
    monkeypatch.delenv("BUILD_ID", raising=False)
    (tmp_path / "REVISION").write_text("\n")
    assert build.build_id(tmp_path) is None


def test_the_default_root_is_the_tree_this_code_runs_from():
    assert (build.ROOT / "src" / "core" / "build.py").is_file()
