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
        ("favicon.svg", "<svg/>"),
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
            "/static/favicon.svg",
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
        fav = await client.get("/favicon.ico")
        assert fav.status == 204
        resp = await client.get("/api/state", headers=AUTH)
        assert resp.headers["X-Frame-Options"] == "DENY"


async def test_adapters_closed_after_agent_registration(
    service: BluezService, bus: FakeBus, caplog: pytest.LogCaptureFixture
) -> None:
    """BlueZ rend Pairable à l'enregistrement de l'agent : l'état sûr est posé ensuite."""
    caplog.set_level(logging.INFO, logger="btmux.bluez")
    await started(service)
    members = [m for _, _, m, _ in bus.calls]
    assert "RequestDefaultAgent" in members
    for path in (SRC_PATH, HP_PATH):
        adapter = bus.objects[path]["org.bluez.Adapter1"]
        assert adapter["Pairable"] is False and adapter["Discoverable"] is False
    assert "event=agent_registered" in caplog.text
    assert caplog.text.index("agent_registered") < caplog.text.index("bluez_ready")
    assert all(a["pairable"] is False for a in service.inventory.state()["adapters"])


async def test_adapter_stuck_open_is_reported(
    service: BluezService, bus: FakeBus, caplog: pytest.LogCaptureFixture
) -> None:
    bus.set_errors[("org.bluez.Adapter1", "Pairable")] = DBusCallError(
        "org.bluez.Error.Failed", "x"
    )
    await started(service)
    assert "event=adapter_not_closed" in caplog.text


# ----- séance GATE 4 : confiance entrante sans agent, rôle des casques
async def test_just_works_incoming_pairing_is_trusted_in_sources_window(
    service: BluezService, bus: FakeBus
) -> None:
    await started(service)
    path = bus.add_device(SRC_PATH, "BC:93:07:3B:03:52", name="S24", Class=0x5A020C)
    await service.pairing.open("sources", 30)
    bus.change(path, "org.bluez.Device1", Paired=True)  # BlueZ n'appelle PAS l'agent (Just Works)
    await asyncio.sleep(0.05)
    assert (path, "org.bluez.Device1", "Trusted", True) in bus.sets
    state = {d["mac"]: d for d in service.inventory.state()["devices"]}
    assert (
        state["BC:93:07:3B:03:52"]["trusted"] is True
        and state["BC:93:07:3B:03:52"]["kind"] == "source"
    )


async def test_incoming_pairing_outside_window_is_not_trusted(
    service: BluezService, bus: FakeBus, caplog: pytest.LogCaptureFixture
) -> None:
    await started(service)
    path = bus.add_device(SRC_PATH, "BC:93:07:3B:03:52", name="S24")
    bus.change(path, "org.bluez.Device1", Paired=True)
    await asyncio.sleep(0.05)
    assert not [s for s in bus.sets if s[2] == "Trusted"]
    assert "event=unexpected_incoming_pairing" in caplog.text
    # fenêtre `headsets` : un entrant n'est pas non plus approuvé
    caplog.clear()
    await service.pairing.open("headsets", 30)
    other = bus.add_device(HP_PATH, "BB:BB:BB:BB:BB:09", name="x")
    bus.change(other, "org.bluez.Device1", Paired=True)
    await asyncio.sleep(0.05)
    assert not [s for s in bus.sets if s[2] == "Trusted"]


async def test_preexisting_bonds_are_not_retrusted_at_load(
    service: BluezService, bus: FakeBus
) -> None:
    bus.objects["/org/bluez/hci1/dev_BC_93_07_3B_03_52"] = {
        "org.bluez.Device1": {"Address": "BC:93:07:3B:03:52", "Paired": True, "Trusted": False}
    }
    await started(service)
    await service.pairing.open("sources", 30)
    await asyncio.sleep(0.05)
    assert not [s for s in bus.sets if s[2] == "Trusted"]


def test_deduce_kind_headphones_with_both_a2dp_roles_and_origin() -> None:
    from fakes import A2DP_SINK, A2DP_SOURCE

    from btmux.bluez.models import deduce_kind

    both = [A2DP_SOURCE, A2DP_SINK, "0000111e-0000-1000-8000-00805f9b34fb"]
    assert deduce_kind(0x240418, both) == "headset"  # Cache-oreilles
    assert deduce_kind(0x5A020C, []) == "source"  # S24 : téléphone, UUID inconnus
    assert deduce_kind(0x5A020C, both) == "source"
    assert deduce_kind(0x02010C, []) == "source"  # ordinateur
    assert deduce_kind(0x000000, both) == "unknown"
    assert deduce_kind(0x000000, both, "headset") == "headset"  # arbitre : origine
    assert deduce_kind(0x000000, [], "source") == "source"


async def test_pair_marks_origin_so_unclassified_headset_goes_to_headsets(
    config: Config, bus: FakeBus
) -> None:
    from fakes import A2DP_SINK, A2DP_SOURCE, adapter_obj

    mono = parse_config(
        {
            "adapters": [
                {"mac": "AA:BB:CC:00:00:01", "name": "btmux", "roles": ["sources", "headsets"]}
            ]
        }
    )
    mono_bus = FakeBus({SRC_PATH: adapter_obj("AA:BB:CC:00:00:01")})
    svc = BluezService(mono, mono_bus, adapter_wait=0.3, retry_interval=0.02)
    await started(svc)
    path = mono_bus.add_device(
        SRC_PATH, "28:11:A5:32:3B:22", name="Cache-oreilles", UUIDs=[A2DP_SOURCE, A2DP_SINK]
    )
    mono_bus.handlers[("org.bluez.Device1", "Pair")] = lambda p, b: mono_bus.change(
        p, "org.bluez.Device1", Paired=True
    )
    await svc.pairing.open("headsets", 30)
    await svc.pairing.pair("28:11:A5:32:3B:22")
    dev = next(d for d in svc.inventory.state()["devices"] if d["mac"] == "28:11:A5:32:3B:22")
    assert dev["kind"] == "headset" and dev["adapter"] == "headsets" and dev["trusted"] is True
    assert path in mono_bus.objects


# ----- revue LOT-2 : réserves 6 et 7 -----
async def test_pending_pair_is_cancelled_cleanly_on_teardown(
    service: BluezService, bus: FakeBus
) -> None:
    await started(service)
    path = bus.add_device(HP_PATH, HEADSET_MAC, name="Bose", Class=0x240404)
    never = asyncio.Event()

    async def hung_pair(p: str, body: list[Any]) -> list[Any]:
        await never.wait()
        return []

    bus.handlers[("org.bluez.Device1", "Pair")] = hung_pair
    await service.pairing.open("headsets", 30)
    waiter = asyncio.create_task(service.pairing.pair(HEADSET_MAC))
    await asyncio.sleep(0.05)
    assert service.pairing.allows(path)
    await asyncio.wait_for(service.pairing.cancel_pending(), 2)
    await asyncio.sleep(0)
    assert not service.pairing.allows(path)  # _outgoing nettoyé, plus d'agent autorisé
    with pytest.raises(asyncio.CancelledError):
        await waiter


async def test_patch_trusted_bluez_failure_is_502(api: _AsyncCtx) -> None:
    async with api as a:
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True)
        a.bus.set_errors[("org.bluez.Device1", "Trusted")] = DBusCallError(
            "org.bluez.Error.Failed", "boom"
        )
        status, body = await a.req("PATCH", f"/api/devices/{PHONE_MAC}", json={"trusted": True})
        assert status == 502 and body["error"] == "bluez_error"
