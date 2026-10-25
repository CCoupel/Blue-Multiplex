"""B-2 (#23) : requêtes d'identité au hotplug (multi-lignes, différé, abandon, vidage).

Déterministe, sans attente réelle : le temps (débounce 1 s, vérification à +60 s) est piloté par une
`FakeClock` injectée dans `IdentityRequester`, et les écritures du fichier sont exécutées en ligne.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeBus, adapter_obj

from btmux.bluez.bus import BusSignal
from btmux.bluez.daemon import BluezService
from btmux.config import Config, write_identity_requests

SRC_PATH = "/org/bluez/hci1"
HP_PATH = "/org/bluez/hci0"
SRC = "AA:BB:CC:00:00:01"
HP = "AA:BB:CC:00:00:02"
OK_SOURCES = 0x6C0404
OK_HEADSETS = 0x6C010C
DEBOUNCE = 1.0
VERIFY = 60.0


class FakeClock:
    """Planificateur manuel : `sleep` ne rend la main que lorsque `advance` franchit l'échéance."""

    def __init__(self) -> None:
        self.now = 0.0
        self._waiters: list[tuple[float, asyncio.Future[None]]] = []

    async def sleep(self, delay: float) -> None:
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append((self.now + delay, fut))
        await fut

    async def settle(self) -> None:
        """Laisse s'exécuter toutes les tâches prêtes (aucune attente réelle)."""
        for _ in range(60):
            await asyncio.sleep(0)

    async def advance(self, seconds: float) -> None:
        target = self.now + seconds
        await self.settle()
        while True:
            self._waiters = [w for w in self._waiters if not w[1].done()]  # sommeils annulés
            due = sorted((w for w in self._waiters if w[0] <= target), key=lambda w: w[0])
            if not due:
                break
            deadline, fut = due[0]
            self._waiters.remove(due[0])
            self.now = max(self.now, deadline)
            fut.set_result(None)
            await self.settle()
        self.now = target


async def inline_write(path: Path, entries: Sequence[tuple[str, str, str]]) -> None:
    write_identity_requests(path, entries)  # fichier local, sans thread : déterministe


def make(config: Config, bus: FakeBus, tmp_path: Path) -> tuple[BluezService, Path, FakeClock]:
    cfg = config.model_copy(update={"state_path": tmp_path / "adapters.yaml"})
    return wire(BluezService(cfg, bus, adapter_wait=0.3, retry_interval=0.02), tmp_path)


def wire(service: BluezService, tmp_path: Path) -> tuple[BluezService, Path, FakeClock]:
    clock = FakeClock()
    service.identity.sleep = clock.sleep
    service.identity.write = inline_write
    service.identity.debounce = DEBOUNCE
    service.identity.verify_delay = VERIFY
    return service, tmp_path / "identity.request", clock


async def start(service: BluezService) -> None:
    assert await service._start_once() == []


def lines(request: Path) -> list[list[str]]:
    return [ln.split("\t") for ln in request.read_text().splitlines()]


def replug(bus: FakeBus, path: str, mac: str, **props: Any) -> None:
    ifaces = adapter_obj(mac, **props)
    bus.emit(BusSignal("interfaces_removed", path, None, ["org.bluez.Adapter1"]))
    bus.objects[path] = ifaces
    bus.emit(BusSignal("interfaces_added", path, None, ifaces))


def count(caplog: pytest.LogCaptureFixture, event: str) -> int:
    return caplog.text.count(f"event={event} ")


async def test_hotplug_of_assigned_controller_writes_one_line(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    assert not request.exists()  # rien au chargement initial
    replug(bus, SRC_PATH, SRC)
    await clock.settle()
    assert not request.exists()  # écriture différée par le débounce
    await clock.advance(DEBOUNCE)
    [[when, hci, mac]] = lines(request)
    assert (hci, mac) == ("hci1", SRC) and when.endswith("Z")
    assert oct(request.stat().st_mode & 0o777) == "0o640"
    assert [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    # classe correcte observée : acquittement, le fichier est vidé (aucune nouvelle requête)
    bus.change(SRC_PATH, "org.bluez.Adapter1", Alias="btmux", Class=OK_SOURCES)
    await clock.advance(DEBOUNCE)
    assert request.read_text() == "" and count(caplog, "identity_requested") == 1


async def test_two_simultaneous_hotplugs_lose_no_mac(config, bus, tmp_path):
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC)
    replug(bus, HP_PATH, HP)
    await clock.advance(DEBOUNCE)
    assert sorted(ln[2] for ln in lines(request)) == [SRC, HP]


async def test_late_second_hotplug_rewrites_the_whole_pending_set(config, bus, tmp_path):
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC)
    await clock.advance(DEBOUNCE)
    assert [ln[2] for ln in lines(request)] == [SRC]
    replug(
        bus, HP_PATH, HP
    )  # la première MAC n'est pas encore acquittée : elle reste dans le fichier
    await clock.advance(DEBOUNCE)
    assert sorted(ln[2] for ln in lines(request)) == [SRC, HP]


