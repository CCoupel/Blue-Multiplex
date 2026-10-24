from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import Any

import pytest
from fakes import HP_PATH, SRC_PATH, FakeBus, adapter_obj

from btmux import daemon
from btmux.bluez import agent_dbus
from btmux.bluez.bus import BusSignal, DBusCallError, DBusFastBus, unwrap
from btmux.bluez.daemon import BluezService, adapter_wait_from_env
from btmux.bluez.errors import AdaptersNotFound, AgentRejected, BluezUnavailable
from btmux.cli import btmuxd
from btmux.config import Config


async def run_until(service: BluezService, stop: asyncio.Event) -> asyncio.Task[int]:
    task = asyncio.create_task(service.run(stop))
    await asyncio.wait_for(service.ready.wait(), 5)
    return task


async def test_start_registers_agent_and_closes_adapters(service: BluezService, bus: FakeBus):
    stop = asyncio.Event()
    task = await run_until(service, stop)
    assert bus.agent is service.agent and bus.agent_path == "/org/btmux/agent"
    members = [m for _, _, m, _ in bus.calls]
    assert "RegisterAgent" in members and "RequestDefaultAgent" in members
    adapter = bus.objects[SRC_PATH]["org.bluez.Adapter1"]
    assert (adapter["Powered"], adapter["Pairable"], adapter["Discoverable"]) == (True, False, False)
    await service.pairing.open("sources", 30)
    stop.set()
    assert await task == 0
    assert bus.agent is None and "UnregisterAgent" in [m for _, _, m, _ in bus.calls]
    assert service.inventory.state()["pairing"] is None  # fenêtre fermée à l'arrêt


async def test_missing_adapter_raises_after_wait(config: Config):
    bus = FakeBus({SRC_PATH: adapter_obj("AA:BB:CC:00:00:01")})  # il manque le second
    service = BluezService(config, bus, adapter_wait=0.2, retry_interval=0.02)
    with pytest.raises(AdaptersNotFound) as info:
        await service.run(asyncio.Event())
    assert info.value.missing == ["AA:BB:CC:00:00:02"]


async def test_adapter_appearing_during_wait_is_accepted(config: Config):
    bus = FakeBus({SRC_PATH: adapter_obj("AA:BB:CC:00:00:01")})
    service = BluezService(config, bus, adapter_wait=3, retry_interval=0.02)
    stop = asyncio.Event()
    task = asyncio.create_task(service.run(stop))
    await asyncio.sleep(0.1)
    bus.objects[HP_PATH] = adapter_obj("AA:BB:CC:00:00:02", "btmux-hp")
    await asyncio.wait_for(service.ready.wait(), 5)
    stop.set()
    assert await task == 0


async def test_bus_unavailable_then_available(service: BluezService, bus: FakeBus):
    bus.connect_failures = 3
    stop = asyncio.Event()
    task = await run_until(service, stop)
    assert bus.connect_count == 4
    stop.set()
    await task


async def test_bus_never_available_exits_with_adapter_error(config: Config):
    bus = FakeBus()
    bus.connect_failures = 10**6
    service = BluezService(config, bus, adapter_wait=0.15, retry_interval=0.02)
    with pytest.raises(AdaptersNotFound):
        await service.run(asyncio.Event())


async def test_stop_while_waiting_for_adapters(config: Config):
    service = BluezService(config, FakeBus({}), adapter_wait=30, retry_interval=0.02)
    stop = asyncio.Event()
    task = asyncio.create_task(service.run(stop))
    await asyncio.sleep(0.1)
    stop.set()
    assert await asyncio.wait_for(task, 5) == 0


@pytest.mark.parametrize("how", ["disconnect", "bluez_left"])
async def test_reconnects_when_bus_or_bluez_is_lost(service: BluezService, bus: FakeBus, how: str):
    stop = asyncio.Event()
    task = await run_until(service, stop)
    first = bus.connect_count
    await service.pairing.open("sources", 30)
    if how == "disconnect":
        bus.lose_connection()
    else:
        bus.bluez_left()
    await asyncio.sleep(0.15)
    await asyncio.wait_for(service.ready.wait(), 5)
    assert bus.connect_count == first + 1 and bus.agent is service.agent
    assert service.inventory.state()["pairing"] is None
    stop.set()
    assert await task == 0


