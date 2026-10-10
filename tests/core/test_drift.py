"""``src.core.drift``: does live lag origin/main in code that runs (archiver#338)?

Ported from CannObserv/processor's ``tests/test_drift.py`` (processor#35), itself
from CannObserv/status's (status#12); their CR numbers are kept. GitHub's answers
are built here in the shapes its REST API returns: the compare (``status``,
``total_commits``, ``commits``, ``files``) and the CI workflow's runs. Verdicts
are tested through a fake ``get``; the getter and the command end to end through
respx. Never the network, and never the real monitor or key: a disabled monitor
still pages on an alert, and a stray ``ok`` masks real silence (status#32).
"""

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from src.core import drift
from src.core.drift import (
    COMPARE_FILES_LIMIT,
    GITHUB_API,
    GRACE,
    RUNS_PATH,
    GitHubNotFound,
    GitHubSilent,
    Push,
    Verdict,
    assess,
    counts,
    diff_counts,
    first_look,
    lagging,
    main,
    pushes,
    tip_ci,
)
from src.core.status_checkin import CREDENTIAL_NAME

NOW = datetime(2026, 10, 2, 22, 0, tzinfo=UTC)
LIVE = "deff23b0c287"
REPO = Path(__file__).resolve().parents[2]


def sha(n: int) -> str:
    """A distinct full-length commit id."""
    return f"{n:040x}"


def commit(n: int, committed: datetime = NOW) -> dict:
    return {"sha": sha(n), "commit": {"committer": {"date": committed.isoformat()}}}


def compare(*shas: int, files=("src/core/drift.py",), status="ahead", total=None) -> dict:
    """GitHub's ``compare/<live>...main``: *shas* oldest first, the last one main's."""
    answer = {
        "status": status,
        "total_commits": len(shas) if total is None else total,
        "commits": [commit(n) for n in shas],
    }
    if files is not None:
        answer["files"] = [{"filename": f} for f in files]
    return answer


def run(
    n: int,
    created: datetime,
    *,
    event="push",
    branch="main",
    status="completed",
    conclusion="success",
) -> dict:
    return {
        "head_sha": sha(n),
        "event": event,
        "head_branch": branch,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
    }


def runs(*items: dict) -> dict:
    return {"workflow_runs": list(items)}


class TestCounts:
    """What runs is an allowlist, defined once in ``drift``."""

    @pytest.mark.parametrize(
        "path",
        [
            "src/core/drift.py",
            "src/api/main.py",
            "src/dashboard/templates/base.html",
            "alembic/versions/43c76bf61952_x.py",
            "alembic/env.py",
            "alembic.ini",
            "deploy/archiver.service",
            "deploy/archiver-drift.timer",
            "scripts/deploy.sh",
            "scripts/check_redis_floor.sh",
            "pyproject.toml",
            "uv.lock",
        ],
    )
    def test_what_runs_counts(self, path):
        assert counts(path)

    @pytest.mark.parametrize(
        "path",
        [
            "docs/DEPLOYMENT.md",
            "docs/plans/2026-10-09-330-deploy-releases-design.md",
            "CLAUDE.md",
            "AGENTS.md",
            "CHANGELOG.md",
            "tests/core/test_drift.py",
            ".github/workflows/ci.yml",
            ".claude/settings.json",
            "skills/using-git-worktrees/SKILL.md",
            "skills-vendor/gregoryfoster-skills",
            ".skills/worktree_venv",
            "clients/python/src/archiver_client/client.py",
            "scripts/dev_server.sh",
            "scripts/sync_wheelhouse.py",
            ".gitmodules",
            "srcery/x.py",
            "deployment.md",
        ],
    )
    def test_what_never_runs_does_not(self, path):
        assert not counts(path)

    def test_every_path_a_unit_executes_from_the_release_counts(self):
        """A unit's ``Exec*=`` under ``/srv/archiver/live`` runs from the release:
        a change there that was never deployed is drift. ``.venv/`` is built at
        deploy from ``pyproject.toml`` and ``uv.lock``, which count."""
        executed = set()
        for unit in (REPO / "deploy").glob("*.service"):
            for line in unit.read_text().splitlines():
                m = re.match(r"^Exec[A-Za-z]*=[-+@!:]*(\S+)", line)
                if m and m.group(1).startswith("/srv/archiver/live/") and "/.venv/" not in m[1]:
                    executed.add(m.group(1).removeprefix("/srv/archiver/live/"))
        assert "scripts/check_redis_floor.sh" in executed, "the scan found nothing"
        assert [p for p in sorted(executed) if not counts(p)] == []

    def test_every_module_a_unit_runs_counts(self):
        modules = set()
        for unit in (REPO / "deploy").glob("*.service"):
            for line in unit.read_text().splitlines():
                if line.startswith("ExecStart"):
                    modules |= set(re.findall(r"(?:-m |uvicorn )([A-Za-z_][\w.]*)", line))
        assert "src.core.drift" in modules
        paths = [m.split(":")[0].replace(".", "/") + ".py" for m in modules]
        assert [p for p in paths if not counts(p)] == []


