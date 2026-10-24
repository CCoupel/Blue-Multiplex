from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from fakes import HEADSET_MAC, HP_PATH, PHONE_MAC, SRC_PATH, FakeBus

from btmux.api.auth import check_bearer, load_token
from btmux.api.routes import HUB
from btmux.api.server import ApiServer, ApiStartError, create_app, parse_listen
from btmux.api.sse import EventHub, format_event
from btmux.bluez.bus import DBusCallError
from btmux.bluez.daemon import BluezService
from btmux.config import Config

TOKEN = "s3cr3t-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class Api:
    def __init__(self, client: TestClient[Any, Any], service: BluezService, bus: FakeBus) -> None:
        self.c, self.service, self.bus = client, service, bus
        self.hub: EventHub

    async def req(self, method: str, path: str, auth: bool = True, **kw: Any) -> tuple[int, Any]:
        headers = {**(AUTH if auth else {}), **kw.pop("headers", {})}
        resp = await self.c.request(method, path, headers=headers, **kw)
        text = await resp.text()
        return resp.status, (json.loads(text) if text else None)


@pytest.fixture(name="api")
def api_sync(service: BluezService, bus: FakeBus) -> Any:
    return _AsyncCtx(service, bus)


class _AsyncCtx:
    """Fixture synchrone : l'entrée/sortie async se fait dans le test via `async with api:`."""

    def __init__(self, service: BluezService, bus: FakeBus) -> None:
        self.service, self.bus = service, bus

    async def __aenter__(self) -> Api:
        await self.service._start_once()
        self.service.ready.set()
        app = create_app(self.service, TOKEN, static=Path("/nonexistent"))
        self.hub: EventHub = app[HUB]
        self.hub.start()
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        api = Api(self.client, self.service, self.bus)
        api.hub = self.hub
        return api

    async def __aexit__(self, *exc: object) -> None:
        await self.client.close()
        await self.hub.stop()


async def test_auth_and_public_routes(api: _AsyncCtx) -> None:
    async with api as a:
        assert (await a.req("GET", "/api/health", auth=False))[0] == 200
        assert (await a.req("GET", "/api/state", auth=False))[0] == 401
        status, body = await a.req("GET", "/api/state", headers={"Authorization": "Bearer nope"})
        assert status == 401 and body["error"] == "unauthorized"
        assert (await a.req("GET", "/api/state", headers={"Authorization": "Basic abc"}))[0] == 401
        status, body = await a.req("GET", "/api/health", auth=False)
        assert body["adapters"] == 2 and body["version"]
        resp = await a.c.get("/api/state", headers=AUTH)
        assert resp.headers["Cache-Control"] == "no-store"
        assert (await a.req("GET", "/api/nothing"))[0] == 404
        assert (await a.req("PUT", "/api/state"))[0] == 405
        status, body = await a.req("GET", "/api/nothing", auth=False)
        assert status == 401  # même les routes inconnues exigent le jeton


async def test_locked_api_without_token(service: BluezService) -> None:
    await service._start_once()
    service.ready.set()
    app = create_app(service, None, static=Path("/nonexistent"))
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/api/health")).status == 200
        assert (await client.get("/api/state", headers=AUTH)).status == 401
        assert (await client.get("/api/state", headers={"Authorization": "Bearer "})).status == 401


async def test_state_discovered_and_503_when_bluez_down(api: _AsyncCtx) -> None:
    async with api as a:
        status, body = await a.req("GET", "/api/state")
        assert status == 200 and set(body) == {"version", "adapters", "devices", "pairing"}
        assert (await a.req("GET", "/api/discovered"))[1] == []
        a.service.ready.clear()
        status, body = await a.req("GET", "/api/state")
        assert (status, body["error"]) == (503, "bluez_unavailable")
        assert (await a.req("GET", "/api/health", auth=False))[0] == 200


async def test_pairing_lifecycle_and_validation(api: _AsyncCtx) -> None:
    async with api as a:
        for bad in (
            {},
            {"adapter": "x"},
            {"adapter": "sources", "duration": 0},
            {"adapter": "sources", "duration": 301},
            {"adapter": "sources", "duration": "9"},
        ):
            assert (await a.req("POST", "/api/pairing", json=bad))[0] == 400
        assert (await a.req("POST", "/api/pairing", data=b"{oops"))[0] == 400
        assert (await a.req("POST", "/api/pairing", data=b"[1]"))[0] == 400
        status, win = await a.req(
            "POST", "/api/pairing", json={"adapter": "sources", "duration": 60}
        )
        assert status == 202 and win["adapter"] == "sources"
        status, body = await a.req("POST", "/api/pairing", json={"adapter": "headsets"})
        assert (status, body["error"]) == (409, "pairing_open")
        assert (await a.req("GET", "/api/state"))[1]["pairing"]["adapter"] == "sources"
        assert (await a.req("DELETE", "/api/pairing"))[0] == 204
        assert (await a.req("DELETE", "/api/pairing"))[0] == 204  # idempotent
        assert (await a.req("GET", "/api/state"))[1]["pairing"]["open"] is False
        assert (await a.req("POST", "/api/pairing", json={"adapter": "sources"}))[
            0
        ] == 202  # défaut


