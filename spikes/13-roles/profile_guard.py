#!/usr/bin/env python3
"""Prototype #13, repli « filtrage par le daemon » : profils DISTANTS incohérents avec le rôle du contrôleur.

Principe : sur un contrôleur `sources` (le Pi = casque), le Pi ne doit utiliser ni A2DP source ni HFP AG vers l'appareil
(il n'y a pas de sens à « jouer » vers un PC qui expose aussi un puits A2DP / HF) ; sur un contrôleur `headsets` (le Pi =
source), ni A2DP sink ni HFP HF. Les profils interdits sont ceux que l'appareil distant annonce en UUID et vers lesquels
BlueZ/PipeWire se connecteraient : `Device1.DisconnectProfile(uuid)` les coupe.

  sources  : interdit = UUID distants A2DP sink (110b) et HFP HF (111e)  [le Pi ne joue pas VERS eux]
  headsets : interdit = UUID distants A2DP source (110a) et HFP AG (111f) [le Pi ne reçoit pas DEPUIS eux]
Par défaut : lecture seule (liste ce qui serait fait). `--apply` appelle DisconnectProfile (hors séance, appareil connu).
Les rôles/hciN viennent de `btmuxctl controllers`. Provisoire — à valider avec les dongles UB500 (T3.2b).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))

FORBIDDEN = {
    "sources": {
        "0000110b-0000-1000-8000-00805f9b34fb": "A2DP sink",
        "0000111e-0000-1000-8000-00805f9b34fb": "HFP HF",
    },
    "headsets": {
        "0000110a-0000-1000-8000-00805f9b34fb": "A2DP source",
        "0000111f-0000-1000-8000-00805f9b34fb": "HFP AG",
    },
}


def plan(roles_by_hci: dict[str, str], objects: dict[str, dict[str, dict[str, object]]]):
    """Logique pure : liste (chemin appareil, uuid, libellé, rôle) des profils à couper. `objects` = GetManagedObjects."""
    todo = []
    for path, ifaces in objects.items():
        dev = ifaces.get("org.bluez.Device1")
        if dev is None:
            continue
        hci = path.split("/")[3]
        role = roles_by_hci.get(hci)
        if role is None:
            continue
        uuids = [str(u).lower() for u in getattr(dev["UUIDs"], "value", dev["UUIDs"])]
        for uuid, label in FORBIDDEN[role].items():
            if uuid in uuids:
                todo.append(
                    (
                        path,
                        uuid,
                        label,
                        role,
                        bool(getattr(dev["Connected"], "value", dev["Connected"])),
                    )
                )
    return todo


async def run(apply: bool) -> int:
    from dbus_fast import BusType, Message
    from dbus_fast.aio import MessageBus
    from resolve_adapter import managed_objects

    raw = subprocess.run(
        ["/opt/btmux/bin/btmuxctl", "controllers"], capture_output=True, text=True, check=True
    ).stdout
    roles = {c["hci"]: c["role"] for c in json.loads(raw)["controllers"] if c.get("role")}
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    for path, uuid, label, role, connected in plan(roles, await managed_objects(bus)):
        masked = path.rsplit("/dev_", 1)[0] + "/dev_<MAC>"
        print(
            f"{masked} ({role}) : profil distant {label} [{uuid}] connecté={connected}", flush=True
        )
        if apply and connected:
            await bus.call(
                Message(
                    destination="org.bluez",
                    path=path,
                    interface="org.bluez.Device1",
                    member="DisconnectProfile",
                    signature="s",
                    body=[uuid],
                )
            )
            print("  -> DisconnectProfile envoyé", flush=True)
    bus.disconnect()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="coupe réellement les profils (défaut : lecture seule)"
    )
    return asyncio.run(run(parser.parse_args().apply))


if __name__ == "__main__":
    sys.exit(main())
