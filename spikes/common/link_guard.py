#!/usr/bin/env python3
"""Plafond de liens ACL par adaptateur : déconnecte et bloque l'appareil en trop (BlueZ, D-Bus).

Les sources (téléphone, PC) se reconnectent d'elles-mêmes et peuvent dépasser le plafond sûr d'un contrôleur
(2 ACL sur le Bluetooth interne du Pi 3 ; à mesurer avec les UB500). `link_guard` surveille `Device1.Connected` ;
quand le nombre d'appareils connectés d'un adaptateur dépasse son plafond, l'appareil qui vient de se connecter est
déconnecté puis **bloqué** (`Device1.Blocked = true`) pour qu'il ne se reconnecte pas. À l'arrêt (SIGINT/SIGTERM) les appareils
bloqués par ce programme sont débloqués (sauf `--keep-blocked`).

Usage : link_guard.py [--config /etc/btmux/config.yaml] [--cap sources=2] [--cap headsets=1] [--cap-default 2] [--keep-blocked]
Plafond par défaut : 2 par adaptateur. Provisoire — à valider avec les dongles UB500 (T3.2b).
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


@dataclass
class LinkPolicy:
    """Logique pure (testable sans D-Bus) : suivi des appareils connectés par adaptateur et décision de blocage."""

    caps: dict[str, int]  # chemin d'adaptateur -> plafond
    default_cap: int = 2
    connected: dict[str, list[str]] = field(
        default_factory=dict
    )  # adaptateur -> appareils, dans l'ordre d'arrivée

    def cap_for(self, adapter: str) -> int:
        return self.caps.get(adapter, self.default_cap)

    def on_connected(self, adapter: str, device: str) -> str | None:
        """Retourne `device` si ce nouvel appareil dépasse le plafond (à déconnecter puis bloquer), sinon None."""
        devices = self.connected.setdefault(adapter, [])
        if device in devices:
            return None
        devices.append(device)
        if len(devices) > self.cap_for(adapter):
            devices.remove(device)
            return device
        return None

    def on_disconnected(self, adapter: str, device: str) -> None:
        devices = self.connected.get(adapter, [])
        if device in devices:
            devices.remove(device)


def parse_caps(items: list[str]) -> dict[str, int]:
    caps: dict[str, int] = {}
    for item in items:
        key, _, value = item.partition("=")
        if not key or not value.isdigit() or int(value) < 1:
            raise ValueError(f"--cap attend ROLE=N (N >= 1), reçu '{item}'")
        caps[key] = int(value)
    return caps


async def run(args: argparse.Namespace) -> int:
    from dbus_fast import BusType, Message, MessageType, Variant
    from dbus_fast.aio import MessageBus
    from resolve_adapter import find_adapter, mac_for_role, managed_objects

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    role_caps = parse_caps(args.cap)
    caps: dict[str, int] = {}
    for role, cap in role_caps.items():
        path = await find_adapter(bus, mac_for_role(args.config, role))
        if path is None:
            print(f"AVERTISSEMENT : adaptateur du rôle '{role}' introuvable", file=sys.stderr)
            continue
        caps[path] = cap
    policy = LinkPolicy(caps, args.cap_default)
    blocked: list[str] = []
    device_adapter: dict[str, str] = {}

    async def call(
        path: str, iface: str, member: str, sig: str = "", body: list | None = None
    ) -> None:
        reply = await bus.call(
            Message(
                destination="org.bluez",
                path=path,
                interface=iface,
                member=member,
                signature=sig,
                body=body or [],
            )
        )
        if reply is not None and reply.message_type == MessageType.ERROR:
            print(f"  erreur {member} {path} : {reply.body}", file=sys.stderr)

    async def set_blocked(path: str, value: bool) -> None:
        await call(
            path,
            "org.freedesktop.DBus.Properties",
            "Set",
            "ssv",
            ["org.bluez.Device1", "Blocked", Variant("b", value)],
        )

    def log(msg: str) -> None:
        print(f"{time.strftime('%H:%M:%S', time.gmtime())}Z link_guard : {msg}", flush=True)

    async def handle(msg: Message) -> None:
        if msg.member != "PropertiesChanged" or not (msg.path or "").count("/dev_"):
            return
        iface, changed, _ = msg.body
        if iface != "org.bluez.Device1" or "Connected" not in changed:
            return
        path = msg.path or ""
        adapter = device_adapter.setdefault(path, path.rsplit("/dev_", 1)[0])
        if changed["Connected"].value:
            excess = policy.on_connected(adapter, path)
            log(
                f"{path} connecté ({len(policy.connected.get(adapter, []))}/{policy.cap_for(adapter)} sur {adapter})"
            )
            if excess:
                log(f"PLAFOND dépassé sur {adapter} : déconnexion + blocage de {excess}")
                await call(excess, "org.bluez.Device1", "Disconnect")
                await set_blocked(excess, True)
                blocked.append(excess)
        else:
            policy.on_disconnected(adapter, path)

    for path, ifaces in (await managed_objects(bus)).items():  # état initial
        dev = ifaces.get("org.bluez.Device1")
        if dev and dev["Connected"].value:  # type: ignore[attr-defined]
            policy.on_connected(path.rsplit("/dev_", 1)[0], path)

    bus.add_message_handler(lambda m: asyncio.ensure_future(handle(m)) and None)
    await bus.call(
        Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="AddMatch",
            signature="s",
            body=["type='signal',sender='org.bluez',interface='org.freedesktop.DBus.Properties'"],
        )
    )
    log(f"actif, plafonds {caps or '(défaut ' + str(args.cap_default) + ')'}")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    if blocked and not args.keep_blocked:
        for path in blocked:
            await set_blocked(path, False)
            log(f"{path} débloqué")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--config", default="/etc/btmux/config.yaml")
    parser.add_argument(
        "--cap",
        action="append",
        default=[],
        metavar="ROLE=N",
        help="plafond d'un rôle (sources|headsets)",
    )
    parser.add_argument(
        "--cap-default", type=int, default=2, help="plafond des autres adaptateurs (défaut 2)"
    )
    parser.add_argument("--keep-blocked", action="store_true", help="ne pas débloquer à l'arrêt")
    args = parser.parse_args()
    parse_caps(args.cap)  # validation avant de se connecter
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
