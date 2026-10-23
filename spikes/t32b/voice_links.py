#!/usr/bin/env python3
"""Liens de voix bidirectionnels PC <-> casque (#6) : le PC (HF sur hci-src) parle au casque (AG sur hci-hp) via PipeWire.

Deux liens : voix du PC -> écouteurs du casque, micro du casque -> PC. Les nœuds se désignent par nom exact ou par
`@hciN[:classe[:texte]]` (cf. 07-routing/router.py). Les liens vivent tant que le script tourne (session pw-cli) ; Ctrl-C les retire.
Usage : voice_links.py --pc-in SPEC --hs-out SPEC --hs-in SPEC --pc-out SPEC [--hold SECONDES]
  --pc-in  : nœud qui reçoit la voix du PC (ex. @hci0:Stream/Output/Audio)   --hs-out : lecture vers le casque (ex. @hci1:Audio/Sink)
  --hs-in  : micro du casque (ex. @hci1:Audio/Source)                         --pc-out : retour vers le PC (ex. @hci0:Stream/Input/Audio)
Provisoire — à valider avec les dongles UB500 (T3.2b).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "07-routing"))

from pw_graph import Graph  # noqa: E402
from router import PwCliSession, link_source, resolve_node  # noqa: E402


async def main_async(args: argparse.Namespace) -> int:
    graph = Graph()
    await graph.start()
    await asyncio.wait_for(graph.synced.wait(), 10)
    specs = {"pc-in": args.pc_in, "hs-out": args.hs_out, "hs-in": args.hs_in, "pc-out": args.pc_out}
    nodes = {k: resolve_node(graph, v) for k, v in specs.items()}
    missing = [k for k, n in nodes.items() if n is None]
    if missing:
        print("nœuds introuvables :", {k: specs[k] for k in missing}, file=sys.stderr)
        await graph.stop()
        return 2
    linker = PwCliSession(graph)
    await linker.start()
    try:
        await link_source(graph, nodes["pc-in"], nodes["hs-out"], linker)  # type: ignore[arg-type]
        await link_source(graph, nodes["hs-in"], nodes["pc-out"], linker)  # type: ignore[arg-type]
        print("voix PC -> casque et casque -> PC liées ; Ctrl-C pour retirer", flush=True)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), args.hold or None)
    finally:
        await linker.stop()
        await graph.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    for name in ("pc-in", "hs-out", "hs-in", "pc-out"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--hold", type=float, default=0, help="durée max (s) ; 0 = jusqu'à Ctrl-C")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
