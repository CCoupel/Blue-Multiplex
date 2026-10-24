"""BluezService : démarre bus + inventaire + agent + gestionnaire d'appairage et les maintient (reconnexion BlueZ)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from btmux.bluez.adapters import ADAPTER_IFACE, AdapterRegistry
from btmux.bluez.agent import AGENT_CAPABILITY, AGENT_PATH, Agent
from btmux.bluez.bus import Bus, BusSignal, DBusCallError, DBusFastBus
from btmux.bluez.errors import AdaptersNotFound, BluezError
from btmux.bluez.inventory import Inventory
from btmux.bluez.pairing import PairingManager
from btmux.config import Config
from btmux.log import kv

log = logging.getLogger("btmux.bluez")

EXIT_OK = 0
EXIT_ADAPTER_NOT_FOUND = 3
DEFAULT_ADAPTER_WAIT = 30.0
ENV_ADAPTER_WAIT = "BTMUX_ADAPTER_WAIT"


def adapter_wait_from_env() -> float:
    try:
        return float(os.environ.get(ENV_ADAPTER_WAIT, DEFAULT_ADAPTER_WAIT))
    except ValueError:
        return DEFAULT_ADAPTER_WAIT


class BluezService:
    def __init__(
        self,
        config: Config,
        bus: Bus | None = None,
        *,
        adapter_wait: float | None = None,
        retry_interval: float = 1.0,
    ) -> None:
        self.config = config
        self.bus: Bus = bus if bus is not None else DBusFastBus()
        self.registry = AdapterRegistry(config)
        self.inventory = Inventory(config, self.registry)
        self.pairing = PairingManager(self.bus, self.registry, self.inventory, config.pairing)
        self.agent = Agent(self.pairing, self.inventory)
        self.adapter_wait = adapter_wait_from_env() if adapter_wait is None else adapter_wait
        self.retry_interval = retry_interval
        self.ready = asyncio.Event()
        self._lost = asyncio.Event()
        self._handlers_installed = False

    # ----- démarrage / arrêt -----------------------------------------------------------------
    def _on_signal(self, signal: BusSignal) -> None:
        if signal.kind == "name_owner_changed":
            if not signal.data[1]:  # BlueZ a quitté le bus
                log.warning(kv("bluez_lost"))
                self._lost.set()
            return
        self.inventory.handle(signal)

    async def _start_once(self) -> list[str]:
        """Connexion + inventaire + agent ; retourne les MAC d'adaptateurs absents (liste vide = OK)."""
        if not self._handlers_installed:
            self.bus.on_signal(self._on_signal)
            self.bus.on_disconnect(self._lost.set)
            self._handlers_installed = True
        await self.bus.connect()
        try:
            return await self._start_connected()
        except BaseException:
            await self.bus.close()  # pas de connexion D-Bus laissée ouverte entre deux tentatives
            raise

    async def _start_connected(self) -> list[str]:
        objects = await self.bus.get_managed_objects()
        missing = self.registry.update(objects)
        if missing:
            await self.bus.close()
            return missing
        self.inventory.load(objects)
        for info in self.registry.infos:
            assert info.path is not None
            # État sûr au démarrage : alimenté, découverte et appairage fermés (c'est btmuxd qui ouvre).
            for prop, value in (("Powered", True), ("Pairable", False), ("Discoverable", False)):
                with contextlib.suppress(DBusCallError):
                    await self.bus.set_property(info.path, ADAPTER_IFACE, prop, "b", value)
        await self.bus.export_agent(AGENT_PATH, self.agent)
        await self.bus.call(
            "/org/bluez",
            "org.bluez.AgentManager1",
            "RegisterAgent",
            "os",
            [AGENT_PATH, AGENT_CAPABILITY],
        )
        await self.bus.call(
            "/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent", "o", [AGENT_PATH]
        )
        log.info(kv("bluez_ready", adapters=len(self.registry.infos)))
        return []

    async def _teardown(self) -> None:
        with contextlib.suppress(Exception):
            await self.pairing.close()
        with contextlib.suppress(Exception):
            await self.bus.call(
                "/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent", "o", [AGENT_PATH]
            )
        with contextlib.suppress(Exception):
            await self.bus.unexport_agent(AGENT_PATH)
        with contextlib.suppress(Exception):
            await self.bus.close()
        await self.agent.drain()

    async def run(self, stop: asyncio.Event) -> int:
        """Boucle principale : démarre, surveille, redémarre si BlueZ disparaît. Retourne le code de sortie."""
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            deadline = loop.time() + self.adapter_wait
            missing: list[str] = []
            while True:
                try:
                    missing = await self._start_once()
                except BluezError as exc:
                    missing = [f"bluez unavailable ({exc})"]
                except DBusCallError as exc:
                    missing = [f"bluez error ({exc})"]
                if not missing or stop.is_set():
                    break
                if loop.time() >= deadline:
                    log.error(kv("adapter_not_found", missing=",".join(missing)))
                    raise AdaptersNotFound(missing)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self.retry_interval)
                if stop.is_set():
                    break
            if stop.is_set():
                await self._teardown()
                return EXIT_OK
            self._lost.clear()
            self.ready.set()
            waiters = {asyncio.ensure_future(stop.wait()), asyncio.ensure_future(self._lost.wait())}
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            for w in waiters:
                w.cancel()
            self.ready.clear()
            await self._teardown()
            if stop.is_set():
                return EXIT_OK
            log.warning(kv("bluez_reconnect"))
            await asyncio.sleep(self.retry_interval)
        await self._teardown()
        return EXIT_OK
