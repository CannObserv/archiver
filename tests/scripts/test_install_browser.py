"""Tests for ``scripts/install_browser.sh``, the browser tier's Chromium (archiver#546).

The script is a thin, fixed call into ``playwright install``: the pinned package in
the lock's ``browser`` group decides the build, and Playwright itself skips a build
already in place, so a rerun is a no-op. What these tests hold is the call: the
group, the headless shell alone, the two flags the script passes through, and the
build summary it prints. A stub ``uv`` on ``PATH`` stands in for the real one, so
nothing downloads.
"""

import os
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install_browser.sh"

_STUB_UV = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$UV_STUB_LOG"
case " $* " in
  *" --dry-run "*)
    echo "Chrome Headless Shell 1.2.3 (playwright chromium-headless-shell v9999)"
    echo "  Install location:    /stub/ms-playwright/chromium_headless_shell-9999"
    echo "  Download url:        https://stub.invalid/shell.zip"
    ;;
esac
"""


def run(tmp_path: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the script against a stub ``uv``; return the result and the calls it made."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "uv"
    stub.write_text(_STUB_UV)
    stub.chmod(0o755)
    log = tmp_path / "uv.log"
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "UV_STUB_LOG": str(log),
            "HOME": os.environ["HOME"],
        },
        text=True,
        capture_output=True,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def test_installs_the_headless_shell_from_the_browser_group(tmp_path: Path) -> None:
    result, calls = run(tmp_path)
    assert result.returncode == 0, result.stderr
    install = calls[0].split()
    assert install[:5] == ["run", "--group", "browser", "playwright", "install"]
    assert install[-1] == "chromium"
    assert "--only-shell" in install
    assert "--no-progress" in install
    assert "--with-deps" not in install
    assert "--no-remove" not in install


def test_prints_the_build_and_where_it_lives(tmp_path: Path) -> None:
    result, calls = run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in calls[1].split()
    assert "chromium-headless-shell v9999" in result.stdout
    assert "Install location:    /stub/ms-playwright/chromium_headless_shell-9999" in result.stdout


def test_passes_with_deps_and_no_remove_through(tmp_path: Path) -> None:
    result, calls = run(tmp_path, "--with-deps", "--no-remove")
    assert result.returncode == 0, result.stderr
    install = calls[0].split()
    assert "--with-deps" in install
    assert "--no-remove" in install


def test_refuses_anything_else_before_calling_uv(tmp_path: Path) -> None:
    result, calls = run(tmp_path, "firefox")
    assert result.returncode == 2
    assert "usage" in result.stderr.lower()
    assert calls == []


def test_a_rerun_makes_the_same_calls(tmp_path: Path) -> None:
    """The script holds no state: idempotence is Playwright's skip of a present build."""
    _, first = run(tmp_path)
    (tmp_path / "uv.log").unlink(missing_ok=True)
    _, second = run(tmp_path)
    assert first == second


def test_the_group_it_names_is_in_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    groups = pyproject["dependency-groups"]
    assert any(spec.startswith("playwright") for spec in groups["browser"])
    assert not any(spec.startswith("playwright") for spec in groups["dev"])
    assert "browser" not in pyproject.get("tool", {}).get("uv", {}).get("default-groups", [])