class TestDiffCounts:
    def test_docs_alone_do_not_count(self):
        assert not diff_counts(compare(1, files=["docs/a.md", "tests/test_a.py"]))

    def test_one_path_that_runs_is_enough(self):
        assert diff_counts(compare(1, files=["docs/a.md", "src/core/drift.py"]))

    def test_a_file_moved_out_of_a_runtime_path_counts(self):
        """Its old path left the release: ``previous_filename`` says where it was."""
        answer = compare(1, files=[])
        answer["files"] = [{"filename": "docs/old.py", "previous_filename": "src/core/x.py"}]
        assert diff_counts(answer)

    def test_no_file_list_counts(self):
        assert diff_counts(compare(1, files=None))

    def test_a_file_list_at_githubs_limit_counts(self):
        """GitHub cuts the list off there; what follows could be anything."""
        assert diff_counts(compare(1, files=["docs/a.md"] * COMPARE_FILES_LIMIT))

    def test_a_commit_list_cut_short_counts(self):
        assert diff_counts(compare(1, files=["docs/a.md"], total=300))


class TestVerdict:
    @pytest.mark.parametrize(
        ("kind", "status"),
        [("ok", "ok"), ("lag", "alert"), ("off_main", "alert"), ("unstamped", "alert"),
         ("test", "alert"), ("silent", None)],
    )  # fmt: skip
    def test_the_check_in_each_kind_sends(self, kind, status):
        assert Verdict(kind, "b", LIVE).status == status

    def test_every_check_in_carries_every_variable(self):
        """The monitor's template renders on any alert: none may be missing (status#32)."""
        assert Verdict("off_main", "b", LIVE).variables() == {
            "kind": "off_main",
            "live": LIVE,
            "main": "unknown",
            "body": "b",
        }

    @pytest.mark.parametrize("kind", ["lag", "off_main", "unstamped", "test"])
    def test_an_alert_names_its_fault(self, kind):
        """status#28: a change of fault reports at once only when Status is told it."""
        assert Verdict(kind, "b", LIVE).metadata() == {"fault": kind}

    def test_an_ok_names_no_fault(self):
        assert Verdict("ok", "b", LIVE).metadata() is None


class TestFirstLook:
    def test_unstamped_alerts(self):
        verdict = first_look(None, compare())
        assert (verdict.kind, verdict.status, verdict.live) == ("unstamped", "alert", "unknown")
        assert "no REVISION" in verdict.body

    def test_identical_is_ok(self):
        verdict = first_look(LIVE, compare(status="identical", files=[]))
        assert verdict == Verdict("ok", f"live {LIVE} is main", LIVE, LIVE)

    @pytest.mark.parametrize("status", ["diverged", "behind"])
    def test_live_not_on_main_alerts(self, status):
        verdict = first_look(LIVE, compare(1, status=status))
        assert verdict.kind == "off_main"
        assert f"live {LIVE} is not on main" in verdict.body
        assert status in verdict.body
        assert verdict.main == sha(1)[:12]

    def test_ahead_in_docs_alone_is_ok(self):
        verdict = first_look(LIVE, compare(1, 2, files=["docs/plans/x.md"]))
        assert verdict.kind == "ok"
        assert "2 commits ahead, none that runs" in verdict.body
        assert verdict.main == sha(2)[:12]

    def test_ahead_in_code_needs_the_clock(self):
        assert first_look(LIVE, compare(1)) is None


