"""api — le mock `tests/fixtures/api-mock/` respecte contracts/http-endpoints.md + models.md.

Garantit que dev-frontend (#16) developpe contre un comportement conforme au contrat.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import re
import time
from pathlib import Path

import pytest
from specsupport import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "btmux_api_mock", REPO_ROOT / "tests" / "fixtures" / "api-mock" / "server.py"
)
mock_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock_mod)  # type: ignore[union-attr]

TOKEN = "t0k3n"
MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


class Client:
    def __init__(self, api, token: str | None = TOKEN):
        self.api, self.token = api, token

    def call(self, method, path, body=None, token="default"):
        host, port = self.api.httpd.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=10)
        headers = {}
        tok = self.token if token == "default" else token
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        data = None
        if body is not None:
            data = json.dumps(body)
            headers["Content-Type"] = "application/json"
        conn.request(method, path, data, headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, (json.loads(raw) if raw else None)


def make(scenario="default", **kw):
    api = mock_mod.MockApi(scenario, token=TOKEN, time_scale=kw.pop("time_scale", 20.0)).start()
    return api, Client(api)


@pytest.fixture
def mock():
    api, client = make()
    yield client
    api.stop()


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


# --- auth -----------------------------------------------------------------------------------
@pytest.mark.parametrize("route", ["/api/state", "/api/discovered"])
def test_api_requires_bearer_token(mock, route):
    status, body = mock.call("GET", route, token=None)
    assert status == 401 and set(body) >= {"error", "message"}


def test_wrong_token_is_rejected(mock):
    assert mock.call("GET", "/api/state", token="nope")[0] == 401


def test_health_is_public(mock):
    status, body = mock.call("GET", "/api/health", token=None)
    assert status == 200 and body == {"version": "0.2.0.0", "adapters": 2}


# --- modeles --------------------------------------------------------------------------------
def test_state_matches_models_contract(mock):
    status, st = mock.call("GET", "/api/state")
    assert status == 200 and set(st) == {"version", "adapters", "devices", "pairing"}
    assert {a["role"] for a in st["adapters"]} == {"sources", "headsets"}
    for a in st["adapters"]:
        assert set(a) == {
            "role",
            "mac",
            "alias",
            "hci",
            "powered",
            "discoverable",
            "pairable",
            "class",
        }
        assert MAC_RE.match(a["mac"])
    for d in st["devices"]:
        assert set(d) == {
            "mac",
            "adapter",
            "alias",
            "name",
            "kind",
            "paired",
            "trusted",
            "connected",
            "blocked",
            "uuids",
            "profiles",
            "last_seen",
            "in_config",
        }
        assert d["kind"] in {"source", "headset", "unknown"} and MAC_RE.match(d["mac"])
    assert st["pairing"] is None


# --- fenetre d'appairage --------------------------------------------------------------------
def test_open_window_returns_202_and_model(mock):
    status, w = mock.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    assert status == 202 and set(w) == {"adapter", "opened_at", "expires_at", "remaining_s"}
    assert 0 < w["remaining_s"] <= 60
    _, st = mock.call("GET", "/api/state")
    assert st["pairing"]["adapter"] == "sources"
    assert next(a for a in st["adapters"] if a["role"] == "sources")["discoverable"] is True


def test_second_window_is_409(mock):
    mock.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    status, body = mock.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 60})
    assert status == 409 and body["error"] == "pairing_open"


@pytest.mark.parametrize(
    "body",
    [
        {"adapter": "x", "duration": 60},
        {"adapter": "sources", "duration": 0},
        {"adapter": "sources", "duration": 301},
        {"adapter": "sources", "duration": "60"},
        {},
    ],
)
def test_open_window_validation_400(mock, body):
    assert mock.call("POST", "/api/pairing", body)[0] == 400


def test_close_window_204(mock):
    mock.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    assert mock.call("DELETE", "/api/pairing")[0] == 204
    assert mock.call("GET", "/api/state")[1]["pairing"] is None


def test_countdown_decreases_and_window_expires():
    api, c = make(time_scale=50.0)
    try:
        _, w = c.call("POST", "/api/pairing", {"adapter": "sources", "duration": 5})
        assert wait_for(lambda: c.call("GET", "/api/state")[1]["pairing"] is None)
    finally:
        api.stop()


def test_window_open_scenario_has_remaining_seconds():
    api, c = make("window-open", time_scale=1.0)
    try:
        w = c.call("GET", "/api/state")[1]["pairing"]
        assert w["adapter"] == "sources" and 0 < w["remaining_s"] <= 42
    finally:
        api.stop()


# --- casques : decouverte et appairage initie par le Pi -------------------------------------
def test_headset_discovery_then_pair_by_the_pi(mock):
    mock.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 120})
    assert wait_for(lambda: len(mock.call("GET", "/api/discovered")[1]) == 2)
    d = mock.call("GET", "/api/discovered")[1][0]
    assert set(d) == {"mac", "adapter", "name", "rssi", "class"}
    assert mock.call("POST", f"/api/devices/{d['mac']}/pair")[0] == 202
    assert wait_for(
        lambda: any(
            x["mac"] == d["mac"] and x["connected"]
            for x in mock.call("GET", "/api/state")[1]["devices"]
        )
    )


def test_pair_unknown_device_404(mock):
    mock.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 120})
    assert mock.call("POST", "/api/devices/AA:00:00:00:00:99/pair")[0] == 404


def test_pair_with_window_closed_409(mock):
    status, body = mock.call("POST", "/api/devices/AA:11:22:33:44:55/pair")
    assert status == 409 and body["error"] == "pairing_closed"


def test_stale_bond_is_409_until_forget():
    api, c = make("stale-bond")
    try:
        c.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 120})
        assert wait_for(lambda: len(c.call("GET", "/api/discovered")[1]) == 2)
        status, body = c.call("POST", "/api/devices/AA:11:22:33:44:66/pair")
        assert status == 409 and body["error"] == "stale_bond"
    finally:
        api.stop()


def test_bluez_error_is_502():
    api, c = make("bluez-error")
    try:
        c.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 120})
        assert wait_for(lambda: len(c.call("GET", "/api/discovered")[1]) == 2)
        assert c.call("POST", "/api/devices/AA:11:22:33:44:55/pair")[0] == 502
    finally:
        api.stop()


def test_bluez_down_is_503_but_health_stays_200():
    api, c = make("bluez-down")
    try:
        assert c.call("GET", "/api/state")[0] == 503
        assert c.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})[0] == 503
        assert c.call("GET", "/api/health", token=None)[0] == 200
    finally:
        api.stop()


# --- actions sur appareils ------------------------------------------------------------------
def test_connect_disconnect_forget(mock):
    mac = "11:22:33:44:55:02"
    assert mock.call("POST", f"/api/devices/{mac}/connect")[0] == 202

    def dev():
        return next(d for d in mock.call("GET", "/api/state")[1]["devices"] if d["mac"] == mac)

    assert wait_for(lambda: dev()["connected"])
    assert mock.call("POST", f"/api/devices/{mac}/disconnect")[0] == 202
    assert wait_for(lambda: not dev()["connected"])
    assert mock.call("POST", f"/api/devices/{mac}/forget")[0] == 204
    assert dev()["paired"] is False  # present dans la config : reste liste


def test_actions_on_unknown_device_404(mock):
    for action in ("connect", "disconnect", "forget"):
        assert mock.call("POST", f"/api/devices/AA:00:00:00:00:99/{action}")[0] == 404


def test_invalid_mac_400(mock):
    assert mock.call("POST", "/api/devices/not-a-mac/connect")[0] == 400


def test_patch_trusted_and_alias(mock):
    status, d = mock.call(
        "PATCH", "/api/devices/11:22:33:44:55:02", {"trusted": False, "alias": "tel"}
    )
    assert status == 200 and d["trusted"] is False and d["alias"] == "tel"


@pytest.mark.parametrize("body", [{}, {"trusted": "yes"}, {"alias": "Bad Alias"}, {"x": 1}])
def test_patch_validation_400(mock, body):
    assert mock.call("PATCH", "/api/devices/11:22:33:44:55:02", body)[0] == 400


def test_incoming_pairing_only_during_sources_window(mock):
    inc = {"mac": "BB:00:00:00:00:01", "name": "PC visiteur"}
    assert mock.call("POST", "/__mock__/incoming", inc, token=None)[0] == 409
    mock.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    assert mock.call("POST", "/__mock__/incoming", inc, token=None)[0] == 200
    macs = [d["mac"] for d in mock.call("GET", "/api/state")[1]["devices"]]
    assert "BB:00:00:00:00:01" in macs


# --- SSE ------------------------------------------------------------------------------------
def _sse_lines(api, n_events, path="/api/events", headers=None, trigger=None, timeout=8):
    host, port = api.httpd.server_address[:2]
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request(
        "GET",
        path,
        headers=headers if headers is not None else {"Authorization": f"Bearer {TOKEN}"},
    )
    resp = conn.getresponse()
    if resp.status != 200:
        conn.close()
        return resp.status, []
    out, events = [], 0
    if trigger:
        trigger()
    while events < n_events:
        line = resp.fp.readline().decode()
        out.append(line)
        if line == "\n" and any(x.startswith("event:") for x in out[-6:]):
            events += 1
    conn.close()
    return resp.status, out


def test_sse_requires_auth_and_announces_retry():
    api, c = make()
    try:
        assert _sse_lines(api, 0, headers={})[0] == 401
        host, port = api.httpd.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/events", headers={"Authorization": f"Bearer {TOKEN}"})
        resp = conn.getresponse()
        assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/event-stream")
        assert resp.fp.readline().decode() == "retry: 3000\n"
        conn.close()
    finally:
        api.stop()


def test_sse_emits_pairing_event_with_full_model():
    api, c = make()
    try:
        status, lines = _sse_lines(
            api,
            2,
            trigger=lambda: c.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60}),
        )
        text = "".join(lines)
        assert "event: adapter" in text and "event: pairing" in text
        data = next(json.loads(x[6:]) for x in lines if x.startswith("data:") and "expires_at" in x)
        assert data["adapter"] == "sources"
        assert re.search(r"^id: \d+$", text, re.M)
    finally:
        api.stop()


def test_sse_device_event_on_connect():
    api, c = make()
    try:
        _, lines = _sse_lines(
            api, 1, trigger=lambda: c.call("POST", "/api/devices/11:22:33:44:55:02/connect")
        )
        text = "".join(lines)
        assert "event: device" in text and '"connected": true' in text
    finally:
        api.stop()


# --- statique -------------------------------------------------------------------------------
def test_static_dir_is_public_and_confined(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>ok</h1>")
    (tmp_path.parent / "secret.txt").write_text("x")
    api = mock_mod.MockApi("default", token=TOKEN, static_dir=tmp_path).start()
    try:
        host, port = api.httpd.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/")
        r = conn.getresponse()
        assert r.status == 200 and b"ok" in r.read()
        conn.request("GET", "/static/../secret.txt")
        r = conn.getresponse()
        r.read()
        assert r.status == 404
        conn.close()
    finally:
        api.stop()
