#!/usr/bin/env python3
"""Résout une MAC d'adaptateur Bluetooth en chemin D-Bus BlueZ (/org/bluez/hciN).

Usage : resolve_adapter.py [--mac MAC] [--path | --index]
MAC par défaut : $BTMUX_ADAPTER_MAC, sinon la MAC relevée sur pi-qualif
(Bluetooth interne, provisoire).
Code de sortie 1 si aucun adaptateur ne porte cette MAC.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus

# Provisoire — à revalider avec dongle RTL8761B (Bluetooth interne du Pi 3 de pi-qualif).
DEFAULT_MAC = "B8:27:EB:1A:2E:D6"
ADAPTER_IFACE = "org.bluez.Adapter1"


async def managed_objects(bus: MessageBus) -> dict[str, dict[str, dict[str, object]]]:
    reply = await bus.call(
        Message(
            destination="org.bluez",
            path="/",
            interface="org.freedesktop.DBus.ObjectManager",
            member="GetManagedObjects",
        )
    )
    if reply is None or reply.message_type == MessageType.ERROR:
        raise RuntimeError(f"GetManagedObjects a échoué : {reply and reply.body}")
    return reply.body[0]  # type: ignore[no-any-return]


async def find_adapter(bus: MessageBus, mac: str) -> str | None:
    wanted = mac.upper()
    for path, ifaces in (await managed_objects(bus)).items():
        props = ifaces.get(ADAPTER_IFACE)
        if props is not None and str(props["Address"].value).upper() == wanted:  # type: ignore[attr-defined]
            return path
    return None


def index_of(path: str) -> int:
    match = re.fullmatch(r"/org/bluez/hci(\d+)", path)
    if match is None:
        raise ValueError(f"chemin d'adaptateur inattendu : {path}")
    return int(match.group(1))


async def _main(mac: str, want_index: bool) -> int:
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        path = await find_adapter(bus, mac)
    finally:
        bus.disconnect()
    if path is None:
        print(f"aucun adaptateur BlueZ avec la MAC {mac}", file=sys.stderr)
        return 1
    print(index_of(path) if want_index else path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--mac", default=os.environ.get("BTMUX_ADAPTER_MAC", DEFAULT_MAC))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--path", action="store_true", help="affiche /org/bluez/hciN (défaut)")
    group.add_argument("--index", action="store_true", help="affiche N (pour btmgmt -i N)")
    args = parser.parse_args()
    return asyncio.run(_main(args.mac, args.index))


if __name__ == "__main__":
    sys.exit(main())