class TestPushes:
    def test_each_push_is_its_runs_creation_oldest_first(self):
        found = pushes(
            compare(1, 2, 3),
            runs(run(3, NOW - timedelta(hours=1)), run(1, NOW - timedelta(hours=5))),
        )
        assert found == [
            Push(sha(1), NOW - timedelta(hours=5)),
            Push(sha(3), NOW - timedelta(hours=1)),
        ]

    def test_runs_of_deployed_commits_are_not_pushes_since(self):
        found = pushes(compare(2), runs(run(1, NOW - timedelta(days=2)), run(2, NOW)))
        assert found == [Push(sha(2), NOW)]

    def test_only_push_runs_on_main(self):
        found = pushes(
            compare(1, 2),
            runs(
                run(1, NOW - timedelta(hours=9), event="workflow_dispatch"),
                run(1, NOW - timedelta(hours=8), event="pull_request", branch="338-drift-check"),
                run(2, NOW),
            ),
        )
        assert found == [Push(sha(2), NOW)]

    def test_a_commit_with_two_push_runs_was_pushed_at_the_first(self):
        found = pushes(compare(1), runs(run(1, NOW), run(1, NOW - timedelta(hours=2))))
        assert found == [Push(sha(1), NOW - timedelta(hours=2))]

    def test_a_tip_with_no_run_falls_back_to_its_commit_date(self):
        """``[skip ci]``: GitHub ran nothing, so the commit is the only clock."""
        answer = compare(1, 2)
        answer["commits"][1] = commit(2, NOW - timedelta(hours=3))
        found = pushes(answer, runs(run(1, NOW - timedelta(hours=4))))
        assert found == [
            Push(sha(1), NOW - timedelta(hours=4)),
            Push(sha(2), NOW - timedelta(hours=3)),
        ]

    def test_no_runs_at_all_is_the_tips_commit_date(self):
        answer = compare(1)
        answer["commits"][0] = commit(1, NOW - timedelta(hours=3))
        assert pushes(answer, runs()) == [Push(sha(1), NOW - timedelta(hours=3))]

    def test_a_tip_with_no_run_landed_no_earlier_than_the_pushes_under_it(self):
        """An old ``[skip ci]`` commit pushed on top: never sorted before main's pushes (CR 10)."""
        answer = compare(1, 2)
        answer["commits"][1] = commit(2, NOW - timedelta(days=3))
        found = pushes(answer, runs(run(1, NOW - timedelta(hours=2))))
        assert found[-1] == Push(sha(2), NOW - timedelta(hours=2)), "the walk relies on it"


class TestTipCi:
    def test_the_newest_push_runs_conclusion(self):
        answer = runs(
            run(2, NOW - timedelta(hours=2), conclusion="failure"),
            run(2, NOW - timedelta(hours=1), conclusion="success"),
            run(1, NOW, conclusion="cancelled"),
        )
        assert tip_ci(answer, sha(2)) == "success"

    def test_unfinished_is_its_status(self):
        assert tip_ci(runs(run(2, NOW, status="in_progress")), sha(2)) == "in_progress"

    def test_no_run(self):
        assert tip_ci(runs(run(1, NOW)), sha(2)) == "no run"


