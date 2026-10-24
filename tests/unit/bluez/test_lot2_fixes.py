"""Corrections revue/sécurité LOT-2 (#20 #21)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from fakes import HEADSET_MAC, HP_PATH, PHONE_MAC, SRC_PATH, FakeBus
from test_api import AUTH, TOKEN, _AsyncCtx, api_sync  # noqa: F401

from btmux.api.server import ApiServer, create_app
from btmux.bluez.bus import DBusCallError
from btmux.bluez.daemon import BluezService
from btmux.bluez.errors import BluezError, OperationInProgress
from btmux.config import Config, parse_config
from btmux.config.loader import ALIAS_RE, MAC_RE

ROOT = Path(__file__).resolve().parents[3]


async def started(service: BluezService) -> None:
    assert await service._start_once() == []


def api_config(config: Config, tmp_path: Path, listen: str = "127.0.0.1:0") -> Config:
    token = tmp_path / "token"
    token.write_text(TOKEN)
    token.chmod(0o600)
    return config.model_copy(
        update={"api": config.api.model_copy(update={"listen": listen, "token_file": token})}
    )


# ----- 1. arrêt rapide avec client SSE ouvert -----
async def test_shutdown_is_fast_with_open_sse_client(
    config: Config, bus: FakeBus, tmp_path: Path
) -> None:
    service = BluezService(api_config(config, tmp_path), bus, adapter_wait=0.5)
    await started(service)
    service.ready.set()
    server = ApiServer(service)
    await server.__aenter__()
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(
        f"GET /api/events HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\n\r\n".encode()
    )
    await writer.drain()
    await asyncio.wait_for(reader.readuntil(b"event: state"), 5)
    started_at = time.monotonic()
    await server.__aexit__(None, None, None)
    assert time.monotonic() - started_at < 5
    writer.close()


# ----- 2. en-têtes invalides -----
async def test_non_utf8_authorization_is_401_and_bad_last_event_id_gets_state(
    api: _AsyncCtx,
) -> None:
    async with api as a:
        resp = await a.c.get(
            "/api/state", headers={"Authorization": b"Bearer \xff\xfe".decode("latin-1")}
        )
        assert resp.status == 401
        for bad in ("²", "abc", "-1", "9" * 40, ""):
            r = await a.c.get("/api/events", headers={**AUTH, "Last-Event-ID": bad})
            assert r.status == 200
            data = ""
            while "event: state" not in data:
                data += (await asyncio.wait_for(r.content.readline(), 3)).decode()
            r.close()


async def test_raw_non_utf8_authorization_header_on_the_wire(
    config: Config, bus: FakeBus, tmp_path: Path
) -> None:
    service = BluezService(api_config(config, tmp_path), bus, adapter_wait=0.5)
    await started(service)
    service.ready.set()
    async with ApiServer(service) as server:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        writer.write(
            b"GET /api/state HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer \xff\xfe\r\n\r\n"
        )
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n"), 5)
        assert b"401" in head
        writer.close()


# ----- 3. état initial SSE et device.removed pour les découverts -----
async def test_sse_sends_initial_state_without_last_event_id(api: _AsyncCtx) -> None:
    async with api as a:
        r = await a.c.get("/api/events", headers=AUTH)
        text = ""
        while "event: state" not in text or not text.endswith("\n\n"):
            text += (await asyncio.wait_for(r.content.readline(), 3)).decode()
        payload = next(line for line in text.splitlines() if line.startswith("data:"))
        assert json.loads(payload[5:])["pairing"]["open"] is False
        r.close()


async def test_disappearing_discovered_device_emits_removed(service: BluezService, bus: FakeBus):
    await started(service)
    inv = service.inventory
    inv.set_discovery_collection(True)
    path = bus.add_device(HP_PATH, "BB:BB:BB:BB:BB:01", name="Bose", RSSI=-50)
    sub = inv.subscribe()
    bus.remove_device(path)
    event = sub.queue.get_nowait()
    assert event.kind == "device.removed" and event.data == {
        "mac": "BB:BB:BB:BB:BB:01",
        "adapter": "headsets",
    }
    assert inv.discovered() == []


# ----- 4/5. pair annulé, concurrent, Trusted -----
async def test_pair_survives_cancellation_and_blocks_concurrent_pair(
    service: BluezService, bus: FakeBus
) -> None:
    await started(service)
    path = bus.add_device(HP_PATH, HEADSET_MAC, name="Bose", Class=0x240404)
    release = asyncio.Event()

    async def slow_pair(p: str, body: list[Any]) -> list[Any]:
        await release.wait()
        bus.change(p, "org.bluez.Device1", Paired=True)
        return []

    bus.handlers[("org.bluez.Device1", "Pair")] = slow_pair
    await service.pairing.open("headsets", 30)
    first = asyncio.create_task(service.pairing.pair(HEADSET_MAC))
    await asyncio.sleep(0.05)
    with pytest.raises(OperationInProgress):
        await service.pairing.pair(HEADSET_MAC)
    first.cancel()  # le client HTTP s'en va
    await asyncio.sleep(0.05)
    assert service.pairing.allows(path)  # BlueZ poursuit : l'agent reste autorisé
    release.set()
    await asyncio.sleep(0.1)
    assert (
        not service.pairing.allows(path)
        and (path, "org.bluez.Device1", "Trusted", True) in bus.sets
    )
    assert bus.calls_to("Connect")
    await service.pairing.pair(HEADSET_MAC)  # de nouveau possible (déjà appairé)


async def test_pair_failure_in_background_is_reported_to_waiter(
    service: BluezService, bus: FakeBus
) -> None:
    await started(service)
    bus.add_device(HP_PATH, HEADSET_MAC, name="Bose", Paired=True)
    bus.set_errors[("org.bluez.Device1", "Trusted")] = DBusCallError("org.bluez.Error.Failed", "t")
    await service.pairing.open("headsets", 30)
    with pytest.raises(BluezError, match="Trusted"):
        await service.pairing.pair(HEADSET_MAC)


# ----- 6. regex -----
def test_regexes_reject_trailing_newline() -> None:
    assert MAC_RE.fullmatch("AA:BB:CC:DD:EE:FF") and not MAC_RE.fullmatch("AA:BB:CC:DD:EE:FF\n")
    assert ALIAS_RE.fullmatch("pc-pro") and not ALIAS_RE.fullmatch("pc-pro\n")
    with pytest.raises(Exception, match="mac"):
        parse_config(
            {
                "adapters": [
                    {"mac": "AA:BB:CC:00:00:01\n", "name": "a", "roles": ["sources", "headsets"]}
                ]
            }
        )
    with pytest.raises(Exception, match="alias"):
        parse_config(
            {
                "adapters": [
                    {"mac": "AA:BB:CC:00:00:01", "name": "a", "roles": ["sources", "headsets"]}
                ],
                "devices": [{"mac": "11:22:33:44:55:01", "alias": "pc\n", "kind": "source"}],
            }
        )


async def test_api_rejects_mac_and_alias_with_newline(api: _AsyncCtx) -> None:
    async with api as a:
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True)
        assert (await a.req("POST", f"/api/devices/{PHONE_MAC}%0A/connect"))[0] == 400
        assert (await a.req("PATCH", f"/api/devices/{PHONE_MAC}", json={"alias": "pc\n"}))[0] == 400


# ----- 8. PairableTimeout, atomicité, ExecStopPost -----
async def test_open_sets_pairable_timeout_and_rolls_back_on_failure(
    service: BluezService, bus: FakeBus
) -> None:
    await started(service)
    await service.pairing.open("sources", 42)
    assert (SRC_PATH, "org.bluez.Adapter1", "PairableTimeout", 42) in bus.sets
    await service.pairing.close()
    bus.set_errors[("org.bluez.Adapter1", "Discoverable")] = DBusCallError(
        "org.bluez.Error.Failed", "x"
    )
    bus.set_errors.pop(("org.bluez.Adapter1", "Pairable"), None)
    with pytest.raises(BluezError):
        await service.pairing.open("sources", 10)
    assert (
        bus.objects[SRC_PATH]["org.bluez.Adapter1"]["Pairable"] is False
    )  # pas de Pairable orphelin


async def test_start_failure_closes_bus(service: BluezService, bus: FakeBus) -> None:
    async def boom(*a: Any, **k: Any) -> Any:
        raise BluezError("x")

    bus.get_managed_objects = boom  # type: ignore[method-assign]
    with pytest.raises(BluezError):
        await service._start_once()
    assert bus.connected is False


def test_unit_has_exec_stop_post_and_reset_mode(tmp_path: Path) -> None:
    unit = (ROOT / "systemd" / "btmuxd.service").read_text()
    assert "ExecStopPost=-+/usr/lib/btmux/btmux-adapters.sh" in unit and "--reset" in unit
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        'adapters:\n  - {mac: "AA:BB:CC:00:00:01", name: btmux, roles: [sources, headsets]}\n'
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    (bindir / "btmgmt").write_text(
        '#!/bin/sh\nif [ "$1" = info ]; then\n'
        '  printf "hci0:\\tPrimary\\n\\taddr AA:BB:CC:00:00:01 v\\n"; exit 0; fi\n'
        f'echo "btmgmt $*" >> "{log}"\n'
    )
    (bindir / "sudo").write_text('#!/bin/sh\nshift\nexec "$@"\n')
    for f in bindir.iterdir():
        f.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "BTMUX_PYTHON": __import__("sys").executable,
    }
    proc = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "btmux-adapters.sh"),
            "--config",
            str(cfg),
            "--reset",
            "--wait",
            "0",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text()
    assert "bondable off" in calls and "discov no" in calls
    assert "class" not in calls and "power" not in calls  # pas de réidentification


# ----- 9/10. HTTP clair, en-têtes, jeton, statiques -----
async def test_cleartext_warning_only_when_not_loopback(
    config: Config, bus: FakeBus, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="btmux.api")
    for listen, expected in (("127.0.0.1:0", False), ("0.0.0.0:0", True)):
        caplog.clear()
        service = BluezService(api_config(config, tmp_path, listen), bus, adapter_wait=0.5)
        await started(service)
        service.ready.set()
        async with ApiServer(service):
            pass
        text = caplog.text
        assert ("api_listening_cleartext" in text) is expected
        assert TOKEN not in text


async def test_security_headers_and_filtered_statics(service: BluezService, tmp_path: Path) -> None:
    await started(service)
    static = tmp_path / "static"
    (static / "sub").mkdir(parents=True)
    for name, body in (
        ("index.html", "<p>x</p>"),
        ("app.js", "1"),
        ("style.css", "a{}"),
        ("README.md", "doc"),
        ("api.test.mjs", "t"),
        ("sub/ok.js", "2"),
    ):
        (static / name).write_text(body)
    (tmp_path / "secret.js").write_text("secret")
    (static / "link.js").symlink_to(tmp_path / "secret.js")
    from aiohttp.test_utils import TestClient, TestServer

    async with TestClient(TestServer(create_app(service, TOKEN, static=static))) as client:
        for path in (
            "/",
            "/static/app.js",
            "/static/style.css",
            "/static/index.html",
            "/static/sub/ok.js",
        ):
            resp = await client.get(path)
            assert resp.status == 200, path
            assert resp.headers["X-Content-Type-Options"] == "nosniff"
            assert resp.headers["X-Frame-Options"] == "DENY"
            assert resp.headers["Referrer-Policy"] == "no-referrer"
            assert resp.headers["Cache-Control"] == "no-store"
            csp = resp.headers["Content-Security-Policy"]
            assert (
                "default-src 'self'" in csp
                and "frame-ancestors 'none'" in csp
                and "base-uri 'none'" in csp
            )
        for path in (
            "/static/README.md",
            "/static/api.test.mjs",
            "/static/link.js",
            "/static/nope.js",
            "/static/sub",
        ):
            assert (await client.get(path)).status == 404, path
        for path in ("/static/../secret.js", "/static/%2e%2e/secret.js"):
            assert (await client.get(path)).status in (401, 404), path
        resp = await client.get("/api/state", headers=AUTH)
        assert resp.headers["X-Frame-Options"] == "DENY"
