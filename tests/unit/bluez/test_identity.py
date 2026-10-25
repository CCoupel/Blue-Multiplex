"""B-2 (#23) : requêtes d'identité au hotplug — multi-lignes, vérification différée, abandon."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeBus, adapter_obj

from btmux.bluez.bus import BusSignal
from btmux.bluez.daemon import BluezService
from btmux.config import Config

SRC_PATH = "/org/bluez/hci1"
HP_PATH = "/org/bluez/hci0"
SRC = "AA:BB:CC:00:00:01"
HP = "AA:BB:CC:00:00:02"
OK_SOURCES = 0x6C0404
OK_HEADSETS = 0x6C010C


def make(config: Config, bus: FakeBus, tmp_path: Path) -> tuple[BluezService, Path]:
    cfg = config.model_copy(update={"state_path": tmp_path / "adapters.yaml"})
    service = BluezService(cfg, bus, adapter_wait=0.3, retry_interval=0.02)
    service.identity.verify_delay = 0.5
    service.identity.debounce = 0.02
    return service, tmp_path / "identity.request"


async def start(service: BluezService) -> None:
    assert await service._start_once() == []


def lines(request: Path) -> list[list[str]]:
    return [ln.split("\t") for ln in request.read_text().splitlines()]


def replug(bus: FakeBus, path: str, mac: str, **props: Any) -> None:
    ifaces = adapter_obj(mac, **props)
    bus.emit(BusSignal("interfaces_removed", path, None, ["org.bluez.Adapter1"]))
    bus.objects[path] = ifaces
    bus.emit(BusSignal("interfaces_added", path, None, ifaces))


async def wait_until(condition: Callable[[], object], timeout: float = 5.0) -> None:
    """Attente active bornée (robuste sous charge) plutôt qu'un `sleep` fixe."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition non atteinte dans le délai")
        await asyncio.sleep(0.01)


def count(caplog: pytest.LogCaptureFixture, event: str) -> int:
    return caplog.text.count(f"event={event} ")


async def test_hotplug_of_assigned_controller_writes_one_line(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request = make(config, bus, tmp_path)
    await start(service)
    assert not request.exists()  # rien au chargement initial
    replug(bus, SRC_PATH, SRC)
    await wait_until(lambda: count(caplog, "identity_requested") == 1)
    [[when, hci, mac]] = lines(request)
    assert (hci, mac) == ("hci1", SRC) and when.endswith("Z")
    assert oct(request.stat().st_mode & 0o777) == "0o640"
    assert [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    request.unlink()  # une propriété qui change (alias, classe correcte) ne redemande rien
    bus.change(SRC_PATH, "org.bluez.Adapter1", Alias="btmux", Class=OK_SOURCES)
    await asyncio.sleep(0.2)
    assert not request.exists() and count(caplog, "identity_requested") == 1


async def test_two_simultaneous_hotplugs_lose_no_mac(config, bus, tmp_path):
    service, request = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC)
    replug(bus, HP_PATH, HP)
    await wait_until(lambda: request.exists() and len(lines(request)) == 2)
    assert sorted(ln[2] for ln in lines(request)) == [SRC, HP]


async def test_late_second_hotplug_rewrites_the_whole_pending_set(config, bus, tmp_path):
    service, request = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC)
    await wait_until(request.exists)
    assert [ln[2] for ln in lines(request)] == [SRC]
    replug(
        bus, HP_PATH, HP
    )  # la première MAC n'est pas encore acquittée : elle reste dans le fichier
    await wait_until(lambda: len(lines(request)) == 2)
    assert sorted(ln[2] for ln in lines(request)) == [SRC, HP]


async def test_unassigned_controller_requests_nothing(config, bus, tmp_path):
    service, request = make(config, bus, tmp_path)
    bus.objects["/org/bluez/hci5"] = adapter_obj("AA:BB:CC:00:00:09", "raspberrypi")
    await start(service)
    ifaces = adapter_obj("AA:BB:CC:00:00:0A", "usb", Pairable=True)
    bus.objects["/org/bluez/hci6"] = ifaces
    bus.emit(BusSignal("interfaces_added", "/org/bluez/hci6", None, ifaces))
    bus.change("/org/bluez/hci5", "org.bluez.Adapter1", Class=0x0)
    await wait_until(
        lambda: ("/org/bluez/hci6", "org.bluez.Adapter1", "Pairable", False) in bus.sets
    )  # fermé
    await asyncio.sleep(0.3)
    assert not request.exists()


