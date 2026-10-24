"""Agent d'appairage (`org.bluez.Agent1`, NoInputNoOutput) : politique « fenêtre seulement », refus par défaut.

- Appairage **entrant** (une source se présente comme casque) : accepté uniquement si une fenêtre `sources` est
  ouverte, si `pairing.accept_incoming` est vrai et si l'appareil est sur l'adaptateur du rôle `sources`.
- Appairage **sortant** (initié par le Pi vers un casque) : accepté pour l'appareil en cours d'appairage.
- `AuthorizeService` : accepté pour un appareil déjà `Trusted` (reconnexion) ou dans les cas ci-dessus.
- Tout le reste est refusé (`org.bluez.Error.Rejected`).
L'adaptation D-Bus (signatures) vit dans `agent_dbus.py`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from btmux.bluez.errors import AgentRejected
from btmux.log import kv

if TYPE_CHECKING:
    from btmux.bluez.inventory import Inventory
    from btmux.bluez.pairing import PairingManager

log = logging.getLogger("btmux.agent")
AGENT_PATH = "/org/btmux/agent"
AGENT_CAPABILITY = "NoInputNoOutput"
LEGACY_PIN = "0000"


class Agent:
    def __init__(self, pairing: PairingManager, inventory: Inventory) -> None:
        self._pairing = pairing
        self._inventory = inventory
        self._tasks: set[asyncio.Task[None]] = set()

    def _gate(self, kind: str, device: str, *, service: bool = False) -> None:
        allowed = self._pairing.allows(device)
        if not allowed and service:
            allowed = self._inventory.is_trusted(device)
        if not allowed:
            log.warning(kv("agent_refused", request=kind, device=device))
            raise AgentRejected(f"{kind} refused (window closed or device not expected)")
        log.info(kv("agent_accepted", request=kind, device=device))
        if not service and not self._pairing.is_outgoing(device):
            task = asyncio.ensure_future(self._pairing.trust_incoming(device))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def request_authorization(self, device: str) -> None:
        self._gate("RequestAuthorization", device)

    async def authorize_service(self, device: str, uuid: str) -> None:
        self._gate(f"AuthorizeService {uuid}", device, service=True)

    async def request_confirmation(self, device: str, passkey: int) -> None:
        self._gate("RequestConfirmation", device)

    async def request_pin_code(self, device: str) -> str:
        self._gate("RequestPinCode", device)
        return LEGACY_PIN

    async def request_passkey(self, device: str) -> int:
        self._gate("RequestPasskey", device)
        return 0

    def release(self) -> None:
        log.info(kv("agent_released"))

    def cancel(self) -> None:
        log.info(kv("agent_cancelled"))

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
