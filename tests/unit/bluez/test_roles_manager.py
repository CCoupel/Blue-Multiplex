"""R-13 (#23) : `GET /api/controllers`, `PUT /api/controllers/roles`, verrou `change_pending`."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml
from fakes import HEADSET_MAC, HP_PATH, PHONE_MAC, SRC_PATH, FakeBus, adapter_obj
from test_api import AUTH, _AsyncCtx

from btmux.bluez.daemon import BluezService
from btmux.config import Config

SRC = "AA:BB:CC:00:00:01"
HP = "AA:BB:CC:00:00:02"
EXTRA = "AA:BB:CC:00:00:09"


@pytest.fixture(name="state_file")
def state_file_fixture(tmp_path: Path) -> Path:
    return tmp_path / "adapters.yaml"


@pytest.fixture(name="api")
def api_fixture(config: Config, bus: FakeBus, state_file: Path) -> _AsyncCtx:
    bus.objects["/org/bluez/hci5"] = adapter_obj(EXTRA, "raspberrypi")
    cfg = config.model_copy(update={"state_path": state_file})
    return _AsyncCtx(BluezService(cfg, bus, adapter_wait=0.3, retry_interval=0.02), bus)


async def _put(a: Any, body: Any) -> tuple[int, Any]:
    return await a.req("PUT", "/api/controllers/roles", json=body)


async def test_get_controllers(api: _AsyncCtx) -> None:
    async with api as a:
        status, body = await a.req("GET", "/api/controllers")
        assert status == 200 and set(body) == {"controllers", "roles"}
        assert {c["mac"]: c["role"] for c in body["controllers"]} == {
            SRC: "sources",
            HP: "headsets",
            EXTRA: None,
        }
        extra = next(c for c in body["controllers"] if c["mac"] == EXTRA)
        assert extra["pairable"] is False and extra["discoverable"] is False


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"sources": SRC}, "invalid_body"),
        ({"sources": SRC, "headsets": HP, "force": True}, "invalid_body"),
        ([1], "invalid_body"),
        ({"sources": SRC, "headsets": HP, "confirm": "yes"}, "invalid_confirm"),
        ({"sources": "zz", "headsets": None}, "invalid_mac"),
        ({"sources": 5, "headsets": None}, "invalid_mac"),
        ({"sources": "AA:BB:CC:00:00:77", "headsets": None}, "unknown_controller"),
        ({"sources": SRC, "headsets": SRC}, "same_controller"),
    ],
)
async def test_put_roles_validation_400(api: _AsyncCtx, state_file: Path, body: Any, code: str):
    async with api as a:
        status, resp = await _put(a, body)
        assert status == 400 and resp["error"] == code
        assert not state_file.exists()
        status, resp = await a.req("PUT", "/api/controllers/roles", data=b"{oops")
        assert status == 400 and resp["error"] == "invalid_body"


async def test_put_roles_same_assignment_is_noop_200(api: _AsyncCtx, state_file: Path) -> None:
    async with api as a:
        status, roles = await _put(a, {"sources": SRC.lower(), "headsets": HP})
        assert status == 200 and roles["pending"] is False and not state_file.exists()


async def test_put_roles_writes_state_and_goes_pending(api: _AsyncCtx, state_file: Path) -> None:
    async with api as a:
        sub = a.service.inventory.subscribe()
        status, roles = await _put(a, {"sources": EXTRA, "headsets": SRC})
        assert status == 202
        assert roles == {
            "sources": EXTRA,
            "headsets": SRC,
            "source": "config",
            "pending": True,
            "restart_expected": True,
        }
        written = yaml.safe_load(state_file.read_text())["adapters"]
        assert {w["mac"]: w["roles"] for w in written} == {EXTRA: ["sources"], SRC: ["headsets"]}
        assert oct(state_file.stat().st_mode & 0o777) == "0o640"
        kinds = [sub.queue.get_nowait().kind for _ in range(sub.queue.qsize())]
        assert kinds[-1] == "roles" and "controllers" in kinds
        ctrls = (await a.req("GET", "/api/controllers"))[1]
        assert {c["mac"]: c["role"] for c in ctrls["controllers"]}[EXTRA] == "sources"
        assert ctrls["roles"]["pending"] is True
        # change_pending : toute écriture est refusée, les lectures restent servies
        for method, path, kw in (
            ("POST", "/api/pairing", {"json": {"adapter": "sources"}}),
            ("DELETE", "/api/pairing", {}),
            ("POST", f"/api/devices/{PHONE_MAC}/connect", {}),
            ("PATCH", f"/api/devices/{PHONE_MAC}", {"json": {"trusted": True}}),
            ("PUT", "/api/controllers/roles", {"json": {"sources": SRC, "headsets": HP}}),
        ):
            status, body = await a.req(method, path, **kw)
            assert (status, body["error"]) == (409, "change_pending"), path
        assert (await a.req("GET", "/api/state"))[0] == 200


async def test_put_roles_free_a_role_and_default_name(api: _AsyncCtx, state_file: Path) -> None:
    async with api as a:
        status, roles = await _put(a, {"sources": EXTRA, "headsets": None})
        assert status == 202 and roles["headsets"] is None
        written = yaml.safe_load(state_file.read_text())["adapters"]
        assert written == [{"mac": EXTRA, "name": "btmux", "roles": ["sources"]}]


async def test_put_roles_empty_assignment_writes_empty_list(api: _AsyncCtx, state_file: Path):
    async with api as a:
        assert (await _put(a, {"sources": None, "headsets": None}))[0] == 202
        assert yaml.safe_load(state_file.read_text())["adapters"] == []


async def test_put_roles_refused_while_pairing_window_open(api: _AsyncCtx, state_file: Path):
    async with api as a:
        assert (await a.req("POST", "/api/pairing", json={"adapter": "sources"}))[0] == 202
        status, body = await _put(a, {"sources": HP, "headsets": SRC})
        assert (status, body["error"]) == (409, "pairing_open") and not state_file.exists()


async def test_put_roles_devices_connected_needs_confirm(api: _AsyncCtx, state_file: Path):
    async with api as a:
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True, Connected=True)
        a.bus.add_device(HP_PATH, HEADSET_MAC, name="Bose", Paired=True, Connected=False)
        swap = {"sources": HP, "headsets": SRC}
        status, body = await _put(a, swap)
        assert (status, body["error"]) == (409, "devices_connected")
        assert body["details"] == [
            {"mac": PHONE_MAC, "alias": "pc-pro", "name": "PC", "adapter": "sources"}
        ]
        assert not state_file.exists() and not a.bus.calls_to("Disconnect")
        status, _ = await _put(a, {**swap, "confirm": True})
        assert status == 202 and state_file.exists()
        assert [p for p, _ in a.bus.calls_to("Disconnect")] == [
            f"{SRC_PATH}/dev_{PHONE_MAC.replace(':', '_')}"
        ]


async def test_put_roles_state_write_failure_does_not_go_pending(api: _AsyncCtx, tmp_path: Path):
    async with api as a:
        blocker = tmp_path / "file"
        blocker.write_text("x")
        a.service.roles._config = a.service.roles._config.model_copy(
            update={"state_path": blocker / "adapters.yaml"}
        )
        status, body = await _put(a, {"sources": EXTRA, "headsets": None})
        assert status == 500 and body["error"] == "state_write_failed"
        assert "adapters.yaml" in body["message"]
        assert a.service.inventory.roles_pending is False
        assert (await a.req("GET", "/api/controllers"))[1]["roles"]["pending"] is False


async def test_roles_without_bluez_is_503(api: _AsyncCtx) -> None:
    async with api as a:
        a.service.ready.clear()
        assert (await a.req("GET", "/api/controllers"))[0] == 503
        assert (await _put(a, {"sources": None, "headsets": None}))[0] == 503


async def test_sse_after_restart_client_with_higher_last_event_id_gets_state(api: _AsyncCtx):
    """Le compteur repart à 0 au redémarrage : un `Last-Event-ID` supérieur ⇒ `state` complet."""
    async with api as a:
        resp = await a.c.get("/api/events", headers={**AUTH, "Last-Event-ID": "4242"})
        assert resp.status == 200
        data = ""
        while "event: state" not in data:
            data += (await asyncio.wait_for(resp.content.readline(), 3)).decode()
        resp.close()
        assert "controllers" in (await a.req("GET", "/api/state"))[1]


# ----- R-14 : redémarrage piloté côté daemon -----
def _service(config: Config, bus: FakeBus, state_file: Path, timeout: float) -> BluezService:
    cfg = config.model_copy(update={"state_path": state_file})
    return BluezService(cfg, bus, adapter_wait=0.3, retry_interval=0.02, restart_timeout=timeout)


async def test_restart_fallback_exits_with_code_4_when_no_sigterm(
    config: Config, bus: FakeBus, state_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service = _service(config, bus, state_file, 0.2)
    task = asyncio.create_task(service.run(asyncio.Event()))
    await asyncio.wait_for(service.ready.wait(), 5)
    assert (await service.roles.set_roles({"sources": HP, "headsets": SRC}))[0] == 202
    assert service.inventory.roles_pending is True  # reste vrai jusqu'à l'arrêt
    assert await asyncio.wait_for(task, 5) == 4
    assert "event=restart_fallback" in caplog.text
    assert bus.agent is None  # teardown propre avant la sortie


async def test_sigterm_before_timeout_exits_0_without_fallback(
    config: Config, bus: FakeBus, state_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service = _service(config, bus, state_file, 0.5)
    stop = asyncio.Event()
    task = asyncio.create_task(service.run(stop))
    await asyncio.wait_for(service.ready.wait(), 5)
    await service.roles.set_roles({"sources": HP, "headsets": SRC})
    stop.set()  # SIGTERM reçu : arrêt propre
    assert await asyncio.wait_for(task, 5) == 0
    await asyncio.sleep(0.6)
    assert "restart_fallback" not in caplog.text


async def test_no_timer_without_role_change(config: Config, bus: FakeBus, state_file: Path):
    service = _service(config, bus, state_file, 0.1)
    stop = asyncio.Event()
    task = asyncio.create_task(service.run(stop))
    await asyncio.wait_for(service.ready.wait(), 5)
    assert (await service.roles.set_roles({"sources": SRC, "headsets": HP}))[0] == 200
    await asyncio.sleep(0.3)
    assert not task.done()
    stop.set()
    assert await task == 0


async def test_serve_returns_4_on_restart_fallback(
    config: Config, bus: FakeBus, state_file: Path
) -> None:
    from btmux import daemon

    service = _service(config, bus, state_file, 0.1)
    task = asyncio.create_task(daemon.serve(asyncio.Event(), config, service=service))
    await asyncio.wait_for(service.ready.wait(), 5)
    await service.roles.set_roles({"sources": None, "headsets": HP})
    assert await asyncio.wait_for(task, 5) == 4


async def test_confirm_write_failure_is_500_without_pending(api: _AsyncCtx, tmp_path: Path) -> None:
    async with api as a:
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True, Connected=True)
        blocker = tmp_path / "file"
        blocker.write_text("x")
        a.service.roles._config = a.service.roles._config.model_copy(
            update={"state_path": blocker / "adapters.yaml"}
        )
        status, body = await _put(a, {"sources": HP, "headsets": SRC, "confirm": True})
        assert (status, body["error"]) == (500, "state_write_failed")
        assert not a.service.inventory.roles_pending


async def test_confirm_disconnects_and_confirms_before_writing_state(
    api: _AsyncCtx, state_file: Path
):
    """S3 : Disconnect → Connected=false confirmé → ENSUITE écriture des rôles (et redémarrage)."""
    async with api as a:
        path = a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True, Connected=True)
        seen: dict[str, bool] = {}

        async def disconnect(p: str, body: list[Any]) -> list[Any]:
            seen["state_written_at_disconnect"] = state_file.exists()
            await asyncio.sleep(0.1)  # BlueZ confirme avec un léger retard
            a.bus.change(p, "org.bluez.Device1", Connected=False)
            return []

        a.bus.handlers[("org.bluez.Device1", "Disconnect")] = disconnect
        written_at_confirm: list[bool] = []
        orig = a.service.roles._disconnect_and_wait

        async def spy(mac: str) -> None:
            await orig(mac)
            written_at_confirm.append(state_file.exists())

        a.service.roles._disconnect_and_wait = spy  # type: ignore[method-assign]
        status, _ = await _put(a, {"sources": HP, "headsets": SRC, "confirm": True})
        assert status == 202
        assert seen == {"state_written_at_disconnect": False}
        assert written_at_confirm == [False] and state_file.exists()
        assert a.bus.objects[path]["org.bluez.Device1"]["Connected"] is False


async def test_confirm_disconnect_error_writes_nothing(api: _AsyncCtx, state_file: Path):
    from btmux.bluez.bus import DBusCallError

    async with api as a:
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True, Connected=True)
        a.bus.errors[("org.bluez.Device1", "Disconnect")] = DBusCallError(
            "org.bluez.Error.Failed", "boom"
        )
        status, body = await _put(a, {"sources": HP, "headsets": SRC, "confirm": True})
        assert (status, body["error"]) == (502, "disconnect_failed")
        assert [d["mac"] for d in body["details"]] == [PHONE_MAC]
        assert not state_file.exists() and not a.service.inventory.roles_pending


async def test_confirm_disconnect_timeout_writes_nothing(api: _AsyncCtx, state_file: Path):
    async with api as a:
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True, Connected=True)
        a.bus.handlers[("org.bluez.Device1", "Disconnect")] = lambda p, b: []  # reste connecté
        a.service.roles.disconnect_timeout = 0.2
        a.service.roles.disconnect_poll = 0.02
        status, body = await _put(a, {"sources": HP, "headsets": SRC, "confirm": True})
        assert (status, body["error"]) == (502, "disconnect_failed")
        assert not state_file.exists() and not a.service.inventory.roles_pending


async def test_blocking_disconnect_call_is_bounded(api: _AsyncCtx, state_file: Path):
    """Réserve 1 : `Disconnect` muet : borné par `disconnect_timeout`, en parallèle."""
    async with api as a:
        for mac in (PHONE_MAC, HEADSET_MAC):
            a.bus.add_device(SRC_PATH, mac, name=mac, Paired=True, Connected=True)

        async def hang(p: str, body: list[Any]) -> list[Any]:
            await asyncio.sleep(3600)
            return []

        a.bus.handlers[("org.bluez.Device1", "Disconnect")] = hang
        a.service.roles.disconnect_timeout = 0.2
        loop = asyncio.get_running_loop()
        start = loop.time()
        status, body = await _put(a, {"sources": HP, "headsets": SRC, "confirm": True})
        assert (status, body["error"]) == (502, "disconnect_failed")
        assert (
            len(body["details"]) == 2 and loop.time() - start < 0.2 * 2 + 1
        )  # parallèle, pas 2 × délai
        assert not state_file.exists() and not a.service.inventory.roles_pending


async def test_not_connected_error_is_a_success_when_already_disconnected(
    api: _AsyncCtx, state_file: Path
):
    """Réserve 2 : NotConnected alors que l'appareil est déjà tombé → pas de faux échec."""
    from btmux.bluez.bus import DBusCallError

    async with api as a:
        path = a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True, Connected=True)

        async def not_connected(p: str, body: list[Any]) -> list[Any]:
            a.bus.change(p, "org.bluez.Device1", Connected=False)  # tombé juste avant l'appel
            raise DBusCallError("org.bluez.Error.NotConnected", "Not connected")

        a.bus.handlers[("org.bluez.Device1", "Disconnect")] = not_connected
        status, _ = await _put(a, {"sources": HP, "headsets": SRC, "confirm": True})
        assert status == 202 and state_file.exists()
        assert a.bus.objects[path]["org.bluez.Device1"]["Connected"] is False


