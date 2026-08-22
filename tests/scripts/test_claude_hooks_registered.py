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
import os
from pathlib import Path

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


def test_socraticode_health_hook_is_a_symlink_into_the_vendor() -> None:
    """It is silent when clean, so a frozen copy looks exactly like a healthy one.

    Every other hook betrays a stale copy eventually by printing something dated.
    This one's success output is nothing at all, which is also what a copy that
    has stopped detecting anything prints (gregoryfoster/skills#179). Symlinked
    into ``skills-vendor/``, it tracks upstream on the normal submodule refresh
    and ``.skills/doctor.sh`` can see it break; copied, neither holds.
    """
    hook = HOOKS_DIR / "socraticode-health.sh"
    assert hook.is_symlink(), (
        f"{hook} is not a symlink into skills-vendor/ - a copy freezes at install "
        "day and this hook is silent when clean, so the drift is undetectable"
    )
    target = hook.resolve()
    assert target.is_file(), f"{hook} dangles: {os.readlink(hook)}"
    assert (REPO_ROOT / "skills-vendor") in target.parents, (
        f"{hook} resolves to {target}, outside skills-vendor/"
    )