async def test_serve_prints_started_and_exit_codes(
    config: Config, bus: FakeBus, capsys: pytest.CaptureFixture[str]
):
    stop = asyncio.Event()
    service = BluezService(config, bus, adapter_wait=1, retry_interval=0.02)
    entered: list[str] = []

    @contextlib.asynccontextmanager
    async def extension(svc: BluezService):
        entered.append("in")
        yield
        entered.append("out")

    task = asyncio.create_task(daemon.serve(stop, config, service=service, extension=extension))
    await asyncio.wait_for(service.ready.wait(), 5)
    await asyncio.sleep(0.05)
    stop.set()
    assert await task == 0
    out = capsys.readouterr().out
    assert "started" in out and "stopped" in out and entered == ["in", "out"]
    # adaptateur absent : code 3 et message
    bad = BluezService(config, FakeBus({}), adapter_wait=0.1, retry_interval=0.02)
    assert await daemon.serve(asyncio.Event(), config, service=bad) == 3
    assert "adapter not found" in capsys.readouterr().err


def test_btmuxd_main_passes_config_and_returns_code(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text('adapters:\n  - {mac: "AA:BB:CC:00:00:01", name: a, roles: [sources, headsets]}\n')
    seen: list[Config] = []
    monkeypatch.setattr(daemon, "run", lambda c: seen.append(c) or 3)
    assert btmuxd.main(["--config", str(cfg)]) == 3 and seen[0].adapters[0].name == "a"


def test_adapter_wait_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BTMUX_ADAPTER_WAIT", raising=False)
    assert adapter_wait_from_env() == 30.0
    monkeypatch.setenv("BTMUX_ADAPTER_WAIT", "1.5")
    assert adapter_wait_from_env() == 1.5
    monkeypatch.setenv("BTMUX_ADAPTER_WAIT", "abc")
    assert adapter_wait_from_env() == 30.0


# ----- DBusFastBus et glue D-Bus --------------------------------------------------------------
def test_unwrap_variants() -> None:
    from dbus_fast import Variant

    nested = {"a": Variant("as", ["x"]), "b": [Variant("i", 1)], "c": (Variant("b", True),)}
    assert unwrap(nested) == {"a": ["x"], "b": [1], "c": [True]}


def _msg(member: str, body: list[Any], path: str = "/org/bluez/hci0", sender: str = ":1.4") -> Any:
    from dbus_fast import MessageType

    return SimpleNamespace(
        message_type=MessageType.SIGNAL, member=member, body=body, path=path, sender=sender
    )


def test_dbus_message_to_signals() -> None:
    from dbus_fast import MessageType, Variant

    bus = DBusFastBus()
    got: list[BusSignal] = []
    bus.on_signal(got.append)
    bus._on_message(_msg("PropertiesChanged", ["org.bluez.Adapter1", {"Powered": Variant("b", True)}, []]))
    bus._on_message(_msg("PropertiesChanged", ["x", {}, []], sender="org.freedesktop.DBus"))
    bus._on_message(_msg("InterfacesAdded", ["/p", {"org.bluez.Device1": {"Paired": Variant("b", True)}}]))
    bus._on_message(_msg("InterfacesRemoved", ["/p", ["org.bluez.Device1"]]))
    bus._on_message(_msg("NameOwnerChanged", ["org.bluez", ":1.4", ""]))
    bus._on_message(_msg("NameOwnerChanged", ["other", "", ":1.9"]))
    bus._on_message(SimpleNamespace(message_type=MessageType.METHOD_CALL))
    kinds = [(s.kind, s.interface) for s in got]
    assert kinds == [
        ("properties_changed", "org.bluez.Adapter1"),
        ("interfaces_added", None),
        ("interfaces_removed", None),
        ("name_owner_changed", None),
    ]
    assert got[0].data == {"Powered": True} and got[1].data["org.bluez.Device1"] == {"Paired": True}
    assert got[3].data == (":1.4", "")


class _FakeDBus:
    """Faux MessageBus dbus-fast."""

    def __init__(self, replies: list[Any] | Exception) -> None:
        self.replies, self.sent, self.exported, self.handler = replies, [], {}, None
        self.disconnected = asyncio.Event()

    async def call(self, msg: Any) -> Any:
        self.sent.append(msg)
        if isinstance(self.replies, Exception):
            raise self.replies
        reply = self.replies.pop(0) if self.replies else None
        if isinstance(reply, Exception):
            raise reply
        if reply == "hang":
            await asyncio.sleep(60)
        return reply

    def export(self, path: str, iface: Any) -> None:
        self.exported[path] = iface

    def unexport(self, path: str) -> None:
        self.exported.pop(path, None)

    def add_message_handler(self, fn: Any) -> None:
        self.handler = fn

    def disconnect(self) -> None:
        self.disconnected.set()

    async def wait_for_disconnect(self) -> None:
        await self.disconnected.wait()


def _reply(body: list[Any], error: str | None = None) -> Any:
    from dbus_fast import MessageType

    return SimpleNamespace(
        message_type=MessageType.ERROR if error else MessageType.METHOD_RETURN,
        error_name=error,
        body=body,
    )


async def test_dbusfastbus_call_paths() -> None:
    bus = DBusFastBus()
    with pytest.raises(BluezUnavailable):
        await bus.call("/", "i", "m")  # non connecté
    fake = _FakeDBus([_reply([{"/a": {}}]), _reply([], "org.bluez.Error.Failed"), None, "hang"])
    bus._bus = fake
    assert await bus.get_managed_objects() == {"/a": {}}
    with pytest.raises(DBusCallError) as info:
        await bus.call("/", "i", "m")
    assert info.value.name == "org.bluez.Error.Failed"
    assert await bus.call("/", "i", "m") == []
    with pytest.raises(DBusCallError, match="Timeout"):
        await bus.call("/", "i", "m", timeout=0.05)
    fake.replies = RuntimeError("boom")
    with pytest.raises(BluezUnavailable):
        await bus.call("/", "i", "m")
    fake.replies = [_reply([])]
    await bus.set_property("/p", "iface", "Trusted", "b", True)
    assert fake.sent[-1].member == "Set"
    fake.replies = [_reply([])]


async def test_dbusfastbus_connect_failure_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    import dbus_fast.aio as aio

    class Boom:
        def __init__(self, **kw: Any) -> None: ...

        async def connect(self) -> Any:
            raise FileNotFoundError("no socket")

    monkeypatch.setattr(aio, "MessageBus", Boom)
    bus = DBusFastBus()
    with pytest.raises(BluezUnavailable, match="no socket"):
        await bus.connect()

    fake = _FakeDBus([None, None])

    class Good:
        def __init__(self, **kw: Any) -> None: ...

        async def connect(self) -> Any:
            return fake

    monkeypatch.setattr(aio, "MessageBus", Good)
    bus = DBusFastBus()
    lost: list[int] = []
    bus.on_disconnect(lambda: lost.append(1))
    await bus.connect()
    assert fake.handler is not None and len(fake.sent) == 2  # deux AddMatch
    fake.disconnected.set()
    await asyncio.sleep(0.05)
    assert lost == [1]
    await bus.export_agent("/a", SimpleNamespace())  # type: ignore[arg-type]
    assert "/a" in fake.exported
    await bus.unexport_agent("/a")
    await bus.unexport_agent("/zzz")
    await bus.close()
    await bus.close()


async def test_agent_dbus_interface_maps_rejection(service: BluezService, bus: FakeBus):
    from dbus_fast import DBusError

    await service._start_once()
    iface = agent_dbus.make_interface(service.agent)
    dev = "/org/bluez/hci1/dev_11_22_33_44_55_01"
    with pytest.raises(DBusError) as info:
        await iface.RequestAuthorization(dev)
    assert info.value.type == "org.bluez.Error.Rejected"
    await service.pairing.open("sources", 20)
    await iface.RequestAuthorization(dev)
    await iface.AuthorizeService(dev, "0000110b")
    await iface.RequestConfirmation(dev, 1)
    assert await iface.RequestPinCode(dev) == "0000" and await iface.RequestPasskey(dev) == 0
    assert iface.DisplayPasskey(dev, 1, 0) is None and iface.DisplayPinCode(dev, "1") is None
    iface.Release()
    iface.Cancel()
    with pytest.raises(AgentRejected):
        await service.agent.request_authorization("/org/bluez/hci0/dev_x")