async def test_window_opened_during_disconnection_refuses_without_writing(
    api: _AsyncCtx, state_file: Path
):
    """Réserve 3 : les contrôles sont rejoués après les déconnexions."""
    from unittest.mock import PropertyMock, patch

    from btmux.bluez.pairing import PairingManager

    async with api as a:
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True, Connected=True)
        opened = PropertyMock(return_value=False)

        async def disconnect(p: str, body: list[Any]) -> list[Any]:
            opened.return_value = True  # une fenêtre s'ouvre pendant la déconnexion
            a.bus.change(p, "org.bluez.Device1", Connected=False)
            return []

        a.bus.handlers[("org.bluez.Device1", "Disconnect")] = disconnect
        with patch.object(PairingManager, "window_open", opened):
            status, body = await _put(a, {"sources": HP, "headsets": SRC, "confirm": True})
        assert (status, body["error"]) == (409, "pairing_open")
        assert not state_file.exists() and not a.service.inventory.roles_pending


async def test_device_reconnected_during_disconnection_is_a_502(api: _AsyncCtx, state_file: Path):
    """Réserve 3 : appareil reconnecté entre-temps → 502 déterministe, rien d'écrit."""
    async with api as a:
        a.bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True, Connected=True)
        a.bus.add_device(SRC_PATH, HEADSET_MAC, name="Tel", Paired=True, Connected=False)

        async def disconnect(p: str, body: list[Any]) -> list[Any]:
            a.bus.change(p, "org.bluez.Device1", Connected=False)
            other = next(
                q for q in a.bus.objects if q != p and q.endswith(HEADSET_MAC.replace(":", "_"))
            )
            a.bus.change(other, "org.bluez.Device1", Connected=True)
            return []

        a.bus.handlers[("org.bluez.Device1", "Disconnect")] = disconnect
        status, body = await _put(a, {"sources": HP, "headsets": SRC, "confirm": True})
        assert (status, body["error"]) == (502, "disconnect_failed")
        assert [d["mac"] for d in body["details"]] == [HEADSET_MAC]
        assert not state_file.exists() and not a.service.inventory.roles_pending


