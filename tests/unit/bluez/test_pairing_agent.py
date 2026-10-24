from __future__ import annotations

import asyncio

import pytest
from fakes import HEADSET_MAC, HP_PATH, PHONE_MAC, SRC_PATH, FakeBus, device_path

from btmux.bluez.bus import DBusCallError
from btmux.bluez.daemon import BluezService
from btmux.bluez.errors import (
    AgentRejected,
    BluezError,
    BondStale,
    InvalidRequest,
    NotFound,
    WindowClosed,
    WindowOpen,
)


async def started(service: BluezService) -> BluezService:
    assert await service._start_once() == []
    return service


def last_set(bus: FakeBus, prop: str) -> object:
    return [v for _, _, p, v in bus.sets if p == prop][-1]


# ----- fenêtre ------------------------------------------------------------------------------
async def test_open_sources_window_sets_adapter_and_emits(service: BluezService, bus: FakeBus):
    await started(service)
    sub = service.inventory.subscribe()
    window = await service.pairing.open("sources", 30)
    assert window.adapter == "sources" and window.remaining_s in (29, 30)
    assert bus.objects[SRC_PATH]["org.bluez.Adapter1"]["Discoverable"] is True
    assert bus.objects[SRC_PATH]["org.bluez.Adapter1"]["Pairable"] is True
    assert last_set(bus, "DiscoverableTimeout") == 30
    kinds = [sub.queue.get_nowait().kind for _ in range(sub.queue.qsize())]
    assert "pairing" in kinds and "adapter" in kinds
    assert service.inventory.state()["pairing"]["adapter"] == "sources"
    with pytest.raises(WindowOpen):
        await service.pairing.open("headsets", 10)
    await service.pairing.close()
    await service.pairing.close()  # idempotent
    assert bus.objects[SRC_PATH]["org.bluez.Adapter1"]["Discoverable"] is False
    assert service.inventory.state()["pairing"] is None


@pytest.mark.parametrize("duration", [0, 301, -1, "10", True, 1.5])
async def test_open_validates_duration(service: BluezService, duration):
    await started(service)
    with pytest.raises(InvalidRequest):
        await service.pairing.open("sources", duration)


async def test_open_rejects_unknown_role_and_uses_default_duration(service: BluezService):
    await started(service)
    with pytest.raises(InvalidRequest):
        await service.pairing.open("speakers")
    window = await service.pairing.open("sources")
    assert window.remaining_s in (59, 60)  # pairing.default_duration


async def test_window_expires_by_itself(service: BluezService, bus: FakeBus):
    await started(service)
    await service.pairing.open("sources", 1)
    await asyncio.sleep(1.2)
    assert service.inventory.state()["pairing"] is None
    assert bus.objects[SRC_PATH]["org.bluez.Adapter1"]["Pairable"] is False


async def test_headsets_window_starts_and_stops_discovery(service: BluezService, bus: FakeBus):
    await started(service)
    await service.pairing.open("headsets", 20)
    assert [m for _, _, m, _ in bus.calls if m in ("SetDiscoveryFilter", "StartDiscovery")] == [
        "SetDiscoveryFilter",
        "StartDiscovery",
    ]
    await service.pairing.close()
    assert bus.calls_to("StopDiscovery")


async def test_headsets_discovery_failure_resets_adapter(service: BluezService, bus: FakeBus):
    await started(service)
    bus.errors[("org.bluez.Adapter1", "StartDiscovery")] = DBusCallError(
        "org.bluez.Error.NotReady", "off"
    )
    with pytest.raises(BluezError, match="NotReady"):
        await service.pairing.open("headsets", 20)
    assert service.inventory.state()["pairing"] is None
    assert bus.objects[HP_PATH]["org.bluez.Adapter1"]["Discoverable"] is False
    # InProgress est toléré
    bus.errors[("org.bluez.Adapter1", "StartDiscovery")] = DBusCallError(
        "org.bluez.Error.InProgress"
    )
    assert (await service.pairing.open("headsets", 20)).adapter == "headsets"


async def test_open_reports_bluez_set_error(service: BluezService, bus: FakeBus):
    await started(service)
    bus.set_errors[("org.bluez.Adapter1", "Pairable")] = DBusCallError(
        "org.bluez.Error.Failed", "nope"
    )
    with pytest.raises(BluezError, match="Pairable"):
        await service.pairing.open("sources", 5)


