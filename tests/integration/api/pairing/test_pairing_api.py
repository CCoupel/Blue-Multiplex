"""api — appairages, appareils, erreurs (contracts/http-endpoints.md + models.md).

Cible `mock` aujourd'hui ; la meme suite vise l'application reelle (BTMUX_API_TARGET=real) des
que le
harnais FakeBluez de T2.3 existe. Les scenarios (stale-bond, bluez-down...) sont ceux du mock.
"""

from __future__ import annotations

import re

import pytest
from apisupport import wait_for

MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
HP = {"adapter": "headsets", "duration": 120}


def _open_headsets_and_discover(c, expected=2):
    c.call("POST", "/api/pairing", HP)
    assert wait_for(lambda: len(c.call("GET", "/api/discovered")[1]) == expected)


# --- modeles --------------------------------------------------------------------------------
def test_state_matches_models_contract(api):
    status, st = api.call("GET", "/api/state")
    assert status == 200
    assert set(st) == {"version", "adapters", "devices", "pairing"}
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


def test_empty_scenario_lists_no_device(api_factory):
    assert api_factory("empty").call("GET", "/api/state")[1]["devices"] == []


# --- fenetre d'appairage --------------------------------------------------------------------
def test_open_window_returns_202_and_model(api):
    status, w = api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    assert status == 202
    assert set(w) == {"adapter", "opened_at", "expires_at", "remaining_s"}
    assert 0 < w["remaining_s"] <= 60
    _, st = api.call("GET", "/api/state")
    assert st["pairing"]["adapter"] == "sources"
    assert next(a for a in st["adapters"] if a["role"] == "sources")["discoverable"] is True


def test_default_duration_is_accepted_without_field(api):
    assert api.call("POST", "/api/pairing", {"adapter": "sources"})[0] == 202


def test_second_window_is_409(api):
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    status, body = api.call("POST", "/api/pairing", HP)
    assert status == 409 and "error" in body


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
def test_open_window_validation_400(api, body):
    assert api.call("POST", "/api/pairing", body)[0] == 400


@pytest.mark.parametrize("duration", [1, 300])
def test_open_window_duration_bounds_accepted(api, duration):
    assert api.call("POST", "/api/pairing", {"adapter": "sources", "duration": duration})[0] == 202


def test_close_window_204_and_adapter_no_longer_discoverable(api):
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    assert api.call("DELETE", "/api/pairing")[0] == 204
    _, st = api.call("GET", "/api/state")
    assert st["pairing"] is None
    assert all(a["discoverable"] is False for a in st["adapters"])


def test_window_expires_by_itself(api_factory):
    c = api_factory("default", time_scale=50.0)
    c.call("POST", "/api/pairing", {"adapter": "sources", "duration": 5})
    assert wait_for(lambda: c.call("GET", "/api/state")[1]["pairing"] is None)


# --- casques : decouverte et appairage initie par le Pi -------------------------------------
def test_headset_window_exposes_discovered_devices(api):
    _open_headsets_and_discover(api)
    d = api.call("GET", "/api/discovered")[1][0]
    assert set(d) == {"mac", "adapter", "name", "rssi", "class"} and d["adapter"] == "headsets"


def test_sources_window_does_not_discover_anything(api):
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    assert api.call("GET", "/api/discovered")[1] == []


def test_pair_headset_initiated_by_the_pi(api):
    _open_headsets_and_discover(api)
    mac = api.call("GET", "/api/discovered")[1][0]["mac"]
    assert api.call("POST", f"/api/devices/{mac}/pair")[0] == 202
    assert wait_for(
        lambda: any(
            d["mac"] == mac and d["paired"] and d["trusted"] and d["connected"]
            for d in api.call("GET", "/api/state")[1]["devices"]
        )
    )


def test_pair_unknown_device_404(api):
    api.call("POST", "/api/pairing", HP)
    assert api.call("POST", "/api/devices/AA:00:00:00:00:99/pair")[0] == 404


def test_pair_with_window_closed_409(api):
    assert api.call("POST", "/api/devices/AA:11:22:33:44:55/pair")[0] == 409


