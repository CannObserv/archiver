"""Drift tests for the shared SocratiCode index client config (archiver#226).

Archiver does not host its semantic index. `.socraticode.json` and the `env`
block in `.claude/settings.json` are the whole client contract against the
cohort's shared Qdrant on `co-index`; both are committed so every checkout
addresses the same collections wherever the working tree sits on disk.

Each assertion below pins a failure mode that reports itself as *green*:

- a missing or malformed `.socraticode.json` degrades to the path-hash project
  id (this repo's was `7a9d625938ee`) with no message;
- `QDRANT_HOST` instead of `QDRANT_URL` builds an https URL against port 16333
  and surfaces as a network fault (trap 3);
- the short MagicDNS name is not in the Qdrant certificate's SAN (trap 4);
- `QDRANT_COLLECTION_PREFIX` and `SOCRATICODE_BRANCH_AWARE` fragment the
  cohort namespace while every health check still says green (trap 5);
- an ungitignored `.claude/settings.local.json` puts the cohort's single Qdrant
  key one `git add -A` from GitHub, which is what happened in CannObserv/broker
  (notifier#68, broker#18).

Upstream design and decisions D0-D14: `docs/plans/2026-09-11-shared-qdrant-vm-design.md`
in CannObserv/notifier, tracked by CannObserv/notifier#57.
"""

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".socraticode.json"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

#: Upstream's own validator: config.js assertValidProjectId rejects anything else.
PROJECT_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

#: The other four cohort repos. Archiver links all of them; a stub that names a
#: collection nobody has indexed yet is skipped per-collection, not fatal.
COHORT_SIBLINGS = {"../broker", "../notifier", "../replicator", "../watcher"}

#: The six client variables, and the only values that reach the shared store.
EXPECTED_ENV = {
    "QDRANT_MODE": "external",
    "QDRANT_URL": "https://index.taild0fb76.ts.net:6333",
    "OLLAMA_MODE": "external",
    "OLLAMA_URL": "http://index:11434",
    "EMBEDDING_MODEL": "nomic-embed-text",
    # 768 is nomic-embed-text's width. A mismatch does not error - it writes
    # vectors Qdrant accepts and nothing can be searched against.
    "EMBEDDING_DIMENSIONS": "768",
}

#: Set either, and the cohort's collections split in a way nothing reports: the
#: prefix is prepended to the instance-global socraticode_metadata collection as
#: well as the per-project ones, and branch-awareness appends the branch name to
#: the project id - a fresh six-collection set, re-indexed from empty, per branch.
NAMESPACE_GUARD_VARS = ["QDRANT_COLLECTION_PREFIX", "SOCRATICODE_BRANCH_AWARE"]

#: Everywhere a variable could reach the MCP server's environment on this host.
#: VM-local files are skipped loudly rather than passing vacuously in CI.
NAMESPACE_GUARD_FILES = [
    Path("/etc/archiver/.env"),
    REPO_ROOT / ".env",
    SETTINGS,
    REPO_ROOT / ".claude" / "settings.local.json",
    REPO_ROOT / "deploy" / "archiver.service",
    REPO_ROOT / "deploy" / "archiver-bus-health.service",
]


@pytest.fixture(scope="module")
def config() -> dict:
    return json.loads(CONFIG.read_text())


@pytest.fixture(scope="module")
def settings_env() -> dict:
    return json.loads(SETTINGS.read_text()).get("env", {})


def test_config_exists_and_parses():
    """A malformed file is ignored by upstream, not reported.

    loadSocratiCodeConfig catches every parse error and returns null, so a typo
    here degrades to the path-hash id in silence - the same silence class as the
    linked-project skip.
    """
    assert CONFIG.exists(), f"{CONFIG.name} is missing"
    json.loads(CONFIG.read_text())


def test_project_id_is_the_repo_name(config):
    """`archiver`, so the collections read as codebase_archiver in a shared store."""
    assert config["projectId"] == "archiver"


def test_project_id_is_qdrant_safe(config):
    """Upstream throws on anything outside [a-zA-Z0-9_-]+ rather than sanitizing."""
    assert set(config["projectId"]) <= PROJECT_ID_CHARS


