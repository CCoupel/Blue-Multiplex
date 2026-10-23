#!/usr/bin/env python3
"""Reconstruction des liens après `systemctl --user restart pipewire wireplumber`.

Mémorise la route voulue (source -> sink), redémarre PipeWire/WirePlumber, attend que le démon réponde de
nouveau (seule boucle de reconnexion : tant que le démon est arrêté il n'y a aucun événement à écouter),
attend la réapparition des nœuds (événements du graphe) puis recrée les liens. Mesure chaque jalon.

Usage :
  relink_after_restart.py --virtual                      (hors matériel : sink et source virtuels recréés)
  relink_after_restart.py --source bluez_input.XX --sink bluez_output.YY   (nœuds réels : ils réapparaissent seuls)
Provisoire — à revalider avec dongle RTL8761B (spike #7).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from pw_graph import Graph
from router import PwCliSession, link_source, unlink_source
from virtual import SINK_NAME, SOURCE_NAMES, Virtual, _run, make_tone

NODE_TIMEOUT = 60.0


async def connect_graph(timeout: float) -> Graph:
    """Redémarre un `pw-dump -m` jusqu'à ce que le démon réponde (reconnexion après un restart)."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        graph = Graph()
        await graph.start()
        try:
            await asyncio.wait_for(graph.synced.wait(), 1.0)
            return graph
        except TimeoutError:
            await graph.stop()
            await asyncio.sleep(0.1)
    raise TimeoutError("PipeWire ne répond pas")


async def main_async(args: argparse.Namespace) -> int:
    graph = await connect_graph(10)
    virtual: Virtual | None = None
    if args.virtual:
        tone = Path(args.tone)
        if not tone.exists():
            make_tone(tone)
        virtual = Virtual(graph, tone)
        await virtual.create()
        src_name, sink_name = SOURCE_NAMES[0], SINK_NAME
    else:
        src_name, sink_name = args.source, args.sink
    src, sink = graph.node_by_name(src_name), graph.node_by_name(sink_name)
    if src is None or sink is None:
        print("nœuds introuvables")
        return 2
    linker = PwCliSession(graph)
    await linker.start()
    await unlink_source(graph, src, linker)
    await link_source(graph, src, sink, linker)
    print(f"route initiale : {src_name} -> {sink_name} ({len(graph.links_from(src.id))} liens)")
    await linker.stop()

    # ---- redémarrage ----------------------------------------------------------------------
    t0 = time.perf_counter()
    code, out = await _run("systemctl", "--user", "restart", "pipewire", "wireplumber")
    t_cmd = time.perf_counter()
    if code != 0:
        print("restart en échec :", out)
        return 3
    await asyncio.wait_for(graph.exited.wait(), 10)
    await graph.stop()
    graph = await connect_graph(30)
    t_back = time.perf_counter()
    if virtual is not None:
        virtual.graph = graph
        virtual.players = {n: p for n, p in virtual.players.items() if p.returncode is None}
        await virtual.create()
    await graph.wait_for(
        lambda: graph.node_by_name(src_name) and graph.node_by_name(sink_name), NODE_TIMEOUT
    )
    t_nodes = time.perf_counter()
    src, sink = graph.node_by_name(src_name), graph.node_by_name(sink_name)
    assert src is not None and sink is not None
    await graph.wait_for(
        lambda: graph.ports_of(src.id, "output") and graph.ports_of(sink.id, "input"), 10
    )
    linker = PwCliSession(graph)
    await linker.start()
    # Après un restart WirePlumber peut avoir lié la source au sink par défaut : routage exclusif.
    await unlink_source(graph, src, linker)
    ids = await link_source(graph, src, sink, linker)
    await graph.wait_for(
        lambda: all(graph.links[i].state == "active" for i in ids if i in graph.links), 10
    )
    t_relinked = time.perf_counter()
    await linker.stop()
    result = {
        "restart_cmd_ms": (t_cmd - t0) * 1000,
        "pipewire_back_ms": (t_back - t0) * 1000,
        "nodes_back_ms": (t_nodes - t0) * 1000,
        "relinked_ms": (t_relinked - t0) * 1000,
        "links": len(ids),
    }
    print(json.dumps(result, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1))
    if virtual is not None:
        await virtual.destroy()
    await graph.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--virtual", action="store_true")
    parser.add_argument("--source")
    parser.add_argument("--sink")
    parser.add_argument("--tone", default="out/tone180.wav")
    parser.add_argument("--out")
    args = parser.parse_args()
    if not args.virtual and not (args.source and args.sink):
        parser.error("--virtual, ou --source et --sink")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