async def test_write_failure_is_logged_and_not_fatal(config, bus, tmp_path, caplog):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    cfg = config.model_copy(update={"state_path": blocker / "adapters.yaml"})
    service = BluezService(cfg, bus, adapter_wait=0.3, retry_interval=0.02)
    service.identity.debounce = 0.02
    await start(service)
    replug(bus, SRC_PATH, SRC)
    await wait_until(lambda: count(caplog, "identity_request_failed") == 1)
    await wait_until(
        lambda: ("/org/bluez/hci1", "org.bluez.Adapter1", "Pairable", False) in bus.sets
    )
    assert service.inventory.state()["controllers"]


async def test_correct_class_before_verification_acknowledges(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request = make(config, bus, tmp_path)
    service.identity.verify_delay = 1.0
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await wait_until(lambda: count(caplog, "identity_requested") == 1)
    bus.change(SRC_PATH, "org.bluez.Adapter1", Class=OK_SOURCES)  # la passe root a réussi
    await asyncio.sleep(1.3)  # au-delà de la vérification différée, annulée par l'acquittement
    assert count(caplog, "identity_requested") == 1 and count(caplog, "identity_giving_up") == 0


async def test_deferred_check_rerequests_then_gives_up_after_three(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request = make(config, bus, tmp_path)
    service.identity.verify_delay = 0.1
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)  # la classe ne sera jamais corrigée
    await wait_until(lambda: count(caplog, "identity_giving_up") == 1)
    assert count(caplog, "identity_requested") == 3  # 1 hotplug + 2 réémissions
    giving_up = [r for r in caplog.records if "identity_giving_up" in r.getMessage()]
    assert giving_up[0].levelno == logging.ERROR and f"mac={SRC}" in giving_up[0].getMessage()
    assert "attempts=3" in giving_up[0].getMessage()
    await asyncio.sleep(0.5)
    assert count(caplog, "identity_requested") == 3  # plus de quatrième tentative


async def test_deferred_check_stops_once_class_is_right(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request = make(config, bus, tmp_path)
    service.identity.verify_delay = 0.2
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await wait_until(
        lambda: count(caplog, "identity_requested") == 2
    )  # 1re vérification : 2e requête
    service.inventory._adapters[SRC_PATH]["Class"] = (
        OK_SOURCES  # lue par la vérification (sans signal)
    )
    await asyncio.sleep(0.8)
    assert count(caplog, "identity_requested") == 2 and count(caplog, "identity_giving_up") == 0


async def test_wrong_class_without_hotplug_does_not_start_an_episode(config, bus, tmp_path):
    service, request = make(config, bus, tmp_path)
    await start(service)
    bus.change(SRC_PATH, "org.bluez.Adapter1", Class=OK_SOURCES)
    bus.change(HP_PATH, "org.bluez.Adapter1", Class=OK_HEADSETS)
    bus.change(HP_PATH, "org.bluez.Adapter1", Class=OK_SOURCES)  # headsets seul attend 0x010c
    await asyncio.sleep(0.3)
    assert not request.exists()  # contrat : seule la vérification différée d'un épisode réémet


async def test_no_new_episode_after_giving_up_until_next_hotplug(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request = make(config, bus, tmp_path)
    service.identity.verify_delay = 0.1
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await wait_until(lambda: count(caplog, "identity_giving_up") == 1)
    assert count(caplog, "identity_requested") == 3
    bus.change(
        SRC_PATH, "org.bluez.Adapter1", Class=0x1
    )  # classe toujours fausse : abandon maintenu
    await asyncio.sleep(0.4)
    assert count(caplog, "identity_requested") == 3
    replug(bus, SRC_PATH, SRC, Class=0x0)  # nouvelle apparition : nouvel épisode
    await wait_until(lambda: count(caplog, "identity_requested") == 4)


async def test_no_request_while_roles_are_pending(config, bus, tmp_path, caplog):
    service, request = make(config, bus, tmp_path)
    service.identity.verify_delay = 0.1
    await start(service)
    service.inventory.mark_roles_pending(HP, SRC)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    bus.change(HP_PATH, "org.bluez.Adapter1", Class=0x0)
    await asyncio.sleep(0.5)
    assert not request.exists() and count(caplog, "identity_requested") == 0


async def test_pending_after_a_request_cancels_the_retry(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request = make(config, bus, tmp_path)
    service.identity.verify_delay = 0.3
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await wait_until(lambda: count(caplog, "identity_requested") == 1)
    service.inventory.mark_roles_pending(HP, SRC)  # un changement de rôles est écrit entre-temps
    await asyncio.sleep(0.9)
    assert count(caplog, "identity_requested") == 1 and count(caplog, "identity_giving_up") == 0


async def test_teardown_cancels_pending_verification(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request = make(config, bus, tmp_path)
    service.identity.verify_delay = 0.4
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await wait_until(lambda: count(caplog, "identity_requested") == 1)
    await service._teardown()
    await asyncio.sleep(0.9)
    assert count(caplog, "identity_requested") == 1
