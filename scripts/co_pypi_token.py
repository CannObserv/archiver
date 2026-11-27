"""Run one ``uv`` command with a co-pypi access token in its environment (archiver#498).

    bash scripts/co-pypi.sh uv sync                         # a checkout or worktree
    bash scripts/co-pypi.sh uv lock --upgrade-package co-core   # a pin change (#454)

``co-core`` and ``co-core-aio`` resolve from cannobserv's co-pypi Artifact
Registry index (``pyproject.toml``'s ``[[tool.uv.index]]``). It takes HTTP basic
auth: the username ``oauth2accesstoken`` and an OAuth2 access token as the
password, which uv reads from ``UV_INDEX_CO_PYPI_USERNAME`` /
``UV_INDEX_CO_PYPI_PASSWORD``. The host has no gcloud, so this mints the token
from the read-only ``co-pypi-reader`` key (``roles/artifactregistry.reader`` on
co-pypi; it was the wheelhouse bucket's reader before) at
``/etc/archiver/co-pypi-reader.json``, or at ``ARCHIVER_CO_PYPI_KEY``, and
``exec``s the command with the pair in that child's environment alone. Ported
from CannObserv/broker#144 (processor#121's locked group, replicator#183's
allowlist).

**Never ``GOOGLE_APPLICATION_CREDENTIALS``.** Set shell-wide, that names an
identity to every Google client in the shell; the key path is explicit, so
google-auth's ADC search never runs. ``scripts/deploy.sh`` reads the key's path
from ``deploy.env`` and passes it as ``ARCHIVER_CO_PYPI_KEY``. **The caller's
environment never reaches uv:** ``scripts/co-pypi.sh`` starts the outer ``uv
run`` from an allowlist and :func:`child_environment` cuts the wrapped
command's again, so the PATs a loaded repo ``.env`` carries reach neither.

**The token is never printed, logged, put in argv or written anywhere.** It
lives in this process and the wrapped ``uv``'s environment, an hour at most.
Anything but ``uv`` is refused before a token is minted. **Accepted limit:**
whatever that ``uv`` spawns inherits the pair - hatchling, building the
editable project, and ``git`` for the two git-sourced SDKs. uv has no per-index
credential scoping short of a keyring or netrc file; the bound is the
identity's read-only role and the token's hour.

Its own dependency is uv.lock's ``co-pypi`` group, run ``--isolated --frozen``
from this script's tree (``scripts/co-pypi.sh``), so nothing in the process that
holds the key is resolved at run time, and the project's ``.venv`` (a release's,
under ``deploy.sh``) is never touched by it.

Only a command that downloads from the index needs this: ``uv lock``, and a
``uv sync`` that needs a co-core file neither installed nor cached. ``uv run``
on a synced venv, ``uv lock --check`` and ``uv audit --frozen`` don't.

Exit codes: the wrapped command's own - ``2`` usage or a refused command -
``1`` the mint failed (the key included) - ``127`` the command could not be run.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2 import service_account

USERNAME_VAR = "UV_INDEX_CO_PYPI_USERNAME"
PASSWORD_VAR = "UV_INDEX_CO_PYPI_PASSWORD"
USERNAME = "oauth2accesstoken"
# The host's key: root:exedev 640 in /etc/archiver, the reader the wheelhouse
# sync used before #498 (deploy.env names the same file for scripts/deploy.sh).
DEFAULT_KEY = "/etc/archiver/co-pypi-reader.json"
KEY_VAR = "ARCHIVER_CO_PYPI_KEY"
# Artifact Registry's documented scope for a token-as-password read; the
# identity's IAM role, artifactregistry.reader on co-pypi, is what bounds it.
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
# What uv may see. scripts/co-pypi.sh carries the same two lists, plus KEY_VAR
# (tests/scripts/test_co_pypi_token.py holds them equal). VIRTUAL_ENV is left out:
# the outer `uv run` sets it to its throwaway env, and a wrapped `uv sync` would
# warn about it.
ALLOWED = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "LANG", "TERM", "TMPDIR",
        "http_proxy", "https_proxy", "no_proxy", "all_proxy",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    }
)  # fmt: skip
ALLOWED_PREFIXES = ("LC_", "XDG_", "SSL_CERT_", "UV_")
USAGE = "usage: bash scripts/co-pypi.sh uv <command> [args...]"


def child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """*environ* cut to the allowlist."""
    return {k: v for k, v in environ.items() if k in ALLOWED or k.startswith(ALLOWED_PREFIXES)}


def mint_token(key_path: str) -> str:
    """An access token for the service account whose key is at *key_path*."""
    credentials = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    credentials.refresh(Request())
    if not credentials.token:
        raise RuntimeError("the token endpoint returned no access token")
    return credentials.token


def main(
    argv: Sequence[str],
    environ: Mapping[str, str],
    *,
    mint: Callable[[str], str] = mint_token,
    execvpe: Callable[[str, list[str], dict[str, str]], object] = os.execvpe,
) -> int | None:
    """Exec *argv* (a ``uv`` command) with the co-pypi pair in its environment.

    Returns an exit code on failure; on success *execvpe* replaces the process,
    so in production nothing returns.
    """
    if not argv or Path(argv[0]).name != "uv":
        print(f"error: co-pypi wraps uv alone. {USAGE}", file=sys.stderr)
        return 2

    key_path = environ.get(KEY_VAR, "").strip() or DEFAULT_KEY
    try:
        token = mint(key_path)
    except Exception as exc:  # broad by design: any failure here runs nothing
        # The exception is the token endpoint's or the key file's, never the token.
        print(
            f"error: could not mint a co-pypi access token from {key_path}:"
            f" {type(exc).__name__}: {exc}. The key: docs/DEPLOYMENT.md, The co-pypi index.",
            file=sys.stderr,
        )
        return 1

    env = child_environment(environ)
    env[USERNAME_VAR] = USERNAME
    env[PASSWORD_VAR] = token
    try:
        execvpe(argv[0], list(argv), env)
    except OSError as exc:
        # Names the command and errno, never `env`.
        print(f"error: could not run {argv[0]}: {exc.strerror or exc}", file=sys.stderr)
        return 127
    return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