async def test_confirm_without_connected_devices_keeps_the_path(api: _AsyncCtx, state_file: Path):
    async with api as a:
        status, _ = await _put(a, {"sources": HP, "headsets": SRC, "confirm": True})
        assert status == 202 and state_file.exists() and not a.bus.calls_to("Disconnect")


async def test_noop_wins_over_open_pairing_window(api: _AsyncCtx, state_file: Path) -> None:
    async with api as a:
        assert (await a.req("POST", "/api/pairing", json={"adapter": "sources"}))[0] == 202
        status, roles = await _put(a, {"sources": SRC, "headsets": HP})
        assert status == 200 and roles["pending"] is False and not state_file.exists()
        status, body = await _put(a, {"sources": HP, "headsets": SRC})
        assert (status, body["error"]) == (409, "pairing_open")


def test_default_restart_fallback_delay_is_30s(config: Config, bus: FakeBus) -> None:
    assert BluezService(config, bus).restart_timeout == 30.0


async def test_put_roles_check_order_while_pending(api: _AsyncCtx) -> None:
    """Contrat [20261024-f] : 400 → no-op 200 → 409 change_pending."""
    async with api as a:
        assert (await _put(a, {"sources": EXTRA, "headsets": SRC}))[0] == 202
        status, body = await _put(a, {"sources": "zz", "headsets": None})
        assert (status, body["error"]) == (400, "invalid_mac")  # 400 avant change_pending
        status, roles = await _put(a, {"sources": EXTRA, "headsets": SRC})
        assert status == 200 and roles["pending"] is True  # identique à l'écrit : no-op
        status, body = await _put(a, {"sources": SRC, "headsets": HP})
        assert (status, body["error"]) == (409, "change_pending")