# ----- agent ----------------------------------------------------------------------------------
async def test_agent_refuses_by_default_and_outside_window(service: BluezService):
    await started(service)
    agent = service.agent
    dev = device_path(SRC_PATH, PHONE_MAC)
    with pytest.raises(AgentRejected):
        await agent.request_authorization(dev)
    with pytest.raises(AgentRejected):
        await agent.authorize_service(dev, "0000110b")
    for call in (
        agent.request_confirmation(dev, 1),
        agent.request_pin_code(dev),
        agent.request_passkey(dev),
    ):
        with pytest.raises(AgentRejected):
            await call


async def test_agent_accepts_incoming_in_sources_window_and_trusts(
    service: BluezService, bus: FakeBus
):
    await started(service)
    path = bus.add_device(SRC_PATH, PHONE_MAC, name="PC")
    await service.pairing.open("sources", 30)
    await service.agent.request_authorization(path)
    await service.agent.request_confirmation(path, 123456)
    assert await service.agent.request_pin_code(path) == "0000"
    assert await service.agent.request_passkey(path) == 0
    await service.agent.drain()
    assert (path, "org.bluez.Device1", "Trusted", True) in bus.sets
    # mauvais adaptateur (headsets) : refusé même fenêtre sources ouverte
    other = device_path(HP_PATH, "22:22:22:22:22:22")
    with pytest.raises(AgentRejected):
        await service.agent.request_authorization(other)
    service.agent.release()
    service.agent.cancel()


async def test_agent_respects_accept_incoming_false(config, bus: FakeBus):
    cfg = config.model_copy(
        update={"pairing": config.pairing.model_copy(update={"accept_incoming": False})}
    )
    svc = BluezService(cfg, bus, adapter_wait=0.2)
    await started(svc)
    await svc.pairing.open("sources", 30)
    with pytest.raises(AgentRejected):
        await svc.agent.request_authorization(device_path(SRC_PATH, PHONE_MAC))


async def test_agent_authorizes_service_for_trusted_device(service: BluezService, bus: FakeBus):
    await started(service)
    path = bus.add_device(SRC_PATH, PHONE_MAC, Paired=True, Trusted=True)
    await service.agent.authorize_service(
        path, "0000110b"
    )  # reconnexion d'un appareil de confiance
    untrusted = bus.add_device(SRC_PATH, "33:33:33:33:33:33", Paired=True)
    with pytest.raises(AgentRejected):
        await service.agent.authorize_service(untrusted, "0000110b")


async def test_agent_headsets_window_does_not_accept_incoming(service: BluezService, bus: FakeBus):
    await started(service)
    await service.pairing.open("headsets", 30)
    with pytest.raises(AgentRejected):
        await service.agent.request_authorization(device_path(HP_PATH, "22:22:22:22:22:22"))


# ----- pair / connect / forget -----------------------------------------------------------------
async def test_pair_requires_headsets_window_and_known_device(service: BluezService, bus: FakeBus):
    await started(service)
    with pytest.raises(WindowClosed):
        await service.pairing.pair(HEADSET_MAC)
    await service.pairing.open("sources", 10)
    with pytest.raises(WindowClosed):
        await service.pairing.pair(HEADSET_MAC)
    await service.pairing.close()
    await service.pairing.open("headsets", 10)
    with pytest.raises(NotFound):
        await service.pairing.pair(HEADSET_MAC)
    bus.add_device(SRC_PATH, "44:44:44:44:44:44", name="sur-sources")
    with pytest.raises(NotFound):  # vu sur l'adaptateur `sources` : pas un casque découvert
        await service.pairing.pair("44:44:44:44:44:44")


async def test_pair_flow_pair_trust_connect_and_agent_allows_outgoing(
    service: BluezService, bus: FakeBus
):
    await started(service)
    path = bus.add_device(HP_PATH, HEADSET_MAC, name="Bose", Class=0x240404)
    seen = {}

    async def pair(p: str, body: list) -> list:
        seen["allowed_during_pair"] = service.pairing.allows(p)
        await service.agent.request_confirmation(p, 0)
        bus.change(p, "org.bluez.Device1", Paired=True)
        return []

    bus.handlers[("org.bluez.Device1", "Pair")] = pair
    await service.pairing.open("headsets", 30)
    await service.pairing.pair(HEADSET_MAC)
    assert seen["allowed_during_pair"] is True
    assert not service.pairing.allows(path) and not service.pairing.is_outgoing(
        path
    )  # fin de session
    assert (path, "org.bluez.Device1", "Trusted", True) in bus.sets
    assert bus.calls_to("Connect")[0][0] == path