async def test_device_actions_and_errors(api: _AsyncCtx) -> None:
    async with api as a:
        a.bus.add_device(HP_PATH, HEADSET_MAC, name="Bose", Paired=True)
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True)
        status, dev = await a.req("POST", f"/api/devices/{HEADSET_MAC}/connect")
        assert status == 202 and dev["mac"] == HEADSET_MAC
        assert (await a.req("POST", f"/api/devices/{HEADSET_MAC}/disconnect"))[0] == 202
        assert (await a.req("POST", f"/api/devices/{HEADSET_MAC.lower()}/forget"))[0] == 204
        status, body = await a.req("POST", "/api/devices/00:00:00:00:00:09/connect")
        assert (status, body["error"]) == (404, "unknown_device")
        assert (await a.req("POST", "/api/devices/zz/connect"))[1]["error"] == "invalid_mac"
        a.bus.errors[("org.bluez.Device1", "Connect")] = DBusCallError(
            "org.bluez.Error.AuthenticationFailed"
        )
        status, body = await a.req("POST", f"/api/devices/{PHONE_MAC}/connect")
        assert (status, body["error"]) == (409, "stale_bond")
        a.bus.errors[("org.bluez.Device1", "Connect")] = DBusCallError(
            "org.bluez.Error.Failed", "x"
        )
        assert (await a.req("POST", f"/api/devices/{PHONE_MAC}/connect"))[0] == 502


async def test_mac_url_encoded_or_literal(api: _AsyncCtx) -> None:
    async with api as a:
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True)
        encoded = PHONE_MAC.replace(":", "%3A")
        assert (await a.req("POST", f"/api/devices/{encoded}/connect"))[0] == 202
        assert (await a.req("POST", f"/api/devices/{PHONE_MAC}/disconnect"))[0] == 202
        status, dev = await a.req(
            "PATCH", f"/api/devices/{encoded.lower()}", json={"trusted": True}
        )
        assert status == 200 and dev["mac"] == PHONE_MAC


async def test_pair_endpoint(api: _AsyncCtx) -> None:
    async with api as a:
        status, body = await a.req("POST", f"/api/devices/{HEADSET_MAC}/pair")
        assert (status, body["error"]) == (409, "pairing_closed")
        await a.req("POST", "/api/pairing", json={"adapter": "headsets", "duration": 30})
        status, body = await a.req("POST", f"/api/devices/{HEADSET_MAC}/pair")
        assert (status, body["error"]) == (404, "not_discovered")
        a.bus.add_device(HP_PATH, HEADSET_MAC, name="Bose", Class=0x240404, RSSI=-50)
        status, found = await a.req("GET", "/api/discovered")
        assert found[0]["mac"] == HEADSET_MAC and found[0]["adapter"] == "headsets"
        status, dev = await a.req("POST", f"/api/devices/{HEADSET_MAC}/pair")
        assert status == 202 and dev["in_config"] is True


async def test_patch_device(api: _AsyncCtx) -> None:
    async with api as a:
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True)
        status, dev = await a.req(
            "PATCH", f"/api/devices/{PHONE_MAC}", json={"trusted": True, "alias": "bureau"}
        )
        assert status == 200 and dev["alias"] == "bureau" and dev["trusted"] is True
        for bad in ({}, {"trusted": "yes"}, {"alias": "Bad Alias"}, {"x": 1}):
            assert (await a.req("PATCH", f"/api/devices/{PHONE_MAC}", json=bad))[0] == 400
        assert (await a.req("PATCH", "/api/devices/00:00:00:00:00:09", json={"trusted": True}))[
            0
        ] == 404