class TestLagging:
    def test_within_grace_is_ok(self):
        """The clock's push, never "in code since": unwalked, it may be docs only (CR 4)."""
        since = Push(sha(1), NOW - GRACE + timedelta(minutes=1))
        verdict = lagging(LIVE, compare(1, 2), since, ci="success", now=NOW)
        assert verdict == Verdict(
            "ok",
            f"live {LIVE}, main {sha(2)[:12]}: 2 commits ahead, the clock started at the push "
            "of 2026-10-02T14:01:00Z (8.0 h ago; grace 8 h)",
            LIVE,
            sha(2)[:12],
        )

    def test_past_grace_is_a_lag_naming_mains_ci(self):
        since = Push(sha(1), NOW - GRACE - timedelta(minutes=30))
        verdict = lagging(LIVE, compare(1), since, ci="failure", now=NOW)
        assert (verdict.kind, verdict.status) == ("lag", "alert")
        assert verdict.body.endswith(
            "(8.5 h ago; grace 8 h). main's CI: failure — deploy.sh refuses it until CI passes"
        )

    def test_past_grace_with_green_ci_says_deploy(self):
        since = Push(sha(1), NOW - timedelta(days=2))
        verdict = lagging(LIVE, compare(1), since, ci="success", now=NOW)
        assert verdict.body.endswith("main's CI: success — scripts/deploy.sh")

    def test_one_commit_is_singular(self):
        since = Push(sha(1), NOW)
        assert "1 commit ahead," in lagging(LIVE, compare(1), since, ci="success", now=NOW).body


class Unrouted(Exception):
    """A path the test did not expect asked; assess must not swallow it."""


class FakeGitHub:
    """``get`` for :func:`assess`: answers by path, records each call."""

    def __init__(self) -> None:
        self.answers: dict[str, object] = {}
        self.calls: list[str] = []

    def route(self, path: str, answer: object) -> None:
        self.answers[path] = answer

    def __call__(self, path: str):
        self.calls.append(path)
        if path not in self.answers:
            raise Unrouted(path)
        answer = self.answers[path]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


def _route_compare(github: FakeGitHub, head: str, answer: object) -> None:
    github.route(f"compare/{LIVE}...{head}", answer)


