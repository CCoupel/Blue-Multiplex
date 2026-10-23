#!/usr/bin/env python3
"""Journalise en direct l'appairage/connexion des appareils vus par BlueZ (spike #5).

Une ligne JSON par événement : Device1 (Paired, Connected, Trusted, UUIDs, Class, Name...) et
MediaTransport1 (State, Codec, Volume) pour les appareils de l'adaptateur BTMUX_ADAPTER_MAC.
Ctrl-C pour arrêter.
Usage : pair_watch.py [--mac MAC] [--out FICHIER.jsonl]
Provisoire — à revalider avec dongle RTL8761B.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from dbus_fast import BusType, Message, MessageType  # noqa: E402
from dbus_fast.aio import MessageBus  # noqa: E402
from resolve_adapter import DEFAULT_MAC, find_adapter, managed_objects  # noqa: E402

DEVICE = "org.bluez.Device1"
TRANSPORT = "org.bluez.MediaTransport1"
WATCHED = {DEVICE, TRANSPORT}
DEVICE_KEYS = (
    "Address",
    "Name",
    "Alias",
    "Class",
    "Icon",
    "Paired",
    "Bonded",
    "Connected",
    "Trusted",
    "UUIDs",
)


def plain(value: Any) -> Any:
    """Variant D-Bus -> valeur JSON."""
    value = getattr(value, "value", value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


class Watcher:
    def __init__(self, adapter_path: str, out: Path | None) -> None:
        self.adapter_path = adapter_path
        self.out = out.open("a", encoding="utf-8") if out else None

    def emit(self, event: str, path: str, data: dict[str, Any]) -> None:
        record = {"t": round(time.time(), 3), "event": event, "path": path, **data}
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        print(line, flush=True)
        if self.out:
            self.out.write(line + "\n")
            self.out.flush()

    def mine(self, path: str) -> bool:
        return path.startswith(self.adapter_path + "/")

    def interface_data(self, iface: str, props: dict[str, Any]) -> dict[str, Any]:
        data = {k: plain(v) for k, v in props.items()}
        if iface == DEVICE:
            data = {k: v for k, v in data.items() if k in DEVICE_KEYS or k == "Connected"}
        return {"iface": iface.rsplit(".", 1)[-1], **data}

    def handle(self, msg: Message) -> None:
        if msg.message_type != MessageType.SIGNAL:
            return
        if msg.member == "PropertiesChanged" and msg.interface == "org.freedesktop.DBus.Properties":
            iface, changed, _ = msg.body
            if iface in WATCHED and self.mine(msg.path or ""):
                self.emit("changed", msg.path or "", self.interface_data(iface, changed))
        elif msg.member == "InterfacesAdded":
            path, ifaces = msg.body
            if self.mine(path):
                for iface, props in ifaces.items():
                    if iface in WATCHED:
                        self.emit("added", path, self.interface_data(iface, props))
        elif msg.member == "InterfacesRemoved":
            path, ifaces = msg.body
            if self.mine(path):
                for iface in ifaces:
                    if iface in WATCHED:
                        self.emit("removed", path, {"iface": iface.rsplit(".", 1)[-1]})


async def run(mac: str, out: Path | None) -> int:
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    adapter = await find_adapter(bus, mac)
    if adapter is None:
        print(f"aucun adaptateur BlueZ avec la MAC {mac}", file=sys.stderr)
        return 1
    watcher = Watcher(adapter, out)
    watcher.emit("start", adapter, {"mac": mac})
    for path, ifaces in (await managed_objects(bus)).items():  # état initial
        if watcher.mine(path):
            for iface, props in ifaces.items():
                if iface in WATCHED:
                    watcher.emit("initial", path, watcher.interface_data(iface, props))
    bus.add_message_handler(watcher.handle)
    await bus.call(
        Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="AddMatch",
            signature="s",
            body=["type='signal',sender='org.bluez'"],
        )
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    watcher.emit("stop", adapter, {})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--mac", default=os.environ.get("BTMUX_ADAPTER_MAC", DEFAULT_MAC))
    parser.add_argument("--out", type=Path, help="fichier JSON Lines (ajout)")
    args = parser.parse_args()
    return asyncio.run(run(args.mac, args.out))


if __name__ == "__main__":
    sys.exit(main())