async def test_pair_already_paired_skips_pair_and_already_exists_is_ok(
    service: BluezService, bus: FakeBus
):
    await started(service)
    bus.add_device(HP_PATH, HEADSET_MAC, Paired=True)
    await service.pairing.open("headsets", 30)
    await service.pairing.pair(HEADSET_MAC)
    assert not bus.calls_to("Pair")
    bus.add_device(HP_PATH, "55:55:55:55:55:55", name="x")
    bus.errors[("org.bluez.Device1", "Pair")] = DBusCallError("org.bluez.Error.AlreadyExists")
    await service.pairing.pair("55:55:55:55:55:55")


async def test_pair_failure_is_wrapped(service: BluezService, bus: FakeBus):
    await started(service)
    bus.add_device(HP_PATH, HEADSET_MAC, name="Bose")
    bus.errors[("org.bluez.Device1", "Pair")] = DBusCallError(
        "org.bluez.Error.AuthenticationFailed", "bad"
    )
    await service.pairing.open("headsets", 30)
    with pytest.raises(BluezError, match="AuthenticationFailed"):
        await service.pairing.pair(HEADSET_MAC)


async def test_connect_bond_stale_vs_other_errors(service: BluezService, bus: FakeBus):
    await started(service)
    bus.add_device(HP_PATH, HEADSET_MAC, Paired=True)
    bus.errors[("org.bluez.Device1", "Connect")] = DBusCallError(
        "org.bluez.Error.AuthenticationFailed", "Key missing"
    )
    with pytest.raises(BondStale):
        await service.pairing.connect(HEADSET_MAC)
    bus.errors[("org.bluez.Device1", "Connect")] = DBusCallError(
        "org.bluez.Error.Failed", "page timeout"
    )
    with pytest.raises(BluezError, match="page timeout") as info:
        await service.pairing.connect(HEADSET_MAC)
    assert not isinstance(info.value, BondStale)
    bus.add_device(HP_PATH, "66:66:66:66:66:66")  # non appairé : pas BondStale
    bus.errors[("org.bluez.Device1", "Connect")] = DBusCallError(
        "org.bluez.Error.AuthenticationFailed"
    )
    with pytest.raises(BluezError) as info2:
        await service.pairing.connect("66:66:66:66:66:66")
    assert not isinstance(info2.value, BondStale)


async def test_disconnect_forget_trust_and_unknown(service: BluezService, bus: FakeBus):
    await started(service)
    path = bus.add_device(HP_PATH, HEADSET_MAC, Paired=True, Connected=True)
    await service.pairing.disconnect(HEADSET_MAC)
    assert bus.calls_to("Disconnect")[0][0] == path
    await service.pairing.set_trusted(HEADSET_MAC, True)
    assert (path, "org.bluez.Device1", "Trusted", True) in bus.sets
    await service.pairing.forget(HEADSET_MAC)
    assert bus.calls_to("RemoveDevice") == [(HP_PATH, [path])]
    for coro in (
        service.pairing.connect("00:00:00:00:00:09"),
        service.pairing.disconnect("00:00:00:00:00:09"),
        service.pairing.forget("00:00:00:00:00:09"),
        service.pairing.set_trusted("00:00:00:00:00:09", True),
    ):
        with pytest.raises(NotFound):
            await coro


async def test_action_errors_are_wrapped(service: BluezService, bus: FakeBus):
    await started(service)
    bus.add_device(HP_PATH, HEADSET_MAC, Paired=True)
    for key, call in (
        (("org.bluez.Device1", "Disconnect"), service.pairing.disconnect(HEADSET_MAC)),
        (("org.bluez.Adapter1", "RemoveDevice"), service.pairing.forget(HEADSET_MAC)),
    ):
        bus.errors[key] = DBusCallError("org.bluez.Error.Failed", "x")
        with pytest.raises(BluezError, match="Failed"):
            await call
    bus.set_errors[("org.bluez.Device1", "Trusted")] = DBusCallError("org.bluez.Error.Failed", "y")
    with pytest.raises(BluezError):
        await service.pairing.set_trusted(HEADSET_MAC, False)
    await service.pairing.trust_incoming(
        device_path(HP_PATH, HEADSET_MAC)
    )  # erreur absorbée (journal)


def test_error_classes_status_codes() -> None:
    assert (NotFound.status, WindowClosed.status, WindowOpen.status, BondStale.status) == (
        404,
        409,
        409,
        409,
    )
    assert BluezError.status == 502 and InvalidRequest.status == 400
