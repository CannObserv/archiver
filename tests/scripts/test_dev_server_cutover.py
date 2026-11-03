"""The dev-server launcher's cutover instant (archiver#369, D3).

``ARCHIVER_NOTIFY_CUTOVER_AT`` is ``archiver.service``'s own line. The launcher
drops whatever it inherited and maps ``ARCHIVER_DEV_NOTIFY_CUTOVER_AT`` onto it,
**only beside a mapped dev Notifier pair**, so a dev T only ever reaches the dev
tenant. Without the pair it stays shadow and says why (the gate would refuse T).
"""

from tests.scripts.test_dev_server_notifier import DEV_KEY, DEV_URL, _run

T = "2026-11-02T00:00:00Z"
PAIR = {"ARCHIVER_DEV_NOTIFIER_BASE_URL": DEV_URL, "ARCHIVER_DEV_NOTIFIER_API_KEY": DEV_KEY}


def _line(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("NOTIFY_CUTOVER="):
            return line[len("NOTIFY_CUTOVER=") :]
    raise AssertionError(f"no NOTIFY_CUTOVER= line in dry-run output:\n{stdout}")


def test_nothing_set_is_shadow() -> None:
    result = _run(PAIR)
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == "(shadow)"


def test_the_units_t_is_never_inherited() -> None:
    result = _run(PAIR | {"ARCHIVER_NOTIFY_CUTOVER_AT": T})
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == "(shadow)"


def test_a_dev_t_is_mapped_beside_the_dev_pair() -> None:
    result = _run(PAIR | {"ARCHIVER_DEV_NOTIFY_CUTOVER_AT": T})
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == T


def test_a_dev_t_without_the_pair_stays_shadow_and_says_so() -> None:
    result = _run({"ARCHIVER_DEV_NOTIFY_CUTOVER_AT": T})
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == "(shadow)"
    assert "ARCHIVER_DEV_NOTIFY_CUTOVER_AT ignored" in result.stderr
