"""BluezService : démarre bus + inventaire + agent + gestionnaire d'appairage et les maintient (reconnexion BlueZ)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from btmux.bluez.adapters import ADAPTER_IFACE, AdapterRegistry
from btmux.bluez.agent import AGENT_CAPABILITY, AGENT_PATH, Agent
from btmux.bluez.bus import Bus, BusSignal, DBusCallError, DBusFastBus
from btmux.bluez.controllers import RoleManager
from btmux.bluez.errors import AdaptersNotFound, BluezError
from btmux.bluez.inventory import Inventory
from btmux.bluez.pairing import PairingManager
from btmux.config import Config
from btmux.log import kv

log = logging.getLogger("btmux.bluez")

EXIT_OK = 0
EXIT_ADAPTER_NOT_FOUND = 3
EXIT_RESTART_FALLBACK = (
    4  # redémarrage piloté non reçu : systemd relance (RestartForceExitStatus=4)
)
RESTART_TIMEOUT_S = 20.0
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
        restart_timeout: float = RESTART_TIMEOUT_S,
    ) -> None:
        self.restart_timeout = restart_timeout
        self._fallback = asyncio.Event()
        self._restart_task: asyncio.Task[None] | None = None
        self.config = config
        self.bus: Bus = bus if bus is not None else DBusFastBus()
        self.registry = AdapterRegistry(config)
        self.inventory = Inventory(config, self.registry)
        self.pairing = PairingManager(self.bus, self.registry, self.inventory, config.pairing)
        self.agent = Agent(self.pairing, self.inventory)
        self.roles = RoleManager(config, self.inventory, self.pairing, self.on_roles_written)
        self.adapter_wait = adapter_wait_from_env() if adapter_wait is None else adapter_wait
        self.retry_interval = retry_interval
        self.ready = asyncio.Event()
        self._lost = asyncio.Event()
        self._handlers_installed = False
        self._guards: set[asyncio.Future[None]] = set()

    def on_roles_written(self) -> None:
        """L'état des rôles vient d'être écrit : `btmux-adapters.path` doit relancer le service (SIGTERM) ;
        sans signal dans `restart_timeout` s, repli : sortie code 4 (journal `restart_fallback`)."""
        if self._restart_task is None:
            self._restart_task = asyncio.create_task(self._restart_watch())

    async def _restart_watch(self) -> None:
        await asyncio.sleep(self.restart_timeout)
        log.error(
            kv("restart_fallback", after_s=self.restart_timeout, exit_code=EXIT_RESTART_FALLBACK)
        )
        self._fallback.set()

    # ----- démarrage / arrêt -----------------------------------------------------------------
    def _on_signal(self, signal: BusSignal) -> None:
        if signal.kind == "name_owner_changed":
            if not signal.data[1]:  # BlueZ a quitté le bus
                log.warning(kv("bluez_lost"))
                self._lost.set()
            return
        self.inventory.handle(signal)
        self._guard_controller(signal)

    def _guard_controller(self, signal: BusSignal) -> None:
        """Hotplug / réouverture : tout contrôleur sans rôle reste fermé (#23) ; un contrôleur affecté qui
        apparaît est mis dans l'état sûr (alimenté, appairage et découverte fermés)."""
        opened = {"Pairable", "Discoverable"} & set(
            signal.data
            if signal.kind == "properties_changed" and isinstance(signal.data, dict)
            else ()
        )
        if signal.kind == "interfaces_added" and ADAPTER_IFACE in signal.data:
            pass
        elif not (
            signal.kind == "properties_changed"
            and signal.interface == ADAPTER_IFACE
            and opened
            and self.registry.info_for_path(signal.path) is None
            and any(signal.data[p] for p in opened)
        ):
            return
        task = asyncio.ensure_future(self._close_controller(signal.path))
        self._guards.add(task)
        task.add_done_callback(self._guards.discard)

    async def _close_controller(self, path: str) -> None:
        assigned = self.registry.info_for_path(path) is not None
        props = (("Powered", True),) if assigned else ()
        for prop, value in (*props, ("Pairable", False), ("Discoverable", False)):
            with contextlib.suppress(DBusCallError, BluezError):
                await self.bus.set_property(path, ADAPTER_IFACE, prop, "b", value)
        log.info(kv("controller_closed", path=path, assigned=assigned))

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
        for mac in self.registry.update(
            objects
        ):  # tolérant (#23) : rôle non affecté, pas de code 3
            log.warning(kv("adapter_missing", mac=mac))
        self.inventory.load(objects)
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
        log.info(kv("agent_registered", path=AGENT_PATH, capability=AGENT_CAPABILITY))
        # BlueZ passe Pairable à vrai dès qu'un agent est enregistré : l'état sûr (alimenté, appairage et
        # découverte fermés) doit donc être posé APRÈS l'enregistrement, et vérifié.
        await self._close_adapters()
        log.info(kv("bluez_ready", adapters=sum(i.present for i in self.registry.infos)))
        return []

    async def _close_adapters(self) -> None:
        """Alimente les adaptateurs, ferme appairage et découverte, puis le vérifie (3 essais)."""
        for _ in range(3):
            for info in self.registry.infos:
                if info.path is None:
                    continue
                for prop, value in (
                    ("Powered", True),
                    ("Pairable", False),
                    ("Discoverable", False),
                ):
                    with contextlib.suppress(DBusCallError):
                        await self.bus.set_property(info.path, ADAPTER_IFACE, prop, "b", value)
            for path in self.inventory.unassigned_adapter_paths():  # contrôleurs sans rôle : fermés
                for prop in ("Pairable", "Discoverable"):
                    with contextlib.suppress(DBusCallError):
                        await self.bus.set_property(path, ADAPTER_IFACE, prop, "b", False)
            objects = await self.bus.get_managed_objects()
            watched = [i.path for i in self.registry.infos if i.path]
            watched += self.inventory.unassigned_adapter_paths()
            open_ = [
                str(objects[path][ADAPTER_IFACE].get("Address", path))
                for path in watched
                if objects.get(path, {}).get(ADAPTER_IFACE, {}).get("Pairable")
                or objects.get(path, {}).get(ADAPTER_IFACE, {}).get("Discoverable")
            ]
            if not open_:
                return
            log.warning(kv("adapter_still_open", adapters=",".join(open_)))
            await asyncio.sleep(0.2)
        log.error(kv("adapter_not_closed", adapters=",".join(open_)))

    async def _teardown(self) -> None:
        with contextlib.suppress(Exception):
            await self.pairing.cancel_pending()
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
        """Boucle principale : démarre, surveille, redémarre si BlueZ disparaît. Retourne le code de sortie
        (0 arrêt propre, 3 BlueZ injoignable, 4 redémarrage piloté non reçu)."""
        try:
            return await self._run(stop)
        finally:
            if self._restart_task is not None:
                self._restart_task.cancel()
                self._restart_task = None

    async def _run(self, stop: asyncio.Event) -> int:
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
            waiters = {
                asyncio.ensure_future(stop.wait()),
                asyncio.ensure_future(self._lost.wait()),
                asyncio.ensure_future(self._fallback.wait()),
            }
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            for w in waiters:
                w.cancel()
            self.ready.clear()
            await self._teardown()
            if stop.is_set():
                return EXIT_OK
            if self._fallback.is_set():
                return EXIT_RESTART_FALLBACK
            log.warning(kv("bluez_reconnect"))
            await asyncio.sleep(self.retry_interval)
        await self._teardown()
        return EXIT_OK