class TestAssess:
    def test_unstamped_asks_github_nothing(self, github):
        assert assess(None, now=NOW, get=github).kind == "unstamped"
        assert not github.calls

    def test_in_sync_is_one_call(self, github):
        _route_compare(github, "main", compare(status="identical", files=[]))
        assert assess(LIVE, now=NOW, get=github).kind == "ok"
        assert len(github.calls) == 1

    def test_docs_alone_never_ask_for_runs(self, github):
        _route_compare(github, "main", compare(1, files=["docs/a.md"]))
        assert assess(LIVE, now=NOW, get=github).kind == "ok"
        assert len(github.calls) == 1

    def test_code_within_grace_is_two_calls(self, github):
        _route_compare(github, "main", compare(1))
        github.route(RUNS_PATH, runs(run(1, NOW - timedelta(hours=1))))
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict.kind == "ok"
        assert "1.0 h ago" in verdict.body
        assert len(github.calls) == 2

    def test_code_past_grace_is_a_lag(self, github):
        _route_compare(github, "main", compare(1))
        github.route(RUNS_PATH, runs(run(1, NOW - timedelta(hours=9))))
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict.kind == "lag"
        assert "main's CI: success" in verdict.body
        assert len(github.calls) == 2

    def test_old_docs_then_new_code_starts_the_clock_at_the_code(self, github):
        """Live sat behind a docs push for two days; code pushed an hour ago is not late."""
        _route_compare(github, "main", compare(1, 2))
        github.route(
            RUNS_PATH, runs(run(1, NOW - timedelta(days=2)), run(2, NOW - timedelta(hours=1)))
        )
        _route_compare(github, sha(1), compare(1, files=["docs/a.md"]))
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict.kind == "ok"
        assert "1.0 h ago" in verdict.body

    def test_old_code_then_new_docs_is_late(self, github):
        _route_compare(github, "main", compare(1, 2))
        github.route(
            RUNS_PATH, runs(run(1, NOW - timedelta(days=2)), run(2, NOW - timedelta(hours=1)))
        )
        _route_compare(github, sha(1), compare(1))
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict.kind == "lag"
        assert "48.0 h ago" in verdict.body

    @staticmethod
    def _docs_pushes_then_code(github: FakeGitHub, third: timedelta) -> None:
        """Pushes 4 and 3 days ago, docs only; a third *third* ago; main now."""
        _route_compare(github, "main", compare(1, 2, 3, 4))
        github.route(
            RUNS_PATH,
            runs(
                run(1, NOW - timedelta(days=4)),
                run(2, NOW - timedelta(days=3)),
                run(3, NOW - third),
                run(4, NOW),
            ),
        )
        for n in (1, 2, 3):
            _route_compare(github, sha(n), compare(n, files=["docs/a.md"]))

    def test_an_old_skip_ci_tip_on_new_code_is_not_late(self, github):
        """Code pushed 2 h ago under a [skip ci] commit written 3 days ago (CR 10)."""
        answer = compare(1, 2)
        answer["commits"][1] = commit(2, NOW - timedelta(days=3))
        _route_compare(github, "main", answer)
        github.route(RUNS_PATH, runs(run(1, NOW - timedelta(hours=2))))
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict.kind == "ok"
        assert "2.0 h ago" in verdict.body

    def test_the_walk_stops_at_the_first_push_inside_the_grace(self, github):
        """It, or a newer push, brought the code: ok either way, so ask no further (CR 14)."""
        _route_compare(github, "main", compare(1, 2, 3))
        github.route(
            RUNS_PATH,
            runs(
                run(1, NOW - timedelta(days=2)),
                run(2, NOW - timedelta(hours=1)),
                run(3, NOW),
            ),
        )
        _route_compare(github, sha(1), compare(1, files=["docs/a.md"]))
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict.kind == "ok"
        assert "1.0 h ago" in verdict.body
        assert f"compare/{LIVE}...{sha(2)}" not in github.calls

    def test_the_walk_stops_at_its_limit_at_the_first_push_unchecked(self, github, monkeypatch):
        """Pushes 1 and 2 are known not to count: the code came with 3 at the earliest (CR 1)."""
        monkeypatch.setattr(drift, "WALK_LIMIT", 2)
        self._docs_pushes_then_code(github, timedelta(days=2))
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict.kind == "lag", "the code may be as old as push 3"
        assert "48.0 h ago" in verdict.body
        assert len(github.calls) == 2 + 2

    def test_past_the_limit_recent_code_is_not_late(self, github, monkeypatch):
        monkeypatch.setattr(drift, "WALK_LIMIT", 2)
        self._docs_pushes_then_code(github, timedelta(hours=1))
        assert assess(LIVE, now=NOW, get=github).kind == "ok"


class TestAssessWhenGitHubCannotSay:
    """Silent: no check-in at all, so a long outage ends in Status's ``missing``."""

    def test_a_refusal_is_silent_with_githubs_message(self, github):
        _route_compare(github, "main", GitHubSilent("403 API rate limit exceeded for 1.2.3.4."))
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict == Verdict(
            "silent", "GitHub did not answer: 403 API rate limit exceeded for 1.2.3.4.", LIVE
        )
        assert verdict.status is None

    def test_live_unknown_to_github_is_off_main(self, github):
        """GitHub answers 404 for a base it does not know: not on main, said so (CR 2)."""
        _route_compare(github, "main", GitHubNotFound("404 Not Found"))
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict.kind == "off_main"
        assert verdict.body.startswith(f"GitHub does not know live {LIVE} (404 Not Found)")

    def test_a_404_on_anything_else_is_silent(self, github):
        _route_compare(github, "main", compare(1))
        github.route(RUNS_PATH, GitHubNotFound("404 Not Found"))
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict == Verdict("silent", "GitHub did not answer: 404 Not Found", LIVE)

    @pytest.mark.parametrize("answer", [{"status": "ahead"}, {"status": "ahead", "commits": 3}])
    def test_unexpected_json_is_silent(self, github, answer):
        _route_compare(github, "main", answer)
        verdict = assess(LIVE, now=NOW, get=github)
        assert verdict.kind == "silent"
        assert "not the JSON expected" in verdict.body

    def test_unexpected_json_leaves_its_traceback_in_the_journal(self, github, monkeypatch):
        """A bug here would read as GitHub's fault without it (CR 3)."""
        seen: list[dict] = []
        monkeypatch.setattr(drift.logger, "warning", lambda *a, **kw: seen.append(kw))
        _route_compare(github, "main", {"status": "ahead"})
        assess(LIVE, now=NOW, get=github)
        assert [kw.get("exc_info") for kw in seen] == [True]


