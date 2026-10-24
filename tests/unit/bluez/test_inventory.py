from __future__ import annotations

import asyncio

from fakes import (
    A2DP_SINK,
    A2DP_SOURCE,
    HEADSET_MAC,
    HFP_AG,
    HP_PATH,
    PHONE_MAC,
    SRC_PATH,
    FakeBus,
    device_path,
)

from btmux import __version__
from btmux.bluez.adapters import AdapterRegistry
from btmux.bluez.bus import BusSignal
from btmux.bluez.daemon import BluezService
from btmux.bluez.models import deduce_kind, format_class, profiles_from_uuids
from btmux.config import parse_config


async def started(service: BluezService) -> BluezService:
    assert await service._start_once() == []
    return service


def test_deduce_kind_and_profiles() -> None:
    assert deduce_kind(0x240404, [A2DP_SINK]) == "headset"
    assert deduce_kind(0x240404, []) == "unknown"
    assert deduce_kind(None, [A2DP_SINK]) == "unknown"
    assert deduce_kind(0x5A020C, [A2DP_SOURCE]) == "source"
    assert deduce_kind(0, [HFP_AG]) == "source"
    assert profiles_from_uuids([A2DP_SINK.upper(), "zzz", HFP_AG]) == ["a2dp_sink", "hfp_ag"]
    assert format_class(0x6C0404) == "0x6c0404" and format_class(None) is None


async def test_state_lists_adapters_and_config_devices(service: BluezService) -> None:
    await started(service)
    state = service.inventory.state()
    assert state["version"] == __version__ and state["pairing"] == {
        "open": False,
        "adapter": None,
        "closed_at": None,
        "reason": None,
    }
    roles = {a["role"]: a for a in state["adapters"]}
    assert roles["sources"]["hci"] == "hci1" and roles["headsets"]["mac"] == "AA:BB:CC:00:00:02"
    assert roles["sources"]["class"] == "0x6c0404" and roles["sources"]["powered"] is True
    devices = {d["mac"]: d for d in state["devices"]}
    # appareils de la config absents de BlueZ : présents, non appairés
    assert devices[PHONE_MAC]["in_config"] is True and devices[PHONE_MAC]["paired"] is False
    assert (
        devices[PHONE_MAC]["alias"] == "pc-pro"
        and devices[PHONE_MAC]["name"] is None
        and devices[PHONE_MAC]["adapter"] == "sources"
    )
    assert devices[HEADSET_MAC]["adapter"] == "headsets"


async def test_device_events_and_models(service: BluezService, bus: FakeBus) -> None:
    await started(service)
    sub = service.inventory.subscribe()
    path = bus.add_device(
        SRC_PATH, "AA:AA:AA:AA:AA:01", name="S24", Paired=True, UUIDs=[A2DP_SOURCE], Class=0x5A020C
    )
    event = sub.queue.get_nowait()
    assert event.kind == "device"
    assert event.data["kind"] == "source" and event.data["in_config"] is False
    assert event.data["profiles"] == ["a2dp_source"] and event.data["last_seen"] is None
    bus.change(path, "org.bluez.Device1", Connected=True)
    ev2 = sub.queue.get_nowait()
    assert ev2.id == event.id + 1 and ev2.data["connected"] is True and ev2.data["last_seen"]
    bus.change(path, "org.bluez.Device1", RSSI=-50)  # RSSI seul : pas d'évènement
    assert sub.queue.empty()
    bus.remove_device(path)
    gone = sub.queue.get_nowait()
    assert gone.kind == "device.removed" and gone.data == {
        "mac": "AA:AA:AA:AA:AA:01",
        "adapter": "sources",
    }
    assert sub.queue.empty()  # hors config : pas de placeholder
    assert "AA:AA:AA:AA:AA:01" not in {d["mac"] for d in service.inventory.state()["devices"]}


async def test_unknown_device_is_not_in_state_but_discovered_when_collecting(
    service: BluezService, bus: FakeBus
) -> None:
    await started(service)
    inv = service.inventory
    sub = inv.subscribe()
    bus.add_device(HP_PATH, "BB:BB:BB:BB:BB:01", name="Bose QC45", Class=0x240404, RSSI=-60)
    assert sub.queue.empty() and inv.discovered() == []  # hors fenêtre : ignoré
    inv.set_discovery_collection(True)  # recense l'existant
    assert [d.mac for d in inv.discovered()] == ["BB:BB:BB:BB:BB:01"]
    assert sub.queue.get_nowait().kind == "discovered"
    p2 = bus.add_device(HP_PATH, "BB:BB:BB:BB:BB:02", name="JBL", Class=0x240404, RSSI=-40)
    assert sub.queue.get_nowait().data["name"] == "JBL"
    assert [d.mac for d in inv.discovered()] == ["BB:BB:BB:BB:BB:02", "BB:BB:BB:BB:BB:01"]  # RSSI
    bus.change(p2, "org.bluez.Device1", Name="JBL 2", RSSI=-41)
    bus.change(p2, "org.bluez.Device1", Paired=True)  # devient connu : sort des découverts
    assert [d.mac for d in inv.discovered()] == ["BB:BB:BB:BB:BB:01"]
    assert any(d["mac"] == "BB:BB:BB:BB:BB:02" for d in inv.state()["devices"])
    inv.set_discovery_collection(False)
    assert inv.discovered() == []
    # un appareil sur l'adaptateur `sources` n'est jamais « découvert »
    inv.set_discovery_collection(True)
    bus.add_device(SRC_PATH, "CC:CC:CC:CC:CC:01", name="x")
    assert all(d.mac != "CC:CC:CC:CC:CC:01" for d in inv.discovered())


