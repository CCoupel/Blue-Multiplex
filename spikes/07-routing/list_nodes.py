#!/usr/bin/env python3
"""Liste les nœuds audio du graphe (nom, classe, état) avec leurs ports : pour choisir --sink / --a de router.py.

Usage : list_nodes.py [sous-chaîne du nom, ex. bluez]
Provisoire — à revalider avec dongle RTL8761B (spike #7).
"""

from __future__ import annotations

import asyncio
import sys

from pw_graph import Graph


async def main() -> int:
    needle = sys.argv[1] if len(sys.argv) > 1 else ""
    graph = Graph()
    await graph.start()
    await asyncio.wait_for(graph.synced.wait(), 10)
    for node in sorted(graph.nodes.values(), key=lambda n: n.name):
        if needle in node.name and node.media_class:
            outs = ",".join(p.channel for p in graph.ports_of(node.id, "output")) or "-"
            ins = ",".join(p.channel for p in graph.ports_of(node.id, "input")) or "-"
            print(
                f"{node.id:4d} {node.name:45s} {node.media_class:28s} {node.state:10s} out={outs} in={ins}"
            )
    await graph.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
