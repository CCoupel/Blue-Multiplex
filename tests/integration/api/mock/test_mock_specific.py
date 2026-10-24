"""Mock API — fonctions propres au mock (hors contrat) : pilotage /__mock__, statique, scenarios."""

from __future__ import annotations

from pathlib import Path

from apisupport import mock_mod


def test_incoming_pairing_only_during_sources_window(api):
    inc = {"mac": "BB:00:00:00:00:01", "name": "PC visiteur"}
    assert api.call("POST", "/__mock__/incoming", inc, token=None)[0] == 409
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    assert api.call("POST", "/__mock__/incoming", inc, token=None)[0] == 200
    assert "BB:00:00:00:00:01" in [d["mac"] for d in api.call("GET", "/api/state")[1]["devices"]]


def test_incoming_pairing_with_headsets_window_is_refused(api):
    api.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 60})
    assert (
        api.call("POST", "/__mock__/incoming", {"mac": "BB:00:00:00:00:02"}, token=None)[0] == 409
    )


def test_window_open_scenario_has_remaining_seconds(api_factory):
    w = api_factory("window-open", time_scale=1.0).call("GET", "/api/state")[1]["pairing"]
    assert w["open"] is True and w["adapter"] == "sources" and 0 < w["remaining_s"] <= 42


def test_reset_reloads_a_scenario(api):
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    assert api.call("POST", "/__mock__/reset?scenario=empty", token=None)[0] == 200
    st = api.call("GET", "/api/state")[1]
    assert st["devices"] == [] and st["pairing"]["open"] is False


def test_fail_endpoint_switches_bluez_down_on_the_fly(api):
    api.call("POST", "/__mock__/fail", {"bluez_unavailable": True}, token=None)
    assert api.call("GET", "/api/state")[0] == 503
    api.call("POST", "/__mock__/fail", {"bluez_unavailable": False}, token=None)
    assert api.call("GET", "/api/state")[0] == 200


def test_event_injection_reaches_sse_clients(api):
    _, lines = api.sse(
        1,
        trigger=lambda: api.call(
            "POST",
            "/__mock__/event",
            {"event": "pairing", "data": {"open": False, "reason": "closed"}},
            token=None,
        ),
    )
    assert "event: pairing" in "".join(lines) and '"open": false' in "".join(lines)


def test_static_dir_is_public_and_confined(tmp_path: Path):
    import http.client

    (tmp_path / "index.html").write_text("<h1>ok</h1>")
    (tmp_path.parent / "secret.txt").write_text("x")
    api = mock_mod.MockApi("default", token="t", static_dir=tmp_path).start()
    try:
        conn = http.client.HTTPConnection(*api.httpd.server_address[:2], timeout=5)
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


def test_query_token_is_never_accepted(api):
    """Comme l'application reelle : seul l'en-tete Authorization (le front lit le SSE par fetch)."""
    assert api.call("GET", "/api/state?token=t0k3n", token=None)[0] == 401
    assert api.sse(0, headers={}, path="/api/events?token=t0k3n")[0] == 401


def test_discovered_headset_disappearing_emits_device_removed(api):
    api.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 60})
    from apisupport import wait_for

    assert wait_for(lambda: len(api.call("GET", "/api/discovered")[1]) == 2)
    mac = api.call("GET", "/api/discovered")[1][0]["mac"]
    _, lines = api.sse(
        1, trigger=lambda: api.call("POST", "/__mock__/discovered-gone", {"mac": mac}, token=None)
    )
    assert "event: device.removed" in "".join(lines) and mac in "".join(lines)
    assert mac not in [d["mac"] for d in api.call("GET", "/api/discovered")[1]]


def test_static_serves_only_html_js_css(tmp_path):
    import http.client

    for name in ("index.html", "app.js", "style.css", "README.md", "api.test.mjs"):
        (tmp_path / name).write_text("x")
    srv = mock_mod.MockApi("default", token="t", static_dir=tmp_path).start()
    try:
        conn = http.client.HTTPConnection(*srv.httpd.server_address[:2], timeout=5)
        codes = {}
        for name in ("app.js", "style.css", "README.md", "api.test.mjs"):
            conn.request("GET", f"/static/{name}")
            r = conn.getresponse()
            r.read()
            codes[name] = r.status
        conn.close()
    finally:
        srv.stop()
    assert codes == {"app.js": 200, "style.css": 200, "README.md": 404, "api.test.mjs": 404}