async def test_unassigned_controller_requests_nothing(config, bus, tmp_path):
    service, request, clock = make(config, bus, tmp_path)
    bus.objects["/org/bluez/hci5"] = adapter_obj("AA:BB:CC:00:00:09", "raspberrypi")
    await start(service)
    ifaces = adapter_obj("AA:BB:CC:00:00:0A", "usb", Pairable=True)
    bus.objects["/org/bluez/hci6"] = ifaces
    bus.emit(BusSignal("interfaces_added", "/org/bluez/hci6", None, ifaces))
    bus.change("/org/bluez/hci5", "org.bluez.Adapter1", Class=0x0)
    await clock.advance(600)
    assert not request.exists()
    assert ("/org/bluez/hci6", "org.bluez.Adapter1", "Pairable", False) in bus.sets  # fermé


async def test_write_failure_is_logged_and_not_fatal(config, bus, tmp_path, caplog):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    cfg = config.model_copy(update={"state_path": blocker / "adapters.yaml"})
    service, _, clock = wire(
        BluezService(cfg, bus, adapter_wait=0.3, retry_interval=0.02), tmp_path
    )
    await start(service)
    replug(bus, SRC_PATH, SRC)
    await clock.advance(DEBOUNCE)
    assert count(caplog, "identity_request_failed") == 1
    assert ("/org/bluez/hci1", "org.bluez.Adapter1", "Pairable", False) in bus.sets
    assert service.inventory.state()["controllers"]