class TestTheGetter:
    """``drift.github``: GitHub's REST API over HTTPS, unauthenticated, bounded."""

    @respx.mock
    def test_an_answer_is_its_json_object(self):
        route = respx.get(f"{GITHUB_API}/compare/a...main").respond(json={"status": "identical"})
        assert drift.github()("compare/a...main") == {"status": "identical"}
        request = route.calls.last.request
        assert request.headers["Accept"] == "application/vnd.github+json"
        assert "Authorization" not in request.headers

    @respx.mock
    def test_a_refusal_names_githubs_message(self):
        respx.get(f"{GITHUB_API}/x").respond(403, json={"message": "API rate limit exceeded."})
        with pytest.raises(GitHubSilent, match="^403 API rate limit exceeded.$"):
            drift.github()("x")

    @respx.mock
    def test_a_404_is_its_own_kind(self):
        respx.get(f"{GITHUB_API}/x").respond(404, json={"message": "Not Found"})
        with pytest.raises(GitHubNotFound, match="^404 Not Found$"):
            drift.github()("x")

    @respx.mock
    def test_an_error_page_that_is_not_json_is_its_status(self):
        respx.get(f"{GITHUB_API}/x").respond(502, content=b"<html>Bad gateway</html>")
        with pytest.raises(GitHubSilent, match="^502$"):
            drift.github()("x")

    @pytest.mark.parametrize("body", [b"<html>", b"[]", b""], ids=repr)
    @respx.mock
    def test_an_answer_that_is_not_a_json_object_is_refused(self, body):
        """As deploy.sh's gate: an empty or wrong-shaped 200 never passes."""
        respx.get(f"{GITHUB_API}/x").respond(200, content=body)
        with pytest.raises(GitHubSilent, match="not a JSON object"):
            drift.github()("x")

    @respx.mock
    def test_unreachable_is_silent(self):
        respx.get(f"{GITHUB_API}/x").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(GitHubSilent, match="^ConnectError: refused$"):
            drift.github()("x")

    @respx.mock
    def test_every_call_shares_one_deadline(self, monkeypatch):
        """Bounded inside the unit's TimeoutStartSec, however many calls the walk makes."""
        now = [0.0]
        monkeypatch.setattr(drift, "time", SimpleNamespace(monotonic=lambda: now[0]))
        monkeypatch.setattr(drift, "CHECK_TIMEOUT_SECONDS", 10)
        respx.get(f"{GITHUB_API}/x").respond(json={})
        route = respx.get(f"{GITHUB_API}/y").respond(json={})
        get = drift.github()
        get("x")
        now[0] = 9.875  # the walk so far took 9.875 s: this call gets the 0.125 s left, not 10 s
        get("y")
        assert route.calls.last.request.extensions["timeout"]["read"] == 0.125

    @respx.mock
    def test_past_the_deadline_no_call_starts(self, monkeypatch):
        monkeypatch.setattr(drift, "CHECK_TIMEOUT_SECONDS", 0)
        route = respx.get(f"{GITHUB_API}/x").respond(json={})
        with pytest.raises(GitHubSilent, match="^Timeout: no GitHub call starts past 0 s$"):
            drift.github()("x")
        assert not route.called


# --- python -m src.core.drift, end to end -----------------------------------

