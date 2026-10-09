"""The installed-unit parity helper compares with the live release (archiver#330 D12).

Before #330 each parity test compared ``/etc/systemd/system/<unit>`` with the
repo copy in the working tree. Once ``scripts/deploy.sh`` installs units from
the release it switches to, that comparison turns red on every merged unit
edit not yet deployed - drift the deploy is about to fix, not drift. What a
host should hold is the live release's copy; a difference from *that* is a
hand edit.
"""

import pytest

from tests.deploy.live_release import installed_and_expected


def test_a_host_without_the_unit_skips(tmp_path):
    with pytest.raises(pytest.skip.Exception, match="not installed"):
        installed_and_expected("archiver.service", unit_dir=tmp_path, live=tmp_path / "live")


def test_a_host_not_yet_cut_over_skips(tmp_path):
    (tmp_path / "archiver.service").write_text("checkout unit\n")
    with pytest.raises(pytest.skip.Exception, match="deploy.sh"):
        installed_and_expected("archiver.service", unit_dir=tmp_path, live=tmp_path / "live")


def test_the_expected_copy_is_the_live_releases_not_the_working_trees(tmp_path):
    units = tmp_path / "units"
    release = tmp_path / "releases" / "0123456789ab"
    (release / "deploy").mkdir(parents=True)
    units.mkdir()
    (units / "archiver.service").write_text("installed\n")
    (release / "deploy" / "archiver.service").write_text("released\n")
    (tmp_path / "live").symlink_to(release)

    got = installed_and_expected("archiver.service", unit_dir=units, live=tmp_path / "live")

    assert got == ("installed\n", "released\n")


def test_an_unreadable_unit_is_an_error_not_a_skip(tmp_path):
    """A drift check that cannot fail is worse than none (#98)."""
    unit = tmp_path / "archiver.service"
    unit.write_text("x")
    unit.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            installed_and_expected("archiver.service", unit_dir=tmp_path, live=tmp_path / "live")
    finally:
        unit.chmod(0o644)