def test_pair_with_sources_window_open_409(api):
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    assert api.call("POST", "/api/devices/AA:11:22:33:44:55/pair")[0] == 409


def test_stale_bond_is_409_with_hint(api_factory):
    c = api_factory("stale-bond")
    _open_headsets_and_discover(c)
    status, body = c.call("POST", "/api/devices/AA:11:22:33:44:66/pair")
    assert status == 409 and "message" in body


def test_stale_bond_cleared_by_forget_then_pair_succeeds(api_factory):
    c = api_factory("stale-bond")
    _open_headsets_and_discover(c)
    assert c.call("POST", "/api/devices/AA:11:22:33:44:66/pair")[0] == 409
    c.call("POST", "/__mock__/fail", {"stale_bond_macs": []}, token=None)
    assert c.call("POST", "/api/devices/AA:11:22:33:44:66/pair")[0] == 202


def test_bluez_error_is_502_with_dbus_message(api_factory):
    c = api_factory("bluez-error")
    _open_headsets_and_discover(c)
    status, body = c.call("POST", "/api/devices/AA:11:22:33:44:55/pair")
    assert status == 502 and "org.bluez" in body["message"]


def test_bluez_down_is_503_but_health_stays_200(api_factory):
    c = api_factory("bluez-down")
    assert c.call("GET", "/api/state")[0] == 503
    assert c.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})[0] == 503
    assert c.call("GET", "/api/health", token=None)[0] == 200


# --- actions sur appareils ------------------------------------------------------------------
def _dev(c, mac):
    return next(d for d in c.call("GET", "/api/state")[1]["devices"] if d["mac"] == mac)


def test_connect_then_disconnect(api):
    mac = "11:22:33:44:55:02"
    assert api.call("POST", f"/api/devices/{mac}/connect")[0] == 202
    assert wait_for(lambda: _dev(api, mac)["connected"])
    assert api.call("POST", f"/api/devices/{mac}/disconnect")[0] == 202
    assert wait_for(lambda: not _dev(api, mac)["connected"])


def test_forget_known_in_config_device_keeps_it_listed_unpaired(api):
    mac = "11:22:33:44:55:02"
    assert api.call("POST", f"/api/devices/{mac}/forget")[0] == 204
    assert _dev(api, mac)["paired"] is False


@pytest.mark.parametrize("action", ["connect", "disconnect", "forget"])
def test_actions_on_unknown_device_404(api, action):
    assert api.call("POST", f"/api/devices/AA:00:00:00:00:99/{action}")[0] == 404


def test_invalid_mac_400(api):
    assert api.call("POST", "/api/devices/not-a-mac/connect")[0] == 400


def test_mac_is_case_insensitive_in_path(api):
    assert api.call("POST", "/api/devices/11:22:33:44:55:02/connect")[0] == 202
    assert api.call("POST", "/api/devices/11:22:33:44:55:02/connect".lower())[0] == 202


def test_patch_trusted_and_alias(api):
    status, d = api.call(
        "PATCH", "/api/devices/11:22:33:44:55:02", {"trusted": False, "alias": "tel"}
    )
    assert status == 200 and d["trusted"] is False and d["alias"] == "tel"


@pytest.mark.parametrize(
    "body", [{}, {"trusted": "yes"}, {"alias": "Bad Alias"}, {"alias": ""}, {"x": 1}]
)
def test_patch_validation_400(api, body):
    assert api.call("PATCH", "/api/devices/11:22:33:44:55:02", body)[0] == 400


def test_patch_unknown_device_404(api):
    assert api.call("PATCH", "/api/devices/AA:00:00:00:00:99", {"trusted": True})[0] == 404


def test_unknown_route_404_json(api):
    status, body = api.call("GET", "/api/nope")
    assert status == 404 and "error" in body


def test_invalid_json_body_400(api):
    import http.client

    host, port = api.api.httpd.server_address[:2]
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("POST", "/api/pairing", "{oops", {"Authorization": "Bearer t0k3n"})
    r = conn.getresponse()
    r.read()
    conn.close()
    assert r.status == 400
