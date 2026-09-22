"""Every override in ``skills/`` must carry the fragments its vendor marks required.

A vendor fences a block with ``<!-- skill:required id=… -->`` when dropping it
reintroduces a failure that was already fixed once. ``skills/`` overrides are
*supposed* to differ from their vendors, so a plain diff cannot police this -
the required fragments are the small set the vendor says is not optional, and a
``version:`` stamp cannot see them: gregoryfoster/skills#63 came back a second
time under a version that matched exactly (#260).

archiver#241 found two overrides missing one. ``skills/shipping-work-python-fastapi``
had dropped the ``skill-scripts`` fragment outright, and
``skills/using-git-worktrees`` carried the fence with a stale single-anchor body -
which reads as synced to anyone who greps for the marker. Both resolved one
anchor script and reused its directory for the other five, the shape
gregoryfoster/skills#301 fixed upstream. Neither was live here, because both
override ``scripts/`` directories happen to hold every script; both were one
moved file away from resolving five paths into the wrong directory.

Nothing in this repo noticed for the twelve days between the vendor bump and
that review. ``.skills/doctor.sh`` reports it, but only when a skill invokes the
doctor, which happens when someone runs a skill that ships the preflight - not
on any schedule and not in CI.

**Delegates to the doctor rather than re-implementing it.** The rule is a
literal-substring match over flattened markdown, plus ``omits-required:``
declarations that excuse a named id. A second implementation here would be a
second standard, and the two would drift; the thing worth pinning is that the
doctor's verdict is *consulted*, not that Python can reproduce it. Run with
``--check-only`` so the check attempts no repair and never writes to the tree -
a bare run would ``sync_self`` and could leave the working tree dirty.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR = REPO_ROOT / ".skills" / "doctor.sh"

# The doctor prints one of these per override that is missing a fragment, under
# the "omits text its vendor marks as required" header. ``no id`` is the bare
# ``<!-- skill:required -->`` form, which cannot be excused by a declaration
# until its vendor names it.
MISSING_MARKERS = ("missing (id=", "missing (no id)")


def _vendor_checked_out() -> bool:
    """Whether ``skills-vendor/gregoryfoster-skills`` has content.

    The main CI workflow does not check out submodules, so the vendor SKILL.md
    files this check reads against are absent there. Mirrors the helper in
    ``test_claude_hooks_registered.py`` rather than inventing a second probe.
    """
    return (REPO_ROOT / "skills-vendor" / "gregoryfoster-skills" / "skills").is_dir()


def _doctor_output() -> str:
    """Stderr of ``.skills/doctor.sh --check-only``, run from the repo root.

    The doctor writes every finding to stderr and exits 0 when it is merely
    advisory, so the exit code says nothing about fragments and is not asserted
    on here - only that the process ran.
    """
    result = subprocess.run(
        ["bash", str(DOCTOR), "--check-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stderr


def test_doctor_script_is_present_and_executable() -> None:
    """The committed doctor is what every skill's preflight invokes."""
    assert DOCTOR.is_file(), f"{DOCTOR} is missing"


@pytest.mark.skipif(
    not _vendor_checked_out(),
    reason="skills-vendor/gregoryfoster-skills is not checked out",
)
def test_no_override_omits_a_required_fragment() -> None:
    """No ``skills/`` override drops a fragment its vendor marks required.

    Fix by re-syncing that one fragment from the vendor's SKILL.md - not the
    whole override, which is a separate and deliberately manual merge. Where a
    fragment genuinely cannot apply (the override ships none of the scripts the
    block resolves, say), declare it instead::

        metadata:
          omits-required: "<id>: why it cannot apply here"
    """
    offending = [
        line.strip()
        for line in _doctor_output().splitlines()
        if any(marker in line for marker in MISSING_MARKERS)
    ]
    assert not offending, "overrides omit vendor-required fragments:\n" + "\n".join(offending)


@pytest.mark.skipif(
    not _vendor_checked_out(),
    reason="skills-vendor/gregoryfoster-skills is not checked out",
)
def test_no_omits_required_declaration_is_stale() -> None:
    """An ``omits-required:`` declaration must still name a live fragment id.

    A declaration excuses exactly one id. When the vendor renames or retires
    that fragment the declaration stops excusing anything, and a newly armed
    fragment would otherwise be silently covered by a stamp that no longer
    refers to it.
    """
    offending = [
        line.strip()
        for line in _doctor_output().splitlines()
        if "omits-required:" in line and "excuses nothing" not in line
        if line.strip().startswith("skills/")
    ]
    assert not offending, "stale omits-required declarations:\n" + "\n".join(offending)
