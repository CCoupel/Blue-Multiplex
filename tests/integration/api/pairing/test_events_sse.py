"""api — flux SSE `/api/events` (contracts/http-endpoints.md) : format, auth, evenements."""

from __future__ import annotations

import http.client
import json
import re

from apisupport import TOKEN


def test_sse_requires_auth(api):
    assert api.sse(0, headers={})[0] == 401


def test_sse_headers_and_retry(api):
    conn = api._conn(5)
    conn.request("GET", "/api/events", headers={"Authorization": f"Bearer {TOKEN}"})
    resp = conn.getresponse()
    assert resp.status == 200
    assert resp.getheader("Content-Type").startswith("text/event-stream")
    assert resp.fp.readline().decode() == "retry: 3000\n"
    conn.close()


def test_sse_pairing_event_carries_full_model_and_counter_id(api):
    _, lines = api.sse(
        2, trigger=lambda: api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    )
    text = "".join(lines)
    assert "event: adapter" in text and "event: pairing" in text
    data = next(json.loads(x[6:]) for x in lines if x.startswith("data:") and "expires_at" in x)
    assert data["adapter"] == "sources"
    assert re.search(r"^id: \d+$", text, re.M)


def test_sse_device_event_on_connect(api):
    _, lines = api.sse(
        1, trigger=lambda: api.call("POST", "/api/devices/11:22:33:44:55:02/connect")
    )
    text = "".join(lines)
    assert "event: device" in text and '"connected": true' in text


def test_sse_discovered_event_for_headsets(api):
    _, lines = api.sse(
        3, trigger=lambda: api.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 60})
    )
    assert "event: discovered" in "".join(lines)


def test_sse_event_ids_increase(api):
    _, lines = api.sse(
        3, trigger=lambda: api.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 60})
    )
    ids = [int(x.split(":")[1]) for x in lines if x.startswith("id:")]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_sse_clients_do_not_block_regular_requests(api):
    conn = api._conn(5)
    conn.request("GET", "/api/events", headers={"Authorization": f"Bearer {TOKEN}"})
    assert conn.getresponse().status == 200
    assert api.call("GET", "/api/state")[0] == 200  # le flux ouvert ne bloque pas l'API
    conn.close()


def test_sse_authenticates_with_header(api):
    conn = http.client.HTTPConnection(*api.api.httpd.server_address[:2], timeout=5)
    conn.request("GET", "/api/events", headers={"Authorization": "Bearer bad"})
    r = conn.getresponse()
    r.read()
    conn.close()
    assert r.status == 401


def test_sse_pairing_closed_event_is_an_explicit_object_never_null(api):
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    _, lines = api.sse(2, trigger=lambda: api.call("DELETE", "/api/pairing"))
    data = next(json.loads(x[6:]) for x in lines if x.startswith("data:") and '"reason"' in x)
    assert data["open"] is False and data["reason"] == "closed" and data["adapter"] == "sources"


def test_sse_forget_emits_device_removed_then_placeholder_for_config_devices(api):
    _, lines = api.sse(2, trigger=lambda: api.call("POST", "/api/devices/11:22:33:44:55:02/forget"))
    text = "".join(lines)
    assert text.index("event: device.removed") < text.index("event: device\n")
    removed = next(json.loads(x[6:]) for x in lines if x.startswith("data:") and '"adapter"' in x)
    assert removed == {"mac": "11:22:33:44:55:02", "adapter": "sources"}
    assert '"paired": false' in text and '"in_config": true' in text


def test_sse_forget_of_non_config_device_emits_only_device_removed(api):
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    api.call("POST", "/__mock__/incoming", {"mac": "BB:00:00:00:00:01", "name": "x"}, token=None)
    _, lines = api.sse(1, trigger=lambda: api.call("POST", "/api/devices/BB:00:00:00:00:01/forget"))
    assert "event: device.removed" in "".join(lines)


def test_sse_first_event_of_a_connection_is_a_full_state(api):
    _, lines = api.sse(1, keep_state=True)
    assert lines[0].startswith("event: state")
    data = next(json.loads(x[6:]) for x in lines if x.startswith("data:"))
    assert set(data) >= {"version", "adapters", "devices", "pairing"}


def test_sse_last_event_id_replays_missed_events(api):
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})  # ids 1 (adapter), 2
    _, lines = api.sse(
        1, headers={"Authorization": "Bearer t0k3n", "Last-Event-ID": "1"}, keep_state=True
    )
    text = "".join(lines)
    assert "event: pairing" in text and "event: state" not in text


def test_sse_unknown_last_event_id_sends_a_full_state_event(api):
    _, lines = api.sse(
        1, headers={"Authorization": "Bearer t0k3n", "Last-Event-ID": "9999"}, keep_state=True
    )
    text = "".join(lines)
    assert "event: state" in text
    data = next(json.loads(x[6:]) for x in lines if x.startswith("data:"))
    assert set(data) >= {"version", "adapters", "devices", "pairing"}
