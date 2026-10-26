"""Requêtes d'identité au hotplug (#23) : `identity.request` multi-lignes, vérification différée de la classe.

Le daemon n'est pas root : il écrit `/var/lib/btmux/identity.request` (une ligne `ISO<TAB>hciN<TAB>MAC` par
contrôleur en attente) ; `btmux-adapters-identity.path` rejoue alors `btmux-adapters.sh --only <MAC>` en root.
Chaque requête est vérifiée `verify_delay` s plus tard (classe observée = classe du rôle ?) ; sinon nouvelle
requête, `MAX_ATTEMPTS` au plus par contrôleur et par épisode, puis journal ERROR `identity_giving_up`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from btmux.bluez.adapters import AdapterRegistry
from btmux.bluez.inventory import Inventory
from btmux.config import write_identity_requests
from btmux.log import kv

log = logging.getLogger("btmux.identity")

# Classe attendue par rôle (bits majeur/mineur ; les bits « service » varient avec les UUID enregistrés)
CLASS_MASK = 0x1FFF
CLASS_SOURCES = 0x0404  # rôle sources : casque audio
CLASS_HEADSETS = 0x010C  # rôle headsets seul : ordinateur portable
MAX_ATTEMPTS = 3
VERIFY_DELAY_S = 60.0
DEBOUNCE_S = 1.0


def expected_class(roles: tuple[str, ...]) -> int:
    return CLASS_SOURCES if "sources" in roles else CLASS_HEADSETS


# Marqueur interne : contenu inconnu hérité d'une exécution précédente (jamais une MAC)
_RESIDUAL = ""

Sleep = Callable[[float], Awaitable[None]]
Writer = Callable[[Path, Sequence[tuple[str, str, str]]], Awaitable[None]]


async def _write_in_thread(path: Path, entries: Sequence[tuple[str, str, str]]) -> None:
    await asyncio.to_thread(write_identity_requests, path, entries)


class IdentityRequester:
    def __init__(
        self,
        target: Path,
        registry: AdapterRegistry,
        inventory: Inventory,
        *,
        verify_delay: float = VERIFY_DELAY_S,
        debounce: float = DEBOUNCE_S,
        max_attempts: int = MAX_ATTEMPTS,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Sleep = asyncio.sleep,
        write: Writer = _write_in_thread,
    ) -> None:
        # `sleep` et `write` sont injectables : les tests pilotent le temps et les écritures sans horloge réelle
        self.sleep = sleep
        self.write = write
        self._target = target
        self._registry = registry
        self._inventory = inventory
        self.verify_delay = verify_delay
        self.debounce = debounce
        self.max_attempts = max_attempts
        self._now = now
        # MAC en attente d'acquittement → (hci, horodatage de la requête) : contenu du fichier
        self._pending: dict[str, tuple[str, str]] = {}
        self._attempts: dict[str, int] = {}
        self._verifiers: dict[str, asyncio.Task[None]] = {}
        self._flusher: asyncio.Task[None] | None = None
        self._dirty = False
        self._written: set[str] = set()  # MAC présentes dans le fichier tel qu'écrit
        self._to_log: set[str] = set()  # requêtes (ré)émises pas encore journalisées

    # ----- API ----------------------------------------------------------------------------------
    def hotplug(self, hci: str, mac: str) -> None:
        """Un contrôleur affecté vient d'apparaître : nouvel épisode (compteur remis à 1)."""
        self._drop_verifier(mac)
        self._attempts[mac] = 0
        self._request(hci, mac)

    def class_observed(self, hci: str, mac: str, value: int, roles: tuple[str, ...]) -> None:
        """`PropertiesChanged Class` d'un contrôleur affecté : classe correcte → acquittement. Une classe
        incorrecte ne déclenche rien ici : seule la vérification différée bornée peut réémettre (pas de boucle)."""
        if (value & CLASS_MASK) == expected_class(roles):
            self._ack(mac)

    def reconcile_startup(self) -> None:
        """Démarrage : le fichier doit refléter l'état réel (#23). Un résidu d'une exécution précédente
        (aucune MAC en attente dans CE processus) est vidé par le flush habituel (débounce, écriture
        atomique) ; aucune passe, aucune vérification, aucune boucle n'est déclenchée. Les MAC réellement
        en attente (hotplug survenu pendant le démarrage) sont portées par le même flush."""
        try:
            residual = self._target.stat().st_size > 0
        except OSError:
            return  # fichier absent / illisible : rien à réconcilier
        if not residual:
            return
        # le fichier contient autre chose que l'état connu : le réécrire
        self._written.add(_RESIDUAL)
        self._dirty = True
        if self._flusher is None or self._flusher.done():
            self._flusher = asyncio.ensure_future(self._flush())

    def reset(self) -> None:
        """Arrêt / reconnexion BlueZ : plus rien en attente."""
        for task in [*self._verifiers.values(), *([self._flusher] if self._flusher else [])]:
            task.cancel()
        self._verifiers.clear()
        self._flusher = None
        self._pending.clear()
        self._attempts.clear()
        self._dirty = False
        self._written.clear()
        self._to_log.clear()

    # ----- interne ------------------------------------------------------------------------------
    def _request(self, hci: str, mac: str) -> None:
        if self._inventory.roles_pending:
            return  # redémarrage piloté imminent : le démarrage appliquera l'identité
        self._attempts[mac] = self._attempts.get(mac, 0) + 1
        self._pending[mac] = (hci, self._now().strftime("%Y-%m-%dT%H:%M:%SZ"))
        self._drop_verifier(mac)
        self._verifiers[mac] = asyncio.ensure_future(self._verify(hci, mac))
        self._to_log.add(mac)
        self._dirty = True
        if self._flusher is None or self._flusher.done():
            self._flusher = asyncio.ensure_future(self._flush())

    def _drop_verifier(self, mac: str) -> None:
        task = self._verifiers.pop(mac, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def _ack(self, mac: str) -> None:
        """Acquittement (classe correcte ou abandon) : la MAC quitte le fichier à la prochaine réécriture,
        qui le vide quand plus rien n'est en attente."""
        self._pending.pop(mac, None)
        self._attempts.pop(mac, None)
        self._drop_verifier(mac)
        if mac in self._written:  # le fichier la contient : le réécrire
            self._dirty = True
            if self._flusher is None or self._flusher.done():
                self._flusher = asyncio.ensure_future(self._flush())

    async def _flush(self) -> None:
        """Réécrit atomiquement l'ensemble des MAC en attente (fichier vide s'il n'y en a plus)."""
        await self.sleep(self.debounce)
        while self._dirty:
            self._dirty = False
            entries = [(when, hci, mac) for mac, (hci, when) in self._pending.items()]
            if not entries and not self._written:
                return  # acquitté avant la 1re écriture : le fichier n'a rien à perdre
            # Requêtes que CETTE écriture porte (instantané avant l'écriture) : une requête (ré)émise pendant
            # l'écriture reste à journaliser et sera écrite par le tour suivant (sinon elle serait perdue du journal).
            carried = self._to_log & {mac for _, _, mac in entries}
            self._to_log -= carried
            try:
                await self.write(self._target, entries)
            except (
                OSError
            ) as exc:  # jamais fatal : les MAC restent en attente pour la prochaine écriture
                self._to_log |= carried
                for _, hci, mac in entries:
                    log.warning(
                        kv("identity_request_failed", hci=hci, mac=mac, error=exc.strerror or exc)
                    )
                return
            self._written = {mac for _, _, mac in entries}
            for _, hci, mac in entries:
                if mac in carried:
                    log.info(kv("identity_requested", hci=hci, mac=mac))

    async def _verify(self, hci: str, mac: str) -> None:
        await self.sleep(self.verify_delay)
        info = next((i for i in self._registry.infos if i.mac == mac), None)
        observed = self._inventory.adapter_class(mac)
        if info is None or info.path is None:
            self._ack(mac)  # plus affecté / plus présent : rien à vérifier
            return
        if observed is not None and (observed & CLASS_MASK) == expected_class(info.roles):
            self._ack(mac)
            return
        if self._inventory.roles_pending:
            self._ack(mac)
            return
        if self._attempts.get(mac, 0) >= self.max_attempts:
            log.error(
                kv(
                    "identity_giving_up",
                    hci=hci,
                    mac=mac,
                    attempts=self._attempts.get(mac, 0),
                    observed=None if observed is None else f"0x{observed:06x}",
                )
            )
            self._ack(mac)
            return
        self._verifiers.pop(mac, None)
        self._request(info.hci or hci, mac)
