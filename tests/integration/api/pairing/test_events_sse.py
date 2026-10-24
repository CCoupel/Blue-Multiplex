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
