"""Tag ``archiver-client`` releases as ``sdk-v<version>``, and gate CI on it (archiver#409).

A consumer off this VM pins the SDK by git tag::

    archiver-client = { git = "https://github.com/CannObserv/archiver",
                        tag = "sdk-v5.19.0", subdirectory = "clients/python" }

**Which commit a tag marks (D1):** the commit on ``main``'s first-parent line where
``clients/python/pyproject.toml``'s version changes, which is the PR's merge
commit. It is the commit CI verified and the line ``deploy.sh`` deploys, and it
carries any fix the PR made after its bump commit. Both subcommands derive it the
same way, so the tag made and the tag checked cannot disagree.

**Tags are annotated and never moved:** a consumer's ``uv.lock`` pins the commit.
A wrong tag gets a new version; once it is tagged, raise ``FLOOR`` past the bad
one, with a note.

Usage::

    python3 scripts/sdk_tag.py tag [--push]   # after the bump PR merges
    python3 scripts/sdk_tag.py check <ref>    # CI: every release on <ref> is tagged

``tag`` fetches ``origin`` and annotates every untagged release on ``origin/main``
since ``FLOOR``; ``--push`` pushes them, and without it the push line is printed.
``check`` reads ``origin``'s tags with ``git ls-remote``, which is what a
consumer's ``uv`` sees.

Exit: 0 ok · 1 a release untagged or mis-tagged, or a refusal · 2 usage or git error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from dataclasses import dataclass

PYPROJECT = "clients/python/pyproject.toml"
PREFIX = "sdk-v"
REMOTE = "origin"
BRANCH = "main"
#: The first tagged release; older versions were never tagged (#409 D4).
FLOOR = "5.19.0"


class GitError(Exception):
    """A git command failed."""


@dataclass(frozen=True)
class Release:
    """An SDK version and the first-parent commit that introduced it."""

    version: str
    commit: str

    @property
    def tag(self) -> str:
        """The release's tag name."""
        return f"{PREFIX}{self.version}"


def git(*args: str, check: bool = True) -> str:
    """Run git and return its stripped stdout; raise GitError on failure."""
    result = subprocess.run(["git", *args], text=True, capture_output=True)
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def version_at(rev: str) -> str | None:
    """Return the SDK version at ``rev``, or None where the file is absent."""
    result = subprocess.run(["git", "show", f"{rev}:{PYPROJECT}"], text=True, capture_output=True)
    if result.returncode != 0:
        return None
    return tomllib.loads(result.stdout).get("project", {}).get("version")


def releases(ref: str, floor: str = FLOOR) -> list[Release]:
    """Every release at or above ``floor`` on ``ref``'s first-parent line, oldest first.

    A version that comes back (a reverted bump) keeps the commit that first set it,
    which is where its tag already is (CR 1).
    """
    found: dict[str, Release] = {}
    commits = git("rev-list", "--first-parent", "--reverse", ref, "--", PYPROJECT).split()
    for commit in commits:
        version = version_at(commit)
        if version is None or version in found or version == version_at(f"{commit}^1"):
            continue
        if _key(version) >= _key(floor):
            found[version] = Release(version, commit)
    return list(found.values())


def remote_tags(remote: str = REMOTE) -> dict[str, tuple[str, str | None]]:
    """``origin``'s ``sdk-v*`` tags: name -> (object, peeled commit or None if lightweight)."""
    tags: dict[str, list[str | None]] = {}
    out = git("ls-remote", "--tags", remote, f"refs/tags/{PREFIX}*")
    for line in out.splitlines():
        sha, ref = line.split("\t")
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            tags.setdefault(name[:-3], [None, None])[1] = sha
        else:
            tags.setdefault(name, [None, None])[0] = sha
    return {name: (obj, peeled) for name, (obj, peeled) in tags.items()}


def problem(release: Release, tags: dict[str, tuple[str, str | None]]) -> str | None:
    """Why ``release``'s tag on origin is unusable, or None when it is right."""
    if release.tag not in tags:
        return f"{release.tag} is not on {REMOTE}"
    _, peeled = tags[release.tag]
    if peeled is None:
        return f"{release.tag} on {REMOTE} is lightweight, not annotated"
    if peeled != release.commit:
        return (
            f"{release.tag} on {REMOTE} marks {peeled[:12]}, not {release.commit[:12]}, "
            f"the first-parent commit that set {release.version}"
        )
    return None


def check(ref: str) -> int:
    """Exit 1 unless every release since FLOOR on ``ref`` has its tag on origin."""
    tags = remote_tags()
    found = releases(ref)
    problems = [p for r in found if (p := problem(r, tags))]
    if not problems:
        print(f"sdk_tag: {len(found)} release(s) since {FLOOR} on {ref[:12]}, all tagged")
        return 0
    for p in problems:
        print(f"sdk_tag: {p}", file=sys.stderr)
    print(
        "sdk_tag: tag an untagged release from the main checkout with "
        "`python3 scripts/sdk_tag.py tag --push` (the operator approves the push). "
        "A wrong tag is never moved: release a new version, then raise FLOOR "
        "(docs/DEPLOYMENT.md § Releases).",
        file=sys.stderr,
    )
    return 1


def _local_tag(release: Release) -> str | None:
    """Why a local tag of this name can't be pushed, or None if absent or right."""
    if not git("tag", "--list", release.tag):
        return None
    if git("cat-file", "-t", release.tag) != "tag":
        return f"local {release.tag} is lightweight; delete it and rerun"
    commit = git("rev-parse", f"{release.tag}^{{commit}}")
    if commit != release.commit:
        return f"local {release.tag} marks {commit[:12]}, not {release.commit[:12]}"
    return None


def tag(push: bool) -> int:
    """Annotate every untagged release on origin/main since FLOOR; push with ``push``."""
    git("fetch", "--quiet", REMOTE, BRANCH)
    tags = remote_tags()
    pending = []
    for release in releases(f"{REMOTE}/{BRANCH}"):
        if release.tag in tags:
            if why := problem(release, tags):
                print(f"sdk_tag: {why}; a pushed tag is never moved", file=sys.stderr)
                return 1
            print(f"sdk_tag: {release.tag} already on {REMOTE} at {release.commit[:12]}")
            continue
        if why := _local_tag(release):
            print(f"sdk_tag: {why}", file=sys.stderr)
            return 1
        if not git("tag", "--list", release.tag):
            git(
                "tag",
                "-a",
                release.tag,
                release.commit,
                "-m",
                f"archiver-client {release.version}\n\nSee CHANGELOG.md [sdk].",
            )
        print(f"sdk_tag: {release.tag} -> {release.commit[:12]}")
        pending.append(release)
    if not pending:
        return 0
    refs = [f"refs/tags/{r.tag}" for r in pending]
    if push:
        git("push", "--quiet", REMOTE, *refs)
        print(f"sdk_tag: pushed {', '.join(r.tag for r in pending)}")
    else:
        print(f"push with: git push {REMOTE} {' '.join(refs)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse the subcommand and run it."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    tag_cmd = sub.add_parser("tag", help="annotate untagged releases on origin/main")
    tag_cmd.add_argument("--push", action="store_true", help="push the new tags to origin")
    check_cmd = sub.add_parser("check", help="every release on REF is tagged on origin")
    check_cmd.add_argument("ref")
    args = parser.parse_args(argv)
    try:
        return tag(args.push) if args.command == "tag" else check(args.ref)
    except GitError as e:
        print(f"sdk_tag: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