def test_linked_projects_are_relative(config):
    """Absolute paths are the defect this design replaces (notifier#57).

    Relative entries resolve against the repo root, so the same committed file
    works on every cohort VM. This repo previously linked watcher and notifier by
    absolute path through `SOCRATICODE_LINKED_PROJECTS`, from when all four
    services shared one box.
    """
    linked = config["linkedProjects"]
    assert linked, "linkedProjects is empty"
    for entry in linked:
        assert not Path(entry).is_absolute(), f"{entry} is absolute"
        assert entry.startswith("../"), f"{entry} does not name a sibling checkout"


def test_linked_projects_name_the_cohort(config):
    assert set(config["linkedProjects"]) == COHORT_SIBLINGS


def test_linked_projects_exclude_this_repo(config):
    """Upstream drops a self-link, but a self-link in the file is still a mistake."""
    assert f"../{REPO_ROOT.name}" not in config["linkedProjects"]


@pytest.mark.parametrize("variable", sorted(EXPECTED_ENV))
def test_client_variables_are_committed(variable: str, settings_env: dict):
    """Non-secret and self-documenting, so they travel with the checkout.

    Only `QDRANT_API_KEY` is per-host, and it lives in the gitignored
    settings.local.json - see test_settings_local_is_git_ignored.
    """
    assert settings_env.get(variable) == EXPECTED_ENV[variable]


def test_qdrant_is_addressed_by_url_not_host(settings_env: dict):
    """Trap 3: `QDRANT_HOST` is a trap, not a synonym.

    QDRANT_MODE=external refuses to start without a URL, and the fallback it
    would otherwise build is `${KEY ? https : http}://${QDRANT_HOST}:${QDRANT_PORT}`
    with QDRANT_PORT defaulting to 16333, not 6333. A key with no URL therefore
    assumes https against the wrong port and the error reads like a network fault.
    """
    assert "QDRANT_HOST" not in settings_env
    assert "QDRANT_PORT" not in settings_env


def test_qdrant_url_uses_the_full_magicdns_name(settings_env: dict):
    """Trap 4: the short name is not in the certificate's SAN.

    Qdrant serves TLS because SocratiCode refuses to send QDRANT_API_KEY over a
    non-TLS, non-localhost connection (notifier#57 D14). `https://index:6333`
    therefore fails the handshake; only the full MagicDNS name verifies.
    """
    url = settings_env["QDRANT_URL"]
    assert url.startswith("https://"), "the API key is refused over plain http"
    assert url.split("://", 1)[1].startswith("index.taild0fb76.ts.net:"), (
        "use the full MagicDNS name, not the short one"
    )


def test_no_api_key_is_committed(settings_env: dict):
    """The one variable that must never reach a tracked file.

    Qdrant holds a single global service.api_key - no key list, no per-client
    identity - so every cohort VM holds the same secret and a leak anywhere is a
    rotation everywhere, with no overlap window.
    """
    assert "QDRANT_API_KEY" not in settings_env


def test_settings_local_is_git_ignored():
    """Asks git, rather than reading .gitignore and assuming the answer.

    A rule can also come from .git/info/exclude or a global core.excludesfile,
    and `git check-ignore` is the only thing that sees all three. Four of the
    five cohort repos carried the rule, which is exactly what made the assertion
    read as true in the fifth - broker, which is public (notifier#68, broker#18).
    """
    target = ".claude/settings.local.json"
    result = subprocess.run(
        ["git", "check-ignore", "-v", "--no-index", target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{target} is not git-ignored: it would be committed"


@pytest.mark.parametrize("path", NAMESPACE_GUARD_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("variable", NAMESPACE_GUARD_VARS)
def test_namespace_guards_are_not_set_anywhere(variable: str, path: Path):
    """VM-local where the file is VM-local; skips loudly rather than passing vacuously."""
    if not path.exists():
        pytest.skip(f"{path} not present on this machine")
    assert variable not in path.read_text(), f"{path.name} sets {variable}"