async def test_adapter_events_alias_overlay_and_overflow(
    service: BluezService, bus: FakeBus, config
) -> None:
    await started(service)
    inv = service.inventory
    sub = inv.subscribe()
    bus.change(SRC_PATH, "org.bluez.Adapter1", Discoverable=True)
    ev = sub.queue.get_nowait()
    assert ev.kind == "adapter" and ev.data["discoverable"] is True
    path = device_path(SRC_PATH, PHONE_MAC)
    bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True)
    sub.queue.get_nowait()
    inv.set_alias(PHONE_MAC, "pc-maison")
    assert sub.queue.get_nowait().data["alias"] == "pc-maison"
    inv.set_alias(PHONE_MAC, None)
    assert sub.queue.get_nowait().data["alias"] == "pc-pro"  # retour à l'alias de la config
    inv.set_alias("DE:AD:BE:EF:00:00", "x")  # inconnu de BlueZ : mémorisé sans évènement
    assert inv.device_path(PHONE_MAC) == path and inv.device_path("00:00:00:00:00:00") is None
    sub.close()
    bus.change(SRC_PATH, "org.bluez.Adapter1", Pairable=True)
    assert sub.queue.empty()
    # débordement : l'abonné est éjecté
    slow = inv.subscribe()
    for _ in range(1100):
        inv.emit("adapter", {})
    assert slow.overflowed is True


async def test_signals_for_unmanaged_objects_are_ignored(
    service: BluezService, bus: FakeBus
) -> None:
    await started(service)
    inv = service.inventory
    sub = inv.subscribe()
    bus.add_device("/org/bluez/hci9", "DD:DD:DD:DD:DD:01", Paired=True)
    inv.handle(BusSignal("properties_changed", "/nope", "org.bluez.Device1", {"Paired": True}))
    inv.handle(
        BusSignal("interfaces_removed", "/org/bluez/hci9/dev_x", None, ["org.bluez.Device1"])
    )
    inv.handle(BusSignal("interfaces_removed", "/org/bluez/hci0", None, ["org.bluez.Adapter1"]))
    assert sub.queue.empty()
    assert inv.device_path("DD:DD:DD:DD:DD:01") is None


async def test_mono_adapter_exposes_one_entry_per_role_and_classifies_by_kind() -> None:
    cfg = parse_config(
        {
            "adapters": [
                {"mac": "AA:BB:CC:00:00:01", "name": "btmux", "roles": ["sources", "headsets"]}
            ]
        }
    )
    bus = FakeBus(
        {SRC_PATH: {"org.bluez.Adapter1": {"Address": "AA:BB:CC:00:00:01", "Alias": "btmux"}}}
    )
    svc = BluezService(cfg, bus, adapter_wait=0.2)
    await started(svc)
    assert sorted(a["role"] for a in svc.inventory.state()["adapters"]) == ["headsets", "sources"]
    bus.add_device(
        SRC_PATH, "EE:EE:EE:EE:EE:01", name="H", Paired=True, Class=0x240404, UUIDs=[A2DP_SINK]
    )
    bus.add_device(SRC_PATH, "EE:EE:EE:EE:EE:02", name="P", Paired=True)
    by_mac = {d["mac"]: d for d in svc.inventory.state()["devices"]}
    assert by_mac["EE:EE:EE:EE:EE:01"]["adapter"] == "headsets"
    assert by_mac["EE:EE:EE:EE:EE:02"]["adapter"] == "sources"


def test_registry_reports_missing_adapters(config) -> None:
    reg = AdapterRegistry(config)
    assert reg.update({SRC_PATH: {"org.bluez.Adapter1": {"Address": "aa:bb:cc:00:00:01"}}}) == [
        "AA:BB:CC:00:00:02"
    ]
    assert reg.path_for("sources") == SRC_PATH and reg.path_for("headsets") is None
    assert reg.paths() == {SRC_PATH} and reg.info_for_path("/x") is None
    assert asyncio.iscoroutinefunction(started)


async def test_forget_of_config_device_emits_removed_then_placeholder(
    service: BluezService, bus: FakeBus
) -> None:
    await started(service)
    path = bus.add_device(SRC_PATH, PHONE_MAC, name="PC", Paired=True, Trusted=True)
    sub = service.inventory.subscribe()
    bus.remove_device(path)
    removed, placeholder = sub.queue.get_nowait(), sub.queue.get_nowait()
    assert removed.kind == "device.removed" and removed.data["mac"] == PHONE_MAC
    assert placeholder.kind == "device" and placeholder.data["name"] is None
    assert placeholder.data["paired"] is False and placeholder.data["in_config"] is True
    assert placeholder.data["uuids"] == [] and placeholder.data["alias"] == "pc-pro"
