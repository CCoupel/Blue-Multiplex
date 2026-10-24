"""PairingManager : fenêtre d'appairage (une seule à la fois) et actions sur les appareils."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from dbus_fast import Variant

from btmux.bluez.adapters import ADAPTER_IFACE, AdapterRegistry
from btmux.bluez.bus import Bus, DBusCallError
from btmux.bluez.errors import (
    BluezError,
    BluezUnavailable,
    BondStale,
    InvalidRequest,
    NotFound,
    WindowClosed,
    WindowOpen,
)
from btmux.bluez.inventory import DEVICE_IFACE, Inventory, _utc_iso
from btmux.bluez.models import PairingWindowModel
from btmux.config.models import PairingConfig
from btmux.log import kv

log = logging.getLogger("btmux.pairing")

MIN_DURATION, MAX_DURATION = 1, 300
PAIR_TIMEOUT, CONNECT_TIMEOUT = 60.0, 30.0
_AUTH_ERRORS = {
    "org.bluez.Error.AuthenticationFailed",
    "org.bluez.Error.AuthenticationRejected",
    "org.bluez.Error.AuthenticationCanceled",
    "org.bluez.Error.AuthenticationTimeout",
}


@dataclass
class _Window:
    role: str
    opened_at: datetime
    expires_at: datetime
    deadline: float  # loop.time()
    timer: asyncio.TimerHandle


def _wrap(exc: DBusCallError, what: str) -> BluezError:
    return BluezError(f"{what}: {exc.name}: {exc.message}".rstrip(": "))


class PairingManager:
    def __init__(
        self,
        bus: Bus,
        registry: AdapterRegistry,
        inventory: Inventory,
        config: PairingConfig,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._bus = bus
        self._registry = registry
        self._inventory = inventory
        self._cfg = config
        self._now = now
        self._window: _Window | None = None
        self._outgoing: set[str] = set()
        self._bg: set[asyncio.Future[None]] = set()
        self._lock = asyncio.Lock()
        inventory.set_window_provider(self.window)

    # ----- fenêtre ---------------------------------------------------------------------------
    def window(self) -> PairingWindowModel | None:
        w = self._window
        if w is None:
            return None
        loop = asyncio.get_running_loop()
        remaining = max(0, math.ceil(w.deadline - loop.time()))
        return PairingWindowModel(
            adapter=w.role,  # type: ignore[arg-type]
            opened_at=_utc_iso(w.opened_at),
            expires_at=_utc_iso(w.expires_at),
            remaining_s=remaining,
        )

    def _adapter_path(self, role: str) -> str:
        path = self._registry.path_for(role)
        if path is None:
            raise BluezUnavailable(f"no adapter for role '{role}'")
        return path

    async def _set(self, path: str, prop: str, signature: str, value: object) -> None:
        try:
            await self._bus.set_property(path, ADAPTER_IFACE, prop, signature, value)
        except DBusCallError as exc:
            raise _wrap(exc, f"set {prop}") from exc

    async def open(self, role: str, duration: int | None = None) -> PairingWindowModel:
        if role not in ("sources", "headsets"):
            raise InvalidRequest(f"unknown adapter role '{role}'")
        seconds = self._cfg.default_duration if duration is None else duration
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            raise InvalidRequest("duration must be an integer")
        if not MIN_DURATION <= seconds <= MAX_DURATION:
            raise InvalidRequest(f"duration must be between {MIN_DURATION} and {MAX_DURATION} s")
        async with self._lock:
            if self._window is not None:
                raise WindowOpen("a pairing window is already open")
            path = self._adapter_path(role)
            await self._set(path, "Pairable", "b", True)
            await self._set(path, "DiscoverableTimeout", "u", seconds)
            await self._set(path, "Discoverable", "b", True)
            if role == "headsets":
                self._inventory.set_discovery_collection(True)
                try:
                    await self._bus.call(
                        path,
                        "org.bluez.Adapter1",
                        "SetDiscoveryFilter",
                        "a{sv}",
                        [{"Transport": Variant("s", "bredr")}],
                    )
                    await self._bus.call(path, "org.bluez.Adapter1", "StartDiscovery")
                except DBusCallError as exc:
                    if exc.name != "org.bluez.Error.InProgress":
                        await self._reset_adapter(path)
                        self._inventory.set_discovery_collection(False)
                        raise _wrap(exc, "StartDiscovery") from exc
            loop = asyncio.get_running_loop()
            opened = self._now()
            self._window = _Window(
                role=role,
                opened_at=opened,
                expires_at=opened + timedelta(seconds=seconds),
                deadline=loop.time() + seconds,
                timer=loop.call_later(seconds, self._expire),
            )
            log.info(kv("pairing_open", role=role, duration=seconds))
        self._inventory.emit_pairing()
        model = self.window()
        assert model is not None
        return model

    def _expire(self) -> None:
        task = asyncio.ensure_future(self.close())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _reset_adapter(self, path: str) -> None:
        for prop in ("Discoverable", "Pairable"):
            try:
                await self._bus.set_property(path, ADAPTER_IFACE, prop, "b", False)
            except (DBusCallError, BluezUnavailable) as exc:
                log.warning(kv("adapter_reset_failed", prop=prop, error=exc))

    async def close(self) -> None:
        """Ferme la fenêtre (idempotent) : Discoverable/Pairable à faux, fin de découverte."""
        async with self._lock:
            w, self._window = self._window, None
            if w is None:
                return
            w.timer.cancel()
            path = self._registry.path_for(w.role)
            if path is not None:
                await self._reset_adapter(path)
                if w.role == "headsets":
                    try:
                        await self._bus.call(path, "org.bluez.Adapter1", "StopDiscovery")
                    except (DBusCallError, BluezUnavailable) as exc:
                        log.info(kv("stop_discovery_ignored", error=exc))
            self._inventory.set_discovery_collection(False)
            log.info(kv("pairing_close", role=w.role))
        self._inventory.emit_pairing()

    # ----- politique de l'agent ---------------------------------------------------------------
    def allows(self, device_path: str) -> bool:
        if device_path in self._outgoing:
            return True
        w = self._window
        return bool(
            w is not None
            and w.role == "sources"
            and self._cfg.accept_incoming
            and AdapterRegistry.adapter_of_device(device_path) == self._registry.path_for("sources")
        )

    def is_outgoing(self, device_path: str) -> bool:
        return device_path in self._outgoing

    async def trust_incoming(self, device_path: str) -> None:
        try:
            await self._bus.set_property(device_path, DEVICE_IFACE, "Trusted", "b", True)
            log.info(kv("device_trusted", device=device_path))
        except (DBusCallError, BluezUnavailable) as exc:
            log.warning(kv("trust_failed", device=device_path, error=exc))

    # ----- actions sur les appareils -------------------------------------------------------------
    def _path(self, mac: str, role: str | None = None) -> str:
        path = self._inventory.device_path(mac, role)
        if path is None:
            raise NotFound(f"device {mac.upper()} unknown")
        return path

    async def pair(self, mac: str) -> None:
        """Appairage initié par le Pi (casques) : Pair + Trusted + Connect sur l'adaptateur `headsets`."""
        if self._window is None or self._window.role != "headsets":
            raise WindowClosed("a 'headsets' pairing window must be open")
        path = self._path(mac, "headsets")
        if AdapterRegistry.adapter_of_device(path) != self._registry.path_for("headsets"):
            raise NotFound(f"device {mac.upper()} not seen on the headsets adapter")
        props = self._inventory.device_props(path) or {}
        self._outgoing.add(path)
        try:
            if not props.get("Paired"):
                try:
                    await self._bus.call(path, DEVICE_IFACE, "Pair", timeout=PAIR_TIMEOUT)
                except DBusCallError as exc:
                    if exc.name != "org.bluez.Error.AlreadyExists":
                        raise _wrap(exc, "Pair") from exc
            await self._bus.set_property(path, DEVICE_IFACE, "Trusted", "b", True)
            await self._do_connect(path)
            log.info(kv("pair_ok", mac=mac.upper()))
        finally:
            self._outgoing.discard(path)

    async def _do_connect(self, path: str) -> None:
        try:
            await self._bus.call(path, DEVICE_IFACE, "Connect", timeout=CONNECT_TIMEOUT)
        except DBusCallError as exc:
            paired = bool((self._inventory.device_props(path) or {}).get("Paired"))
            if paired and exc.name in _AUTH_ERRORS:
                raise BondStale(
                    "bond is stale: forget the device here and on the other side, then pair again"
                ) from exc
            raise _wrap(exc, "Connect") from exc

    async def connect(self, mac: str) -> None:
        await self._do_connect(self._path(mac))

    async def disconnect(self, mac: str) -> None:
        path = self._path(mac)
        try:
            await self._bus.call(path, DEVICE_IFACE, "Disconnect", timeout=CONNECT_TIMEOUT)
        except DBusCallError as exc:
            raise _wrap(exc, "Disconnect") from exc

    async def forget(self, mac: str) -> None:
        path = self._path(mac)
        adapter = AdapterRegistry.adapter_of_device(path)
        try:
            await self._bus.call(adapter, ADAPTER_IFACE, "RemoveDevice", "o", [path])
        except DBusCallError as exc:
            raise _wrap(exc, "RemoveDevice") from exc
        log.info(kv("device_forgotten", mac=mac.upper()))

    async def set_trusted(self, mac: str, trusted: bool) -> None:
        path = self._path(mac)
        try:
            await self._bus.set_property(path, DEVICE_IFACE, "Trusted", "b", trusted)
        except DBusCallError as exc:
            raise _wrap(exc, "set Trusted") from exc