async def test_sse_stream_events_keepalive_and_replay(api: _AsyncCtx) -> None:
    async with api as a:
        a.hub.keepalive = 0.2
        resp = await a.c.get("/api/events", headers=AUTH)
        assert resp.status == 200 and resp.headers["Content-Type"].startswith("text/event-stream")
        assert await resp.content.readline() == b"retry: 3000\n"
        await resp.content.readline()
        await a.req("POST", "/api/pairing", json={"adapter": "sources", "duration": 30})
        text = ""
        while "event: pairing" not in text:
            text += (await asyncio.wait_for(resp.content.readline(), 3)).decode()
        assert "event: adapter" in text or "id: " in text
        ping = b""
        while b": ping" not in ping:
            ping = await asyncio.wait_for(resp.content.readline(), 3)
        resp.close()
        # reprise : Last-Event-ID récent → évènements manqués rejoués
        last = a.hub.latest_id
        await a.req("DELETE", "/api/pairing")
        resp2 = await a.c.get("/api/events", headers={**AUTH, "Last-Event-ID": str(last)})
        seen = ""
        while "event: pairing" not in seen:
            seen += (await asyncio.wait_for(resp2.content.readline(), 3)).decode()
        assert '"open":false' in seen or "event: adapter" in seen
        resp2.close()
        # id périmé ou futur → évènement `state` complet
        for stale in ("99999", "0"):
            for _ in range(120):
                a.service.inventory.emit("adapter", {})
            r = await a.c.get("/api/events", headers={**AUTH, "Last-Event-ID": stale})
            data = ""
            while "event: state" not in data:
                data += (await asyncio.wait_for(r.content.readline(), 3)).decode()
            r.close()


def test_sse_helpers() -> None:
    assert format_event(3, "x", {"a": 1}) == b'event: x\nid: 3\ndata: {"a":1}\n\n'


async def test_hub_missed_since(service: BluezService) -> None:
    await service._start_once()
    hub = EventHub(service.inventory)
    base = service.inventory.last_event_id
    assert hub.missed_since(base) == [] and hub.missed_since(base + 5) is None
    hub.start()
    for _ in range(3):
        service.inventory.emit("adapter", {})
    await asyncio.sleep(0.05)
    first = hub._buffer[0].id
    assert [e.id for e in hub.missed_since(first) or []] == [first + 1, first + 2]
    assert hub.missed_since(hub.latest_id + 1) is None
    await hub.stop()


def test_check_bearer_and_listen_and_token(tmp_path: Path) -> None:
    assert check_bearer(f"Bearer {TOKEN}", TOKEN) and check_bearer(f"bearer {TOKEN}", TOKEN)
    assert not check_bearer(None, TOKEN) and not check_bearer("Bearer x", TOKEN)
    assert not check_bearer(f"Bearer {TOKEN}", None) and not check_bearer("Bearer", TOKEN)
    assert parse_listen("0.0.0.0:8088") == ("0.0.0.0", 8088)
    assert parse_listen("127.0.0.1:0") == ("127.0.0.1", 0)
    assert parse_listen("[::1]:80") == ("::1", 80)
    for bad in ("8088", "host:x", "h:70000", ""):
        with pytest.raises(ApiStartError):
            parse_listen(bad)
    f = tmp_path / "token"
    assert load_token(f) is None  # absent
    f.write_text("  \n")
    assert load_token(f) is None  # vide
    f.write_text(TOKEN + "\n")
    f.chmod(0o644)
    assert load_token(f) is None  # lisible par les autres : API verrouillée
    f.chmod(0o600)
    assert load_token(f) == TOKEN


async def test_api_server_lifecycle(config: Config, bus: FakeBus, tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text(TOKEN)
    token.chmod(0o600)
    cfg = config.model_copy(
        update={"api": config.api.model_copy(update={"listen": "127.0.0.1:0", "token_file": token})}
    )
    service = BluezService(cfg, bus, adapter_wait=0.5, retry_interval=0.02)
    await service._start_once()
    service.ready.set()
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>btmux</h1>")
    async with ApiServer(service, static=static) as server:
        import urllib.request

        def fetch(path: str, headers: dict[str, str] | None = None) -> tuple[int, bytes, Any]:
            req = urllib.request.Request(
                f"http://127.0.0.1:{server.port}{path}", headers=headers or {}
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, r.read(), r.headers
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read(), exc.headers

        loop = asyncio.get_running_loop()
        status, body, headers = await loop.run_in_executor(None, fetch, "/")
        assert status == 200 and b"btmux" in body and headers["Cache-Control"] == "no-store"
        status, body, headers = await loop.run_in_executor(None, fetch, "/static/index.html")
        assert status == 200
        assert (await loop.run_in_executor(None, fetch, "/static/missing.js"))[0] == 404
        assert (await loop.run_in_executor(None, fetch, "/api/state"))[0] == 401
        status, body, _ = await loop.run_in_executor(None, fetch, "/api/state", AUTH)
        assert status == 200 and json.loads(body)["version"]
        # port déjà occupé → ApiStartError
        busy = service.config.model_copy(
            update={"api": cfg.api.model_copy(update={"listen": f"127.0.0.1:{server.port}"})}
        )
        service.config = busy
        with pytest.raises(ApiStartError, match="cannot listen"):
            async with ApiServer(service):
                pass


async def test_root_without_index_is_404(service: BluezService, tmp_path: Path) -> None:
    await service._start_once()
    static = tmp_path / "empty"
    static.mkdir()
    async with TestClient(TestServer(create_app(service, TOKEN, static=static))) as client:
        assert (await client.get("/")).status == 404
    assert os.path.isdir(static)
