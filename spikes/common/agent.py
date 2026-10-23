#!/usr/bin/env python3
"""Agent BlueZ `NoInputNoOutput` pour les séances (référence pour l'agent de btmuxd, #20).

Règles (décisions du spike #5 et de la v0.2.0) :
  - **fenêtre d'appairage** : les appairages entrants (`RequestAuthorization`, `RequestConfirmation`, `RequestPinCode`…) ne sont
    acceptés que pendant une fenêtre ouverte (`--window SECONDES` à partir du lancement, ou tant que le fichier
    `--window-file` existe), et seulement sur l'adaptateur du rôle `sources` ; hors fenêtre : `org.bluez.Error.Rejected` ;
  - **autorisation de profil** (`AuthorizeService`) : acceptée pour un appareil déjà `Trusted` ; refusée sinon ;
  - un appareil accepté est marqué `Trusted` ; s'il est sur l'adaptateur du rôle `headsets`, le Pi **initie la connexion**
    (`Device1.Connect`) une fois appairé (les sources ne rappellent pas d'elles-mêmes, constat #5).
Usage : agent.py [--config /etc/btmux/config.yaml] [--window 60] [--window-file out/window.open] [--path /btmux/agent]
Provisoire — à valider avec les dongles UB500 (T3.2b).
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


@dataclass
class PairingPolicy:
    """Décisions pures (testables sans D-Bus)."""

    sources_adapter: str | None = None  # chemin D-Bus de l'adaptateur `sources`
    window_until: float = 0.0
    window_file: Path | None = None
    clock: Callable[[], float] = time.monotonic

    def open_window(self, seconds: float) -> None:
        self.window_until = self.clock() + seconds

    def window_open(self) -> bool:
        if self.window_file is not None and self.window_file.exists():
            return True
        return self.clock() < self.window_until

    def accept_pairing(self, adapter: str) -> bool:
        """Appairage entrant : fenêtre ouverte ET adaptateur `sources`."""
        return self.window_open() and (
            self.sources_adapter is None or adapter == self.sources_adapter
        )

    @staticmethod
    def accept_service(trusted: bool) -> bool:
        """Autorisation de profil : seulement pour un appareil déjà de confiance."""
        return trusted


def build_agent_class():  # type: ignore[no-untyped-def]
    """Classe d'agent D-Bus (module séparé : dbus-fast lit les annotations, `from __future__ import annotations` l'interdit)."""
    from agent_service import make_agent_class

    return make_agent_class()


async def run(args: argparse.Namespace) -> int:
    from dbus_fast import BusType, Message, MessageType, Variant
    from dbus_fast.aio import MessageBus
    from resolve_adapter import find_adapter, mac_for_role

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    policy = PairingPolicy(window_file=Path(args.window_file) if args.window_file else None)
    policy.sources_adapter = await find_adapter(bus, mac_for_role(args.config, "sources"))
    headsets_adapter = await find_adapter(bus, mac_for_role(args.config, "headsets"))
    if args.window:
        policy.open_window(args.window)

    def log(msg: str) -> None:
        print(f"{time.strftime('%H:%M:%S', time.gmtime())}Z agent : {msg}", flush=True)

    async def get_prop(path: str, iface: str, prop: str):  # type: ignore[no-untyped-def]
        reply = await bus.call(
            Message(
                destination="org.bluez",
                path=path,
                interface="org.freedesktop.DBus.Properties",
                member="Get",
                signature="ss",
                body=[iface, prop],
            )  # fmt: skip
        )
        return (
            None
            if reply is None or reply.message_type == MessageType.ERROR
            else reply.body[0].value
        )

    async def decide(kind: str, device: str) -> bool:
        adapter = device.rsplit("/dev_", 1)[0]
        if kind.startswith("AuthorizeService"):
            return policy.accept_service(
                bool(await get_prop(device, "org.bluez.Device1", "Trusted"))
            )
        return policy.accept_pairing(adapter)

    async def trust_and_connect(device: str) -> None:
        await bus.call(
            Message(
                destination="org.bluez",
                path=device,
                interface="org.freedesktop.DBus.Properties",
                member="Set",
                signature="ssv",
                body=["org.bluez.Device1", "Trusted", Variant("b", True)],
            )  # fmt: skip
        )
        log(f"{device} marqué Trusted")
        if headsets_adapter and device.startswith(headsets_adapter + "/"):
            for _ in range(30):  # attend l'appairage puis initie la connexion depuis le Pi
                if await get_prop(device, "org.bluez.Device1", "Paired"):
                    await bus.call(
                        Message(
                            destination="org.bluez",
                            path=device,
                            interface="org.bluez.Device1",
                            member="Connect",
                        )
                    )
                    log(f"{device} : connexion initiée par le Pi")
                    return
                await asyncio.sleep(1)

    agent_cls = build_agent_class()
    agent = agent_cls(decide, lambda dev: asyncio.ensure_future(trust_and_connect(dev)), log)
    bus.export(args.path, agent)
    manager = await bus.introspect("org.bluez", "/org/bluez")
    iface = bus.get_proxy_object("org.bluez", "/org/bluez", manager).get_interface(
        "org.bluez.AgentManager1"
    )
    await iface.call_register_agent(args.path, "NoInputNoOutput")  # type: ignore[attr-defined]
    await iface.call_request_default_agent(args.path)  # type: ignore[attr-defined]
    log(
        f"enregistré ({args.path}), fenêtre {'ouverte ' + str(args.window) + ' s' if args.window else 'fermée'}"
        f"{', fichier ' + args.window_file if args.window_file else ''}"
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await iface.call_unregister_agent(args.path)  # type: ignore[attr-defined]
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--config", default="/etc/btmux/config.yaml")
    parser.add_argument(
        "--window",
        type=float,
        default=0,
        help="ouvre la fenêtre d'appairage N secondes au lancement",
    )
    parser.add_argument(
        "--window-file", help="la fenêtre est ouverte tant que ce fichier existe (touch/rm)"
    )
    parser.add_argument("--path", default="/btmux/agent")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
