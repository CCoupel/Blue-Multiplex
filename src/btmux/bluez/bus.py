"""Accès au bus système D-Bus : protocole `Bus` (remplaçable par un faux en test) et implémentation dbus-fast."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from dbus_fast import Variant

from btmux.bluez.errors import BluezUnavailable
from btmux.log import kv

if TYPE_CHECKING:
    from btmux.bluez.agent import Agent

log = logging.getLogger("btmux.bus")

BLUEZ = "org.bluez"
Props = dict[str, Any]
ManagedObjects = dict[str, dict[str, Props]]
SignalKind = Literal[
    "interfaces_added", "interfaces_removed", "properties_changed", "name_owner_changed"
]


class DBusCallError(Exception):
    """Réponse d'erreur D-Bus (`name` = `org.bluez.Error.*`)."""

    def __init__(self, name: str, message: str = "") -> None:
        super().__init__(f"{name}: {message}" if message else name)
        self.name = name
        self.message = message


@dataclass(frozen=True)
class BusSignal:
    """Signal normalisé. `data` : objets+interfaces (added), liste d'interfaces (removed),
    propriétés modifiées (properties_changed, avec `interface`), `(ancien, nouveau)` (name_owner_changed)."""

    kind: SignalKind
    path: str
    interface: str | None
    data: Any


SignalCallback = Callable[[BusSignal], None]


class Bus(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    def on_signal(self, callback: SignalCallback) -> None: ...
    def on_disconnect(self, callback: Callable[[], None]) -> None: ...
    async def get_managed_objects(self) -> ManagedObjects: ...
    async def call(
        self,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: Sequence[Any] = (),
        *,
        timeout: float | None = 10.0,
    ) -> list[Any]: ...
    async def set_property(
        self, path: str, interface: str, prop: str, signature: str, value: Any
    ) -> None: ...
    async def export_agent(self, path: str, agent: Agent) -> None: ...
    async def unexport_agent(self, path: str) -> None: ...


def unwrap(value: Any) -> Any:
    """Variant dbus-fast → valeur Python (récursif)."""
    if isinstance(value, Variant):
        return unwrap(value.value)
    if isinstance(value, dict):
        return {k: unwrap(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [unwrap(v) for v in value]
    return value


class DBusFastBus:
    """Bus système via dbus-fast. Reconnexion : à la charge de `BluezService` (rappel `on_disconnect`)."""

    def __init__(self) -> None:
        self._bus: Any = None
        self._signal_cbs: list[SignalCallback] = []
        self._disconnect_cbs: list[Callable[[], None]] = []
        self._watch: asyncio.Task[None] | None = None
        self._agents: dict[str, Any] = {}

    def on_signal(self, callback: SignalCallback) -> None:
        self._signal_cbs.append(callback)

    def on_disconnect(self, callback: Callable[[], None]) -> None:
        self._disconnect_cbs.append(callback)

    async def connect(self) -> None:
        from dbus_fast import BusType, Message
        from dbus_fast.aio import MessageBus

        try:
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        except Exception as exc:  # socket absent, refus, ...
            raise BluezUnavailable(f"system bus unavailable: {exc}") from exc
        self._bus = bus
        bus.add_message_handler(self._on_message)
        for rule in (
            "type='signal',sender='org.bluez'",
            "type='signal',sender='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.bluez'",
        ):
            await bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[rule],
                )
            )
        self._watch = asyncio.create_task(self._wait_disconnect(bus))

    async def _wait_disconnect(self, bus: Any) -> None:
        with contextlib.suppress(Exception):
            await bus.wait_for_disconnect()
        if self._bus is bus:
            log.warning(kv("bus_disconnected"))
            for cb in list(self._disconnect_cbs):
                cb()

    async def close(self) -> None:
        bus, self._bus = self._bus, None
        if self._watch is not None:
            self._watch.cancel()
            self._watch = None
        if bus is not None:
            bus.disconnect()

    def _on_message(self, msg: Any) -> bool:
        from dbus_fast import MessageType

        if msg.message_type != MessageType.SIGNAL:
            return False
        signal: BusSignal | None = None
        if msg.member == "PropertiesChanged" and msg.sender != "org.freedesktop.DBus":
            iface, changed, _ = msg.body
            signal = BusSignal("properties_changed", msg.path, iface, unwrap(changed))
        elif msg.member == "InterfacesAdded":
            path, ifaces = msg.body
            signal = BusSignal("interfaces_added", path, None, unwrap(ifaces))
        elif msg.member == "InterfacesRemoved":
            path, ifaces = msg.body
            signal = BusSignal("interfaces_removed", path, None, list(ifaces))
        elif msg.member == "NameOwnerChanged" and msg.body and msg.body[0] == BLUEZ:
            signal = BusSignal("name_owner_changed", "/", None, (msg.body[1], msg.body[2]))
        if signal is not None:
            for cb in list(self._signal_cbs):
                cb(signal)
        return False

    def _require(self) -> Any:
        if self._bus is None:
            raise BluezUnavailable("system bus not connected")
        return self._bus

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
        from dbus_fast import Message, MessageType

        bus = self._require()
        msg = Message(
            destination=BLUEZ,
            path=path,
            interface=interface,
            member=member,
            signature=signature,
            body=list(body),
        )
        try:
            reply = await asyncio.wait_for(bus.call(msg), timeout)
        except TimeoutError as exc:
            raise DBusCallError("org.bluez.Error.Timeout", f"{interface}.{member} timeout") from exc
        except Exception as exc:
            raise BluezUnavailable(f"D-Bus: {exc}") from exc
        if reply is None:
            return []
        if reply.message_type == MessageType.ERROR:
            raise DBusCallError(
                reply.error_name or "unknown", str(reply.body[0]) if reply.body else ""
            )
        return [unwrap(item) for item in reply.body]

    async def get_managed_objects(self) -> ManagedObjects:
        reply = await self.call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
        objects: ManagedObjects = reply[0] if reply else {}
        return objects

    async def set_property(
        self, path: str, interface: str, prop: str, signature: str, value: Any
    ) -> None:
        await self.call(
            path,
            "org.freedesktop.DBus.Properties",
            "Set",
            "ssv",
            [interface, prop, Variant(signature, value)],
        )

    async def export_agent(self, path: str, agent: Agent) -> None:
        from btmux.bluez.agent_dbus import make_interface

        bus = self._require()
        iface = make_interface(agent)
        self._agents[path] = iface
        bus.export(path, iface)

    async def unexport_agent(self, path: str) -> None:
        bus = self._bus
        if bus is not None and self._agents.pop(path, None) is not None:
            bus.unexport(path)
