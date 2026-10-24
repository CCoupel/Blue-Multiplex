"""Inventaire BlueZ : `ObjectManager` + `PropertiesChanged` → modèles de l'API + file d'événements (SSE, #21)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from btmux import __version__
from btmux.bluez.adapters import ADAPTER_IFACE, AdapterRegistry
from btmux.bluez.bus import BusSignal, ManagedObjects, Props
from btmux.bluez.models import (
    AdapterModel,
    DeviceModel,
    DeviceRemovedModel,
    DiscoveredModel,
    KindName,
    PairingWindowModel,
    RoleName,
    deduce_kind,
    format_class,
    profiles_from_uuids,
)
from btmux.config import Config
from btmux.log import kv

DEVICE_IFACE = "org.bluez.Device1"
# Propriétés dont le changement produit un évènement `device` (le RSSI seul n'en produit pas).
_DEVICE_EVENT_PROPS = {"Paired", "Trusted", "Connected", "Blocked", "Alias", "Name", "UUIDs"}
_QUEUE_MAX = 1000

log = logging.getLogger("btmux.inventory")


def _utc_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Event:
    id: int
    kind: str  # adapter | device | pairing | discovered
    data: Any  # modèle complet (dict JSON) ; None pour la fermeture d'une fenêtre


class Subscription:
    """Abonnement à la file d'événements : `await sub.get()` ; `closed` si la file a débordé."""

    def __init__(self, inventory: Inventory) -> None:
        self._inventory = inventory
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self.overflowed = False

    async def get(self) -> Event:
        return await self.queue.get()

    def close(self) -> None:
        self._inventory.unsubscribe(self)