MONITOR = "01M46EXP45TVCVAMQXK043N1Q7"
KEY = "sk-test-0123456789abcdef"
STATUS = "http://status.test:9000"
CHECKIN = f"{STATUS}/api/v1/monitors/{MONITOR}/checkin"


class World:
    """GitHub and Status behind respx; a release whose REVISION is ``LIVE``."""

    def __init__(self, tmp: Path, router: respx.Router, monkeypatch) -> None:
        self.router = router
        self.credentials = tmp / "credentials"
        self.credentials.mkdir()
        (self.credentials / CREDENTIAL_NAME).write_text(f"{KEY}\n")
        monkeypatch.setattr(drift, "build_id", lambda: LIVE)
        monkeypatch.setenv("ARCHIVER_STATUS_URL", STATUS)
        monkeypatch.setenv("CO_ARCHIVER_DRIFT_MONITOR_ID", MONITOR)
        monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(self.credentials))
        self.status = router.post(CHECKIN).respond(202, json={"monitor_id": MONITOR})

    @property
    def github_calls(self) -> list:
        return [c for c in self.router.calls if c.request.url.host == "api.github.com"]

    def lag(self, *, hours: float, files=("src/core/drift.py",)) -> None:
        """main one push ahead of live, *hours* ago, touching *files*."""
        self.router.get(f"{GITHUB_API}/compare/{LIVE}...main").respond(json=compare(1, files=files))
        self.router.get(f"{GITHUB_API}/{RUNS_PATH}").respond(
            json=runs(run(1, datetime.now(UTC) - timedelta(hours=hours)))
        )

    def checkins(self) -> list[dict]:
        return [json.loads(c.request.content) for c in self.status.calls]


@pytest.fixture
def _restore_root_logging():
    # main() reconfigures the process-wide root logger; put pytest's back after.
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def world(tmp_path, monkeypatch, _restore_root_logging):
    with respx.mock(assert_all_called=False) as router:
        yield World(tmp_path, router, monkeypatch)


def records(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]


def outcome(capsys) -> dict:
    (record,) = [r for r in records(capsys) if r["message"] == "drift check"]
    return record