# ----- B-1 : l'alias suit le rôle -----
def _names(state_file: Path) -> dict[str, str]:
    return {a["mac"]: a["name"] for a in yaml.safe_load(state_file.read_text())["adapters"]}


async def test_alias_follows_the_role_after_a_swap(api: _AsyncCtx, state_file: Path) -> None:
    async with api as a:
        assert (await _put(a, {"sources": HP, "headsets": SRC}))[0] == 202
        assert _names(state_file) == {HP: "btmux", SRC: "btmux-hp"}


async def test_alias_of_a_new_controller_is_the_role_name(api: _AsyncCtx, state_file: Path) -> None:
    async with api as a:
        assert (await _put(a, {"sources": EXTRA, "headsets": SRC}))[0] == 202
        assert _names(state_file) == {EXTRA: "btmux", SRC: "btmux-hp"}


async def test_alias_of_a_controller_carrying_both_roles_is_the_sources_name(
    api: _AsyncCtx, state_file: Path
) -> None:
    async with api as a:
        assert (await _put(a, {"sources": EXTRA, "headsets": EXTRA}))[0] == 400  # même contrôleur
    # (un seul contrôleur pour les deux rôles passe par la config mono, testé via _adapters_for)
    cfg = api.service.roles
    from btmux.bluez.controllers import RoleManager

    assert isinstance(cfg, RoleManager)
    [only] = cfg._adapters_for({"sources": SRC, "headsets": None})
    assert (only.name, only.roles) == ("btmux", ("sources",))


