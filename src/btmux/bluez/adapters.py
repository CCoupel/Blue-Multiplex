"""Association configuration ↔ objets `org.bluez.Adapter1` (par MAC, jamais par index hciN)."""

from __future__ import annotations

from dataclasses import dataclass

from btmux.bluez.bus import ManagedObjects
from btmux.config import Config

ADAPTER_IFACE = "org.bluez.Adapter1"


@dataclass(frozen=True)
class AdapterInfo:
    mac: str
    name: str
    roles: tuple[str, ...]
    path: str | None = None

    @property
    def present(self) -> bool:
        return self.path is not None

    @property
    def hci(self) -> str | None:
        return self.path.rsplit("/", 1)[-1] if self.path else None


class AdapterRegistry:
    """Résout les adaptateurs de la configuration dans les objets BlueZ."""

    def __init__(self, config: Config) -> None:
        self._infos = [AdapterInfo(a.mac, a.name, tuple(a.roles)) for a in config.adapters]

    def update(self, objects: ManagedObjects) -> list[str]:
        """Met à jour les chemins ; retourne les MAC de la config introuvables."""
        by_mac = {
            str(ifaces[ADAPTER_IFACE].get("Address", "")).upper(): path
            for path, ifaces in objects.items()
            if ADAPTER_IFACE in ifaces
        }
        self._infos = [AdapterInfo(i.mac, i.name, i.roles, by_mac.get(i.mac)) for i in self._infos]
        return [i.mac for i in self._infos if i.path is None]

    @property
    def infos(self) -> list[AdapterInfo]:
        return list(self._infos)

    def path_for(self, role: str) -> str | None:
        for info in self._infos:
            if role in info.roles:
                return info.path
        return None

    def info_for_path(self, path: str) -> AdapterInfo | None:
        return next((i for i in self._infos if i.path == path), None)

    def paths(self) -> set[str]:
        return {i.path for i in self._infos if i.path}

    @staticmethod
    def adapter_of_device(device_path: str) -> str:
        return device_path.rsplit("/dev_", 1)[0]
