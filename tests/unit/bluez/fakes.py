"""Bus D-Bus simulé pour les tests de `btmux.bluez` (partagé avec test-writer).

`FakeBus` implémente le Protocol `btmux.bluez.bus.Bus` : objets BlueZ en mémoire, appels notés,
signaux injectables, erreurs et réponses programmables, perte de connexion simulable.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Callable, Sequence
from typing import Any

from btmux.bluez.agent import Agent
from btmux.bluez.bus import (
    BusSignal,
    DBusCallError,
    ManagedObjects,
    SignalCallback,
)
from btmux.bluez.errors import BluezUnavailable

SRC_MAC = "AA:BB:CC:00:00:01"
HP_MAC = "AA:BB:CC:00:00:02"
SRC_PATH = "/org/bluez/hci1"
HP_PATH = "/org/bluez/hci0"
PHONE_MAC = "11:22:33:44:55:01"
HEADSET_MAC = "11:22:33:44:55:02"

A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"
A2DP_SOURCE = "0000110a-0000-1000-8000-00805f9b34fb"
HFP_AG = "0000111f-0000-1000-8000-00805f9b34fb"

Handler = Callable[[str, list[Any]], Any]


def adapter_obj(mac: str, alias: str = "btmux", **props: Any) -> dict[str, dict[str, Any]]:
    base = {
        "Address": mac,
        "Alias": alias,
        "Powered": True,
        "Discoverable": False,
        "Pairable": False,
        "Class": 0x6C0404,
    }
    return {"org.bluez.Adapter1": {**base, **props}}


def device_path(adapter_path: str, mac: str) -> str:
    return f"{adapter_path}/dev_{mac.replace(':', '_')}"


def device_obj(mac: str, name: str = "dev", **props: Any) -> dict[str, dict[str, Any]]:
    base: dict[str, Any] = {
        "Address": mac,
        "Name": name,
        "Alias": name,
        "Paired": False,
        "Trusted": False,
        "Connected": False,
        "Blocked": False,
        "UUIDs": [],
    }
    return {"org.bluez.Device1": {**base, **props}}


def bi_objects() -> ManagedObjects:
    """Deux adaptateurs : hci1 = sources (SRC_MAC), hci0 = headsets (HP_MAC)."""
    return {
        SRC_PATH: adapter_obj(SRC_MAC, "btmux"),
        HP_PATH: adapter_obj(HP_MAC, "btmux-hp"),
    }


class FakeBus:
    def __init__(self, objects: ManagedObjects | None = None) -> None:
        self.objects: ManagedObjects = objects if objects is not None else bi_objects()
        self.calls: list[tuple[str, str, str, list[Any]]] = []
        self.sets: list[tuple[str, str, str, Any]] = []
        self.handlers: dict[tuple[str, str], Handler] = {}
        self.errors: dict[tuple[str, str], DBusCallError] = {}
        self.set_errors: dict[tuple[str, str], DBusCallError] = {}
        self.connect_failures = 0
        self.pairable_on_register = True
        self.connected = False
        self.connect_count = 0
        self.agent: Agent | None = None
        self.agent_path: str | None = None
        self._signal_cbs: list[SignalCallback] = []
        self._disconnect_cbs: list[Callable[[], None]] = []

    # ----- Protocol Bus ----------------------------------------------------------------------
    async def connect(self) -> None:
        self.connect_count += 1
        if self.connect_failures > 0:
            self.connect_failures -= 1
            raise BluezUnavailable("system bus unavailable (fake)")
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    def on_signal(self, callback: SignalCallback) -> None:
        self._signal_cbs.append(callback)

    def on_disconnect(self, callback: Callable[[], None]) -> None:
        self._disconnect_cbs.append(callback)

    async def get_managed_objects(self) -> ManagedObjects:
        self._require()
        return copy.deepcopy(self.objects)

    async def call(
        self,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: Sequence[Any] = (),
        *,
        timeout: float | None = 10.0,
    ) -> list[Any]:
        self._require()
        self.calls.append((path, interface, member, list(body)))
        if member == "RegisterAgent" and self.pairable_on_register:
            # BlueZ (constaté sur pi-qualif) : un agent enregistré rend l'adaptateur « Pairable »
            for obj_path, ifaces in self.objects.items():
                if "org.bluez.Adapter1" in ifaces:
                    self.objects[obj_path]["org.bluez.Adapter1"]["Pairable"] = True
        error = self.errors.get((interface, member))
        if error is not None:
            raise error
        handler = self.handlers.get((interface, member))
        if handler is None:
            return []
        result = handler(path, list(body))
        if asyncio.iscoroutine(result):
            result = await result
        return result if isinstance(result, list) else []

    async def set_property(
        self, path: str, interface: str, prop: str, signature: str, value: Any
    ) -> None:
        self._require()
        self.sets.append((path, interface, prop, value))
        error = self.set_errors.get((interface, prop))
        if error is not None:
            raise error
        self.objects.setdefault(path, {}).setdefault(interface, {})[prop] = value
        self.emit(BusSignal("properties_changed", path, interface, {prop: value}))

    async def export_agent(self, path: str, agent: Agent) -> None:
        self.agent, self.agent_path = agent, path

    async def unexport_agent(self, path: str) -> None:
        self.agent = self.agent_path = None

    # ----- pilotage par les tests ------------------------------------------------------------
    def _require(self) -> None:
        if not self.connected:
            raise BluezUnavailable("system bus not connected (fake)")

    def emit(self, signal: BusSignal) -> None:
        for cb in list(self._signal_cbs):
            cb(signal)

    def add_device(self, adapter_path: str, mac: str, **props: Any) -> str:
        """Ajoute un appareil et émet `InterfacesAdded`, comme BlueZ."""
        path = device_path(adapter_path, mac)
        ifaces = device_obj(mac, **props)
        self.objects[path] = ifaces
        self.emit(BusSignal("interfaces_added", path, None, copy.deepcopy(ifaces)))
        return path

    def remove_device(self, path: str) -> None:
        self.objects.pop(path, None)
        self.emit(BusSignal("interfaces_removed", path, None, ["org.bluez.Device1"]))

    def change(self, path: str, interface: str, **props: Any) -> None:
        self.objects[path][interface].update(props)
        self.emit(BusSignal("properties_changed", path, interface, props))

    def lose_connection(self) -> None:
        self.connected = False
        for cb in list(self._disconnect_cbs):
            cb()

    def bluez_left(self) -> None:
        self.emit(BusSignal("name_owner_changed", "/", None, (":1.5", "")))

    def calls_to(self, member: str) -> list[tuple[str, list[Any]]]:
        return [(p, b) for p, _, m, b in self.calls if m == member]