async def test_alias_defaults_when_config_has_no_entry_for_the_role(
    config: Config, bus: FakeBus, state_file: Path
) -> None:
    empty = config.model_copy(update={"adapters": (), "state_path": state_file})
    service = BluezService(empty, bus, adapter_wait=0.3, retry_interval=0.02)
    adapters = service.roles._adapters_for({"sources": HP, "headsets": SRC})
    assert {a.mac: a.name for a in adapters} == {HP: "btmux", SRC: "btmux-hp"}
    both = service.roles._adapters_for({"sources": HP, "headsets": HP})
    assert [(a.name, a.roles) for a in both] == [("btmux", ("sources", "headsets"))]


async def test_alias_uses_custom_config_names_per_role(config: Config, bus: FakeBus, tmp_path):
    from btmux.config import Adapter

    custom = config.model_copy(
        update={
            "adapters": (
                Adapter(mac=SRC, name="salon", roles=("sources",)),
                Adapter(mac=HP, name="salon-casque", roles=("headsets",)),
            ),
            "state_path": tmp_path / "a.yaml",
        }
    )
    service = BluezService(custom, bus, adapter_wait=0.3, retry_interval=0.02)
    swapped = service.roles._adapters_for({"sources": HP, "headsets": SRC})
    assert {a.mac: a.name for a in swapped} == {HP: "salon", SRC: "salon-casque"}
