"""Affectation des rôles aux contrôleurs (#23) : validation, état atomique, verrou `change_pending`."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any

from btmux.bluez.errors import (
    BluezError,
    ChangePending,
    ControllerError,
    DevicesConnected,
    DisconnectFailed,
    StateWriteFailed,
    WindowOpen,
)
from btmux.bluez.inventory import Inventory
from btmux.bluez.models import RolesModel
from btmux.bluez.pairing import PairingManager
from btmux.config import Adapter, Config, write_state_atomic
from btmux.log import kv

log = logging.getLogger("btmux.controllers")
ROLES = ("sources", "headsets")
DEFAULT_NAMES = {"sources": "btmux", "headsets": "btmux-hp"}
DISCONNECT_TIMEOUT_S = 5.0  # attente bornée de `Connected=false` après `Disconnect` (par appareil)
DISCONNECT_POLL_S = 0.05
_MAC = re.compile(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")


class RoleManager:
    """`PUT /api/controllers/roles` : tout ou rien, puis redémarrage piloté du service (D3)."""

    def __init__(
        self,
        config: Config,
        inventory: Inventory,
        pairing: PairingManager,
        on_written: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._inventory = inventory
        self._pairing = pairing
        self._on_written = on_written
        self._lock = asyncio.Lock()
        self.disconnect_timeout = DISCONNECT_TIMEOUT_S
        self.disconnect_poll = DISCONNECT_POLL_S

    async def _disconnect_all(self, connected: list[Any]) -> None:
        """Déconnecte chaque appareil et attend `Connected=false` (délai borné) : AVANT toute écriture, le bus
        étant encore ouvert (le redémarrage le fermerait). Échec ou délai → `DisconnectFailed`, rien n'est écrit."""
        failed: list[dict[str, object]] = []
        for device in connected:
            info = {
                "mac": device.mac,
                "alias": device.alias,
                "name": device.name,
                "adapter": device.adapter,
            }
            try:
                await self._pairing.disconnect(device.mac)
            except BluezError as exc:
                log.warning(kv("disconnect_failed", mac=device.mac, error=exc))
                failed.append(info)
                continue
            if not await self._wait_disconnected(device.mac):
                log.warning(kv("disconnect_failed", mac=device.mac, error="timeout"))
                failed.append(info)
        if failed:
            raise DisconnectFailed(
                "cannot disconnect all devices: roles unchanged, nothing written", failed
            )

    async def _wait_disconnected(self, mac: str) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.disconnect_timeout
        while True:
            if not any(d.mac == mac and d.connected for d in self._inventory.devices()):
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(self.disconnect_poll)

    def check_writable(self) -> None:
        if self._inventory.roles_pending:
            raise ChangePending("role change in progress: the service is about to restart")

    def _parse(self, body: Any) -> tuple[dict[str, str | None], bool]:
        if not isinstance(body, dict) or set(body) - {"sources", "headsets", "confirm"}:
            raise ControllerError(
                "invalid_body", "fields: sources, headsets (MAC or null), confirm"
            )
        if not set(ROLES) <= set(body):
            raise ControllerError("invalid_body", "sources and headsets are required (MAC or null)")
        confirm = body.get("confirm", False)
        if not isinstance(confirm, bool):
            raise ControllerError("invalid_confirm", "confirm must be a boolean")
        present = {c.mac for c in self._inventory.controllers() if c.present}
        wanted: dict[str, str | None] = {}
        for role in ROLES:
            value = body[role]
            if value is None:
                wanted[role] = None
                continue
            if not isinstance(value, str) or not _MAC.fullmatch(value):
                raise ControllerError("invalid_mac", f"{role}: MAC address or null expected")
            if value.upper() not in present:
                raise ControllerError(
                    "unknown_controller", f"unknown or absent controller {value.upper()}"
                )
            wanted[role] = value.upper()
        if wanted["sources"] is not None and wanted["sources"] == wanted["headsets"]:
            raise ControllerError("same_controller", "a controller can carry only one role")
        return wanted, confirm

    def _role_name(self, role: str) -> str:
        """Nom du rôle : `name` de l'entrée de config portant le rôle (unique, V3), sinon le défaut."""
        entry = next((a for a in self._config.adapters if role in a.roles), None)
        return entry.name if entry else DEFAULT_NAMES[role]

    def _adapters_for(self, wanted: dict[str, str | None]) -> list[Adapter]:
        """L'alias suit le rôle, pas le dongle ; un contrôleur à deux rôles prend le nom de `sources`."""
        out: dict[str, list[str]] = {}
        for role in ROLES:
            mac = wanted[role]
            if mac is not None:
                out.setdefault(mac, []).append(role)
        return [
            Adapter(mac=mac, name=self._role_name(roles[0]), roles=tuple(roles))  # type: ignore[arg-type]
            for mac, roles in out.items()
        ]

    async def set_roles(self, body: Any) -> tuple[int, RolesModel]:
        """Retourne `(200, Roles)` si rien ne change, `(202, Roles)` si l'état est écrit (redémarrage imminent)."""
        async with self._lock:
            wanted, confirm = self._parse(body)  # 400
            current = (
                self._inventory.roles().to_dict()
            )  # pendant un changement : l'affectation écrite
            affected = [r for r in ROLES if wanted[r] != current[r]]
            if not affected:  # no-op 200, avant change_pending et pairing_open
                return 200, self._inventory.roles()
            self.check_writable()  # 409 change_pending
            if self._pairing.window_open:
                raise WindowOpen("close the pairing window before changing roles")
            connected = [
                d for d in self._inventory.devices() if d.connected and d.adapter in affected
            ]
            if connected and not confirm:
                raise DevicesConnected(
                    "devices are connected: confirm:true to disconnect them",
                    [
                        {"mac": d.mac, "alias": d.alias, "name": d.name, "adapter": d.adapter}
                        for d in connected
                    ],
                )
            if (
                connected
            ):  # confirm:true — d'abord les déconnexions (bus ouvert), échec → rien d'écrit
                await self._disconnect_all(connected)
            path = self._config.state_path
            try:  # puis l'état : en cas d'échec, pas de `pending`
                await asyncio.to_thread(write_state_atomic, path, self._adapters_for(wanted))
            except OSError as exc:
                log.error(kv("state_write_failed", file=path, error=exc.strerror or exc))
                raise StateWriteFailed(
                    f"cannot write the state file {path}: {exc.strerror or exc}"
                ) from exc
            self._inventory.mark_roles_pending(wanted["sources"], wanted["headsets"])
            log.info(kv("roles_written", sources=wanted["sources"], headsets=wanted["headsets"]))
            if self._on_written is not None:
                self._on_written()
            return 202, self._inventory.roles()