class Inventory:
    def __init__(
        self,
        config: Config,
        registry: AdapterRegistry,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._config = config
        self._registry = registry
        self._now = now
        self._adapters: dict[str, Props] = {}
        self._devices: dict[str, Props] = {}
        self._discovered: dict[str, DiscoveredModel] = {}
        self._collect_discovered = False
        self._aliases: dict[str, str] = {}
        self._last_seen: dict[str, str] = {}
        self._origin: dict[str, KindName] = {}
        self._paired_listeners: list[Callable[[str], None]] = []
        self._subs: set[Subscription] = set()
        self._counter = 0
        self._window: Callable[[], PairingWindowModel] = lambda: PairingWindowModel(
            open=False, adapter=None
        )
        self._cfg_devices = {d.mac.upper(): d for d in config.devices}

    # ----- chargement et signaux -------------------------------------------------------------
    def set_window_provider(self, provider: Callable[[], PairingWindowModel]) -> None:
        self._window = provider

    def on_paired(self, listener: Callable[[str], None]) -> None:
        """Rappel `listener(chemin)` quand un appareil devient `Paired` (nouvel appairage, pas au chargement)."""
        self._paired_listeners.append(listener)

    def set_origin(self, mac: str, kind: KindName) -> None:
        """Origine de l'appairage (arbitre de `kind` hors config) : `headset` (pair du Pi) ou `source`."""
        self._origin[mac.upper()] = kind

    def load(self, objects: ManagedObjects) -> None:
        """Recharge tout l'état (démarrage, reconnexion BlueZ) ; aucun évènement n'est émis."""
        self._adapters = {p: i[ADAPTER_IFACE] for p, i in objects.items() if ADAPTER_IFACE in i}
        self._devices = {p: i[DEVICE_IFACE] for p, i in objects.items() if DEVICE_IFACE in i}
        for props in self._devices.values():
            if props.get("Connected"):
                self._last_seen[str(props.get("Address", "")).upper()] = _utc_iso(self._now())

    def handle(self, signal: BusSignal) -> None:
        if signal.kind == "interfaces_added":
            for iface, props in signal.data.items():
                if iface == ADAPTER_IFACE:
                    self._adapters[signal.path] = dict(props)
                    self._emit_adapter(signal.path)
                elif iface == DEVICE_IFACE:
                    self._devices[signal.path] = dict(props)
                    self._device_changed(signal.path, new=True)
                    if props.get("Paired"):
                        self._notify_paired(signal.path)
        elif signal.kind == "interfaces_removed":
            for iface in signal.data:
                if iface == ADAPTER_IFACE:
                    self._adapters.pop(signal.path, None)
                elif iface == DEVICE_IFACE:
                    self._device_removed(signal.path)
        elif signal.kind == "properties_changed":
            if signal.interface == ADAPTER_IFACE and signal.path in self._adapters:
                self._adapters[signal.path].update(signal.data)
                self._emit_adapter(signal.path)
            elif signal.interface == DEVICE_IFACE and signal.path in self._devices:
                props = self._devices[signal.path]
                was_connected = bool(props.get("Connected"))
                was_paired = bool(props.get("Paired"))
                props.update(signal.data)
                if "Connected" in signal.data and bool(props.get("Connected")) != was_connected:
                    self._last_seen[str(props.get("Address", "")).upper()] = _utc_iso(self._now())
                self._device_changed(signal.path, changed=set(signal.data))
                if props.get("Paired") and not was_paired:
                    self._notify_paired(signal.path)

    def _notify_paired(self, path: str) -> None:
        for listener in list(self._paired_listeners):
            listener(path)

    # ----- évènements ------------------------------------------------------------------------
    def subscribe(self) -> Subscription:
        sub = Subscription(self)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    @property
    def last_event_id(self) -> int:
        return self._counter

    def emit(self, kind: str, data: Any) -> None:
        self._counter += 1
        event = Event(self._counter, kind, data)
        for sub in list(self._subs):
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.overflowed = True
                self._subs.discard(sub)
                log.warning(kv("subscriber_dropped", reason="queue_full"))

    def emit_pairing(self) -> None:
        self.emit("pairing", self._window().to_dict())

    def _emit_adapter(self, path: str) -> None:
        for model in self._adapter_models(path):
            self.emit("adapter", model.to_dict())

    # ----- appareils -------------------------------------------------------------------------
    def set_discovery_collection(self, enabled: bool) -> None:
        """Active/désactive la collecte `Discovered` (fenêtre `headsets`) ; réinitialise la liste."""
        self._collect_discovered = enabled
        self._discovered.clear()
        if enabled:
            for path in list(self._devices):
                self._classify_discovered(path, emit=True)

    def _is_known(self, props: Props) -> bool:
        mac = str(props.get("Address", "")).upper()
        return (
            bool(props.get("Paired") or props.get("Trusted") or props.get("Connected"))
            or mac in self._cfg_devices
        )

    def _managed(self, path: str) -> bool:
        return AdapterRegistry.adapter_of_device(path) in self._registry.paths()

    def _device_changed(
        self, path: str, *, new: bool = False, changed: set[str] | None = None
    ) -> None:
        if not self._managed(path):
            return
        props = self._devices[path]
        mac = str(props.get("Address", "")).upper()
        if self._bonded(props):
            self._discovered.pop(mac, None)
        else:
            self._classify_discovered(path, emit=True)
        if self._is_known(props) and (new or changed is None or changed & _DEVICE_EVENT_PROPS):
            self.emit("device", self._device_model(path, props).to_dict())

    def _bonded(self, props: Props) -> bool:
        return bool(props.get("Paired") or props.get("Trusted") or props.get("Connected"))

    def _classify_discovered(self, path: str, *, emit: bool) -> None:
        props = self._devices.get(path)
        if props is None or not self._collect_discovered or not self._managed(path):
            return
        if self._bonded(props):
            return
        adapter = AdapterRegistry.adapter_of_device(path)
        info = self._registry.info_for_path(adapter)
        if info is None or "headsets" not in info.roles:
            return
        mac = str(props.get("Address", "")).upper()
        model = DiscoveredModel(
            mac=mac,
            adapter="headsets",
            name=str(props.get("Name") or props.get("Alias") or mac),
            rssi=props.get("RSSI"),
            class_=format_class(props.get("Class")),
        )
        previous = self._discovered.get(mac)
        self._discovered[mac] = model
        if emit and (
            previous is None or (previous.name, previous.class_) != (model.name, model.class_)
        ):
            self.emit("discovered", model.to_dict())

    def _device_removed(self, path: str) -> None:
        props = self._devices.pop(path, None)
        if props is None or not self._managed(path):
            return
        mac = str(props.get("Address", "")).upper()
        was_discovered = self._discovered.pop(mac, None) is not None
        if was_discovered and not self._is_known(props):
            self.emit("device.removed", DeviceRemovedModel(mac, "headsets").to_dict())
        elif self._is_known(props):
            kind = self._device_model(path, props).kind
            role = self._role_of(path, props, kind)
            self.emit("device.removed", DeviceRemovedModel(mac, role).to_dict())
            if mac in self._cfg_devices:  # la ligne réapparaît : connu de la config, non appairé
                self.emit("device", self._placeholder(mac).to_dict())

    def _placeholder(self, mac: str) -> DeviceModel:
        cfg = self._cfg_devices[mac]
        return DeviceModel(
            mac=mac,
            adapter="sources" if cfg.kind == "source" else "headsets",
            alias=self._aliases.get(mac) or cfg.alias,
            name=None,
            kind=cfg.kind,
            paired=False,
            trusted=False,
            connected=False,
            blocked=False,
            last_seen=self._last_seen.get(mac),
            in_config=True,
        )

    def _role_of(self, path: str, props: Props, kind: KindName) -> RoleName:
        info = self._registry.info_for_path(AdapterRegistry.adapter_of_device(path))
        roles = info.roles if info else ()
        if len(roles) == 1:
            return roles[0]  # type: ignore[return-value]
        if kind == "headset":
            return "headsets"
        return "sources"

    def _device_model(self, path: str, props: Props) -> DeviceModel:
        mac = str(props.get("Address", "")).upper()
        uuids = [str(u) for u in props.get("UUIDs", [])]
        cfg = self._cfg_devices.get(mac)
        kind: KindName = (
            cfg.kind if cfg else deduce_kind(props.get("Class"), uuids, self._origin.get(mac))
        )
        return DeviceModel(
            mac=mac,
            adapter=self._role_of(path, props, kind),
            alias=self._aliases.get(mac) or (cfg.alias if cfg else None),
            name=str(props.get("Name") or props.get("Alias") or mac),
            kind=kind,
            paired=bool(props.get("Paired")),
            trusted=bool(props.get("Trusted")),
            connected=bool(props.get("Connected")),
            blocked=bool(props.get("Blocked")),
            uuids=uuids,
            profiles=profiles_from_uuids(uuids),
            last_seen=self._last_seen.get(mac),
            in_config=cfg is not None,
        )

    # ----- lecture ---------------------------------------------------------------------------
    def _adapter_models(self, only: str | None = None) -> list[AdapterModel]:
        models: list[AdapterModel] = []
        for info in self._registry.infos:
            if info.path is None or (only is not None and info.path != only):
                continue
            props = self._adapters.get(info.path, {})
            for role in info.roles:
                models.append(
                    AdapterModel(
                        role=role,  # type: ignore[arg-type]
                        mac=info.mac,
                        alias=str(props.get("Alias", info.name)),
                        hci=info.hci or "",
                        powered=bool(props.get("Powered")),
                        discoverable=bool(props.get("Discoverable")),
                        pairable=bool(props.get("Pairable")),
                        class_=format_class(props.get("Class")),
                    )
                )
        return models

    def adapters(self) -> list[AdapterModel]:
        return self._adapter_models()

    def devices(self) -> list[DeviceModel]:
        models: dict[str, DeviceModel] = {}
        for path, props in self._devices.items():
            if self._managed(path) and self._is_known(props):
                model = self._device_model(path, props)
                models[model.mac] = model
        for mac in self._cfg_devices:
            if mac not in models:
                models[mac] = self._placeholder(mac)
        return sorted(models.values(), key=lambda m: (m.adapter, m.alias or m.name, m.mac))

    def discovered(self) -> list[DiscoveredModel]:
        return sorted(self._discovered.values(), key=lambda m: (-(m.rssi or -999), m.mac))

    def state(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "adapters": [a.to_dict() for a in self.adapters()],
            "devices": [d.to_dict() for d in self.devices()],
            "pairing": self._window().to_dict(),
        }

    def device_path(self, mac: str, role: str | None = None) -> str | None:
        """Chemin D-Bus de l'appareil `mac` (préfère l'adaptateur du rôle donné)."""
        mac = mac.upper()
        found = [
            p
            for p, props in self._devices.items()
            if str(props.get("Address", "")).upper() == mac and self._managed(p)
        ]
        if role is not None:
            wanted = self._registry.path_for(role)
            found.sort(key=lambda p: AdapterRegistry.adapter_of_device(p) != wanted)
        return found[0] if found else None

    def configured_role(self, mac: str) -> str | None:
        """Rôle (`sources`/`headsets`) d'un appareil connu de la config, sinon `None`."""
        cfg = self._cfg_devices.get(mac.upper())
        if cfg is None:
            return None
        return "sources" if cfg.kind == "source" else "headsets"

    def device_props(self, path: str) -> Props | None:
        return self._devices.get(path)

    def is_trusted(self, path: str) -> bool:
        return bool((self._devices.get(path) or {}).get("Trusted"))

    def set_alias(self, mac: str, alias: str | None) -> None:
        """Alias btmux (en mémoire : la configuration n'est pas réécrite en v0.2.0)."""
        mac = mac.upper()
        if alias:
            self._aliases[mac] = alias
        else:
            self._aliases.pop(mac, None)
        path = self.device_path(mac)
        if path:
            self.emit("device", self._device_model(path, self._devices[path]).to_dict())
