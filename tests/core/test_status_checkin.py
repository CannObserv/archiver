"""``src.core.status_checkin``: one check-in to a co-status monitor (archiver#338).

Status's contract (CannObserv/status#32): ``POST /api/v1/monitors/{id}/checkin``
with ``{"status", "variables"}`` (plus ``metadata.fault`` on an alert, status#28)
and an ``X-API-Key``, answered 202. Routed through respx: never the network,
never the real monitor or key (a disabled monitor still pages on an alert, and
a stray ``ok`` masks real silence).
"""

import json
from pathlib import Path

import httpx
import pytest
import respx

from src.core.status_checkin import CREDENTIAL_NAME, CheckinFailed, post_checkin, read_key

BASE = "http://status.test:9000"
MONITOR = "01M46EXP45TVCVAMQXK043N1Q7"
KEY = "sk-test-0123456789abcdef"
CHECKIN = f"{BASE}/api/v1/monitors/{MONITOR}/checkin"
VARIABLES = {"kind": "ok", "live": "a" * 12, "main": "a" * 12, "body": "b"}


class TestReadKey:
    def test_the_credential_stripped_of_its_newline(self, tmp_path: Path) -> None:
        """The installed key file is 47 characters plus a newline (status#32)."""
        (tmp_path / CREDENTIAL_NAME).write_text(f"{KEY}\n")
        assert read_key(tmp_path) == KEY

    def test_no_credentials_directory_is_no_key(self) -> None:
        """Outside a unit there is no ``$CREDENTIALS_DIRECTORY`` at all."""
        assert read_key(None) == ""

    def test_an_absent_credential_is_no_key(self, tmp_path: Path) -> None:
        assert read_key(tmp_path) == ""

    def test_the_units_lone_newline_fallback_is_no_key(self, tmp_path: Path) -> None:
        """``SetCredential=status-checkin-key:\\n`` when the file is missing."""
        (tmp_path / CREDENTIAL_NAME).write_text("\n")
        assert read_key(tmp_path) == ""


class TestPostCheckin:
    @respx.mock
    def test_one_post_with_the_key_in_its_header_only(self) -> None:
        route = respx.post(CHECKIN).mock(return_value=httpx.Response(202, json={}))
        assert post_checkin(BASE, MONITOR, KEY, "ok", VARIABLES) == 202
        (call,) = route.calls
        assert call.request.headers["X-API-Key"] == KEY
        body = json.loads(call.request.content)
        assert body == {"status": "ok", "variables": VARIABLES}
        assert KEY not in call.request.content.decode()

    @respx.mock
    def test_an_alert_carries_its_fault(self) -> None:
        """status#28: a change of fault reports at once only when Status is told it."""
        route = respx.post(CHECKIN).mock(return_value=httpx.Response(202, json={}))
        post_checkin(BASE, MONITOR, KEY, "alert", VARIABLES, metadata={"fault": "lag"})
        body = json.loads(route.calls.last.request.content)
        assert body["metadata"] == {"fault": "lag"}

    @respx.mock
    def test_a_trailing_slash_on_the_base_is_harmless(self) -> None:
        route = respx.post(CHECKIN).mock(return_value=httpx.Response(202, json={}))
        post_checkin(f"{BASE}/", MONITOR, KEY, "ok", VARIABLES)
        assert route.called

    @pytest.mark.parametrize(
        ("code", "body", "reason"),
        [
            (401, {"detail": "invalid API key"}, "401 invalid API key"),
            (422, {"detail": [{"msg": "bad"}]}, "422 [{'msg': 'bad'}]"),
            (500, b"oops", "500"),
            (200, {}, "200"),
        ],
    )
    @respx.mock
    def test_anything_but_202_fails_naming_statuss_answer(self, code, body, reason) -> None:
        response = (
            httpx.Response(code, json=body) if isinstance(body, dict | list)
            else httpx.Response(code, content=body)
        )  # fmt: skip
        route = respx.post(CHECKIN).mock(return_value=response)
        with pytest.raises(CheckinFailed) as caught:
            post_checkin(BASE, MONITOR, KEY, "ok", VARIABLES)
        assert str(caught.value) == reason
        assert route.call_count == 1, "one attempt, never a loop"

    @respx.mock
    def test_unreachable_fails_by_type_never_naming_the_key(self) -> None:
        respx.post(CHECKIN).mock(side_effect=httpx.ConnectError("connection refused"))
        with pytest.raises(CheckinFailed, match="^ConnectError: connection refused$") as caught:
            post_checkin(BASE, MONITOR, KEY, "ok", VARIABLES)
        assert KEY not in str(caught.value)

    @pytest.mark.parametrize("key", [f"{KEY}\n{KEY}", f"{KEY} x", "", "é" * 8])
    @respx.mock
    def test_a_malformed_key_is_refused_before_any_request(self, key) -> None:
        """A bad paste must not reach httpx, whose header errors can quote the value."""
        route = respx.post(CHECKIN).mock(return_value=httpx.Response(202, json={}))
        with pytest.raises(CheckinFailed) as caught:
            post_checkin(BASE, MONITOR, key, "ok", VARIABLES)
        assert not route.called
        assert CREDENTIAL_NAME in str(caught.value)
        assert KEY not in str(caught.value)