async def test_correct_class_before_verification_acknowledges(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await clock.advance(DEBOUNCE)
    bus.change(SRC_PATH, "org.bluez.Adapter1", Class=OK_SOURCES)  # la passe root a réussi
    await clock.advance(
        10 * VERIFY
    )  # bien au-delà de la vérification différée, annulée par l'acquittement
    assert count(caplog, "identity_requested") == 1 and count(caplog, "identity_giving_up") == 0


async def test_deferred_check_rerequests_then_gives_up_after_three(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)  # la classe ne sera jamais corrigée
    await clock.advance(3 * VERIFY + 10)
    assert count(caplog, "identity_requested") == 3  # 1 hotplug + 2 réémissions
    giving_up = [r for r in caplog.records if "identity_giving_up" in r.getMessage()]
    assert len(giving_up) == 1 and giving_up[0].levelno == logging.ERROR
    assert f"mac={SRC}" in giving_up[0].getMessage() and "attempts=3" in giving_up[0].getMessage()
    await clock.advance(10 * VERIFY)
    assert count(caplog, "identity_requested") == 3  # plus de quatrième tentative


async def test_deferred_check_stops_once_class_is_right(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await clock.advance(VERIFY + DEBOUNCE)  # 1re vérification : mauvaise classe → 2e requête
    assert count(caplog, "identity_requested") == 2
    service.inventory._adapters[SRC_PATH]["Class"] = (
        OK_SOURCES  # lue par la vérification (sans signal)
    )
    await clock.advance(10 * VERIFY)
    assert count(caplog, "identity_requested") == 2 and count(caplog, "identity_giving_up") == 0


async def test_wrong_class_without_hotplug_does_not_start_an_episode(config, bus, tmp_path):
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    bus.change(SRC_PATH, "org.bluez.Adapter1", Class=OK_SOURCES)
    bus.change(HP_PATH, "org.bluez.Adapter1", Class=OK_HEADSETS)
    bus.change(HP_PATH, "org.bluez.Adapter1", Class=OK_SOURCES)  # headsets seul attend 0x010c
    await clock.advance(10 * VERIFY)
    assert not request.exists()  # contrat : seule la vérification différée d'un épisode réémet


async def test_no_new_episode_after_giving_up_until_next_hotplug(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await clock.advance(3 * VERIFY + 10)
    assert count(caplog, "identity_giving_up") == 1 and count(caplog, "identity_requested") == 3
    bus.change(
        SRC_PATH, "org.bluez.Adapter1", Class=0x1
    )  # classe toujours fausse : abandon maintenu
    await clock.advance(10 * VERIFY)
    assert count(caplog, "identity_requested") == 3
    replug(bus, SRC_PATH, SRC, Class=0x0)  # nouvelle apparition : nouvel épisode
    await clock.advance(DEBOUNCE)
    assert count(caplog, "identity_requested") == 4


async def test_no_request_while_roles_are_pending(config, bus, tmp_path, caplog):
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    service.inventory.mark_roles_pending(HP, SRC)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    bus.change(HP_PATH, "org.bluez.Adapter1", Class=0x0)
    await clock.advance(10 * VERIFY)
    assert not request.exists() and count(caplog, "identity_requested") == 0


async def test_pending_after_a_request_cancels_the_retry(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await clock.advance(DEBOUNCE)
    assert count(caplog, "identity_requested") == 1
    service.inventory.mark_roles_pending(HP, SRC)  # un changement de rôles est écrit entre-temps
    await clock.advance(10 * VERIFY)
    assert count(caplog, "identity_requested") == 1 and count(caplog, "identity_giving_up") == 0


async def test_teardown_cancels_pending_verification(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await clock.advance(DEBOUNCE)
    await service._teardown()
    await clock.advance(10 * VERIFY)
    assert count(caplog, "identity_requested") == 1


# ----- fichier vidé après acquittement -----
async def test_file_is_emptied_once_the_class_is_acknowledged(config, bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await clock.advance(DEBOUNCE)
    assert lines(request)
    bus.change(SRC_PATH, "org.bluez.Adapter1", Class=OK_SOURCES)  # acquittement
    await clock.advance(DEBOUNCE)
    assert request.read_text() == ""
    assert count(caplog, "identity_requested") == 1  # l'écriture de vidage n'est pas une requête
    mtime = request.stat().st_mtime_ns
    bus.change(
        SRC_PATH, "org.bluez.Adapter1", Class=OK_SOURCES
    )  # déjà acquitté : pas de réécriture
    await clock.advance(10 * VERIFY)
    assert request.stat().st_mtime_ns == mtime


async def test_ack_of_one_mac_keeps_the_other_pending(config, bus, tmp_path):
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    replug(bus, HP_PATH, HP, Class=0x0)
    await clock.advance(DEBOUNCE)
    assert len(lines(request)) == 2
    bus.change(HP_PATH, "org.bluez.Adapter1", Class=OK_HEADSETS)
    await clock.advance(DEBOUNCE)
    assert [ln[2] for ln in lines(request)] == [SRC]
    bus.change(SRC_PATH, "org.bluez.Adapter1", Class=OK_SOURCES)
    await clock.advance(DEBOUNCE)
    assert request.read_text() == ""


async def test_file_is_emptied_after_giving_up(config, bus, tmp_path, caplog):
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await clock.advance(3 * VERIFY + 10)
    assert count(caplog, "identity_giving_up") == 1
    assert request.read_text() == ""


async def test_deferred_check_acknowledges_and_empties(config, bus, tmp_path):
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await clock.advance(DEBOUNCE)
    assert lines(request)
    service.inventory._adapters[SRC_PATH]["Class"] = (
        OK_SOURCES  # lue par la vérification (sans signal)
    )
    await clock.advance(VERIFY + DEBOUNCE)
    assert request.read_text() == ""


async def test_ack_before_the_file_was_written_writes_nothing(config, bus, tmp_path):
    service, request, clock = make(config, bus, tmp_path)
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await clock.settle()  # requête enregistrée, écriture différée (débounce)
    bus.change(SRC_PATH, "org.bluez.Adapter1", Class=OK_SOURCES)  # acquitté avant l'écriture
    await clock.advance(10 * VERIFY)
    assert not request.exists()


async def test_request_issued_during_a_slow_write_is_not_lost(config, bus, tmp_path, caplog):
    """Régression (CI 3.14 : 2 == 3) : une réémission pendant une écriture lente était retirée du
    journal par le nettoyage de l'écriture en cours."""
    caplog.set_level(logging.INFO)
    service, request, clock = make(config, bus, tmp_path)
    gate = asyncio.Event()
    first = True

    async def slow_write(path: Path, entries: Sequence[tuple[str, str, str]]) -> None:
        nonlocal first
        if first:
            first = False
            await gate.wait()  # l'écriture de la requête n°1 traîne (machine chargée)
        write_identity_requests(path, entries)

    service.identity.write = slow_write
    await start(service)
    replug(bus, SRC_PATH, SRC, Class=0x0)
    await clock.advance(DEBOUNCE)  # écriture n°1 démarrée, bloquée
    await clock.advance(
        VERIFY
    )  # vérification : mauvaise classe → requête n°2 pendant l'écriture n°1
    gate.set()
    await clock.advance(DEBOUNCE)
    assert count(caplog, "identity_requested") == 2
    assert [ln[2] for ln in lines(request)] == [SRC]
    await clock.advance(3 * VERIFY)
    assert count(caplog, "identity_requested") == 3  # 3 tentatives exactement, puis abandon
    assert count(caplog, "identity_giving_up") == 1
