"""Every hook script in ``.claude/hooks/`` must be wired into ``.claude/settings.json``.

archiver#163: ``skills-submodule-update.sh`` sat in ``.claude/hooks/`` - tracked,
resolving, executable - for twelve days while nothing ran it, because its
``settings.json`` entry had been removed (archiver#131's cohort hold) and never
restored. Claude Code runs what ``settings.json`` names, so the half that was
missing was the half that would have run: an ``ls`` of ``.claude/hooks/`` shows a
hook that is right there and does nothing.

That is the *partial install* failure mode, and it is invisible from either side
alone. This module closes it by asserting the two halves agree - a script present
but unregistered fails here, which is the signal that was absent for twelve days.

Deliberately one-directional. A registered command naming no local script is
legitimate (``bash .skills/doctor.sh``, an inline shell guard), so only
script-present-but-unwired is an error. Deliberately name-based rather than
path-based: the registered command may address the script through
``${CLAUDE_PROJECT_DIR}``, a relative path, or a guarded ``[ -f … ] &&`` prefix,
and the parity that matters is *which* hook, not how it is spelled.
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"


def _registered_commands() -> list[str]:
    """Every ``command`` string in ``settings.json``, across all hook events."""
    settings = json.loads(SETTINGS.read_text())
    return [
        entry["command"]
        for matchers in settings.get("hooks", {}).values()
        for matcher in matchers
        for entry in matcher.get("hooks", [])
        if entry.get("type") == "command"
    ]


def test_settings_json_is_valid_json_with_hooks() -> None:
    assert SETTINGS.is_file(), f"{SETTINGS} is missing"
    assert _registered_commands(), "settings.json registers no hook commands"


def test_every_hook_script_is_registered() -> None:
    """A script in ``.claude/hooks/`` that nothing invokes is a partial install."""
    commands = _registered_commands()
    scripts = sorted(p.name for p in HOOKS_DIR.glob("*.sh"))
    assert scripts, f"no hook scripts found under {HOOKS_DIR}"

    unwired = [name for name in scripts if not any(name in cmd for cmd in commands)]
    assert not unwired, (
        f"hook scripts present but not registered in .claude/settings.json: {unwired}. "
        "A hook Claude Code never runs is indistinguishable from one that works "
        "(archiver#163) - either wire it up or delete the script."
    )


def test_skills_refresh_hook_is_wired() -> None:
    """The specific regression of archiver#163, named so a failure reads plainly."""
    assert any("skills-submodule-update.sh" in cmd for cmd in _registered_commands()), (
        "the skills auto-refresh hook is not registered; without it this repo's "
        "vendored skills freeze at whatever commit was last bumped by hand "
        "(archiver#163)"
    )


def test_socraticode_health_hook_is_wired() -> None:
    """archiver#184: the daily SocratiCode health check must actually be invoked.

    A declared-but-unindexed context artifact produces no error and no warning -
    ``codebase_context_search`` simply answers without it while ``codebase_status``
    stays green. The once-per-day health hook is the only thing that reports the
    gap, so an unwired one leaves the failure mode wide open.
    """
    assert any("socraticode-health.sh" in cmd for cmd in _registered_commands()), (
        "the SocratiCode daily health hook is not registered; without it a "
        "declared-but-unindexed context artifact goes unreported indefinitely "
        "(archiver#184)"
    )


# Both SocratiCode hooks must be symlinks into ``skills-vendor/`` rather than
# copies, for reasons that differ per hook - hence the rationale rides on the
# parameter rather than living in one shared docstring.
VENDORED_HOOKS = [
    pytest.param(
        "socraticode-health.sh",
        "it is silent when clean, so a frozen copy that has stopped detecting "
        "anything is indistinguishable from a healthy install "
        "(gregoryfoster/skills#179)",
        id="health",
    ),
    pytest.param(
        "socraticode-reminder.sh",
        "the prefetch query it prints must stay in step with the skill's own "
        "template, and it carries no per-project state - which is the argument "
        "for linking rather than copying (gregoryfoster/skills#186)",
        id="reminder",
    ),
]


def _submodule_checked_out() -> bool:
    """Whether ``skills-vendor/gregoryfoster-skills`` has content.

    CI checks out with ``actions/checkout@v5`` and no ``submodules:`` input, so
    the submodule directory is empty there and every vendor symlink dangles -
    the state ``.skills/doctor.sh`` exists to repair, and the reason
    ``skills-submodule-update.sh`` has dangled in every CI run to date without
    failing anything. Resolution is therefore only assertable where the content
    is present; the symlink *shape* is assertable everywhere, and it is the
    shape that carries the copy-vs-symlink guarantee.
    """
    return (REPO_ROOT / "skills-vendor" / "gregoryfoster-skills" / "skills").is_dir()


@pytest.mark.parametrize(("hook_name", "rationale"), VENDORED_HOOKS)
def test_socraticode_hook_is_a_symlink_into_the_vendor(hook_name: str, rationale: str) -> None:
    """A vendored hook tracks upstream on the normal submodule refresh; a copy
    freezes at the day it was installed."""
    hook = HOOKS_DIR / hook_name
    assert hook.is_symlink(), f"{hook} is a copy, not a symlink - {rationale}"

    link = hook.readlink()
    assert not link.is_absolute(), (
        f"{hook} -> {link} is absolute; it must be relative to survive a clone to a different path"
    )
    assert "skills-vendor" in link.parts, f"{hook} -> {link} does not point into skills-vendor/"

    if not _submodule_checked_out():
        pytest.skip("skills-vendor/gregoryfoster-skills is not checked out")
    assert hook.resolve().is_file(), f"{hook} dangles: {link}"