class TestTheCommand:
    def test_a_runtime_lag_past_the_grace_alerts_with_its_fault(self, world, capsys):
        world.lag(hours=9)
        assert main([]) == 0
        (checkin,) = world.checkins()
        assert checkin["status"] == "alert"
        assert checkin["metadata"] == {"fault": "lag"}
        assert checkin["variables"]["kind"] == "lag"
        assert checkin["variables"]["live"] == LIVE
        assert checkin["variables"]["main"] == sha(1)[:12]
        assert "main's CI: success — scripts/deploy.sh" in checkin["variables"]["body"]
        record = outcome(capsys)
        assert record["level"] == "WARNING"
        assert record["logger"] == "src.core.drift"
        assert (record["build"], record["kind"], record["checkin"]) == (LIVE, "lag", 202)

    def test_a_docs_only_lag_is_ok_however_old(self, world, capsys):
        world.lag(hours=72, files=["docs/DEPLOYMENT.md", "tests/core/test_drift.py"])
        assert main([]) == 0
        (checkin,) = world.checkins()
        assert (checkin["status"], checkin["variables"]["kind"]) == ("ok", "ok")
        assert "metadata" not in checkin
        assert outcome(capsys)["level"] == "INFO"

    def test_a_runtime_lag_within_the_grace_is_ok(self, world):
        world.lag(hours=1)
        assert main([]) == 0
        assert world.checkins()[0]["status"] == "ok"

    def test_the_check_in_is_one_post_with_the_key_in_its_header_only(self, world, capsys):
        world.lag(hours=1)
        main([])
        (call,) = world.status.calls
        assert call.request.headers["X-API-Key"] == KEY
        assert KEY not in call.request.content.decode()
        assert KEY not in capsys.readouterr().out

    def test_an_unstamped_release_alerts_asking_github_nothing(self, world, monkeypatch, capsys):
        monkeypatch.setattr(drift, "build_id", lambda: None)
        assert main([]) == 0
        assert not world.github_calls
        (checkin,) = world.checkins()
        assert checkin["variables"]["kind"] == "unstamped"
        assert checkin["variables"]["live"] == "unknown"

    def test_github_silent_sends_nothing_and_fails(self, world, capsys):
        """Never a false ok: silence, which Status's grace turns into missing."""
        world.router.get(f"{GITHUB_API}/compare/{LIVE}...main").respond(
            403, json={"message": "rate limited"}
        )
        assert main([]) == 1
        assert not world.status.called
        record = outcome(capsys)
        assert (record["level"], record["kind"], record["checkin"]) == ("WARNING", "silent", None)
        assert "rate limited" in record["body"]

    def test_status_refusing_fails_once_with_no_retry(self, world, capsys):
        world.lag(hours=1)
        world.status.respond(401, json={"detail": "invalid API key"})
        assert main([]) == 1
        assert world.status.call_count == 1
        record = outcome(capsys)
        assert record["level"] == "ERROR"
        assert record["checkin"] == "failed: 401 invalid API key"

    def test_status_unreachable_fails(self, world, capsys):
        """A Status outage costs this check its exit code, nothing else."""
        world.lag(hours=1)
        world.status.mock(side_effect=httpx.ConnectError("refused"))
        assert main([]) == 1
        assert outcome(capsys)["checkin"] == "failed: ConnectError: refused"

    def test_no_key_fails_without_asking_status(self, world, capsys):
        (world.credentials / CREDENTIAL_NAME).write_text("\n")  # SetCredential's fallback
        world.lag(hours=1)
        assert main([]) == 1
        assert not world.status.called
        assert CREDENTIAL_NAME in outcome(capsys)["checkin"]

    def test_a_malformed_key_never_reaches_the_journal(self, world, capsys):
        (world.credentials / CREDENTIAL_NAME).write_text(f"{KEY}\n{KEY}\n")
        world.lag(hours=1)
        assert main([]) == 1
        assert not world.status.called
        out = capsys.readouterr().out
        assert KEY not in out
        assert '"message": "drift check"' in out

    def test_both_missing_are_named_in_one_line(self, world, monkeypatch, capsys):
        monkeypatch.delenv("CO_ARCHIVER_DRIFT_MONITOR_ID")
        (world.credentials / CREDENTIAL_NAME).write_text("\n")
        world.lag(hours=1)
        assert main([]) == 1
        assert not world.status.called
        assert outcome(capsys)["checkin"] == (
            f"not sent: missing CO_ARCHIVER_DRIFT_MONITOR_ID, the {CREDENTIAL_NAME} credential"
        )

    def test_a_monitor_id_that_is_not_a_ulid_is_refused_before_anything(
        self, world, monkeypatch, capsys
    ):
        """It lands in a URL path: ``../../admin`` must never reach Status."""
        monkeypatch.setenv("CO_ARCHIVER_DRIFT_MONITOR_ID", "../../admin")
        assert main([]) == 2
        assert not world.status.called and not world.github_calls
        assert any(r["message"] == "invalid settings" for r in records(capsys))

    def test_it_needs_no_database_and_no_production_opt_in(self, world, monkeypatch):
        """The unit has no EnvironmentFile=: nothing here may need one."""
        for name in ("ARCHIVER_DATABASE_URL", "DATABASE_URL", "ARCHIVER_ALLOW_PRODUCTION_DB"):
            monkeypatch.delenv(name, raising=False)
        world.lag(hours=1)
        assert main([]) == 0

    def test_test_alert_sends_one_alert_and_asks_github_nothing(self, world, capsys):
        assert main(["--test-alert"]) == 0
        assert not world.github_calls
        (checkin,) = world.checkins()
        assert checkin["status"] == "alert"
        assert checkin["metadata"] == {"fault": "test"}
        assert checkin["variables"]["kind"] == "test"
        assert set(checkin["variables"]) == {"kind", "live", "main", "body"}
        assert outcome(capsys)["kind"] == "test"
