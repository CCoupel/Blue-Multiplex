#!/usr/bin/env python3
"""Mesure, à partir des événements du graphe, le trou/chevauchement et l'écart FL/FR d'une bascule.

Pour chaque bascule A<->B (sink et sources virtuels, aucun accès Bluetooth) :
  gap_ms  = (1er lien de la nouvelle source `active`) - (dernier lien de l'ancienne source supprimé)
            > 0 : trou (silence), < 0 : chevauchement (les deux sources audibles en même temps)
  skew_ms = écart entre les liens FL et FR de la nouvelle source (instants où chaque lien devient `active`)
Méthodes : pwcli, pwlink-seq, pwlink-par (router.py) et lua (clé `btmux.route`, script déjà chargé).
Provisoire — à revalider avec dongle RTL8761B (spike #7).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

from pw_graph import Graph
from router import make_linker, switch
from virtual import SINK_NAME, SOURCE_NAMES, Virtual, _run, make_tone


def analyse(graph: Graph, events: list, old_id: int | None, new_id: int) -> dict[str, float | None]:
    removed = [t for t, kind, lk in events if kind == "link-removed" and lk.out_node == old_id]
    active: dict[str, float] = {}
    for t, kind, lk in events:
        if kind == "link" and lk.out_node == new_id and lk.state == "active":
            port = graph.ports.get(lk.in_port)
            active.setdefault(port.channel if port else str(lk.in_port), t)
    if not active:
        return {"gap_ms": None, "skew_ms": None}
    first, last = min(active.values()), max(active.values())
    gap = (first - max(removed)) * 1000 if removed else None
    return {"gap_ms": gap, "skew_ms": (last - first) * 1000}


async def run(method: str, cycles: int, tone: Path) -> list[dict[str, float | None]]:
    graph = Graph()
    await graph.start()
    await asyncio.wait_for(graph.synced.wait(), 10)
    virtual = Virtual(graph, tone)
    await virtual.create()
    a, b = (graph.node_by_name(n) for n in SOURCE_NAMES)
    sink = graph.node_by_name(SINK_NAME)
    assert a and b and sink
    linker = None if method == "lua" else make_linker(method, graph)
    if linker:
        await linker.start()
    results = []
    current = None
    try:
        for target in [a, b] * cycles + [a]:
            mark = len(graph.events)
            if linker:
                await switch(graph, current, target, sink, linker)
            else:
                await _run(
                    "pw-metadata", "-n", "default", "0", "btmux.route",
                    f"{target.name}>{SINK_NAME}", "Spa:String",
                )  # fmt: skip
                other = b if target is a else a
                await graph.wait_for(
                    lambda t=target, o=other: (
                        len(
                            [
                                lk
                                for lk in graph.links_between(t.id, sink.id)
                                if lk.state == "active"
                            ]
                        )
                        >= 2
                        and not graph.links_between(o.id, sink.id)
                    ),
                    10,
                )
            await asyncio.sleep(0.5)
            if current is not None:
                results.append(analyse(graph, graph.events[mark:], current.id, target.id))
            current = target
    finally:
        if linker:
            await linker.stop()
        else:
            await _run("pw-metadata", "-n", "default", "0", "btmux.route", "", "Spa:String")
        await virtual.destroy()
        await graph.stop()
    return results


def stats(values: list[float]) -> dict[str, float]:
    return (
        {"min": min(values), "median": statistics.median(values), "max": max(values)}
        if values
        else {}
    )


async def main_async(args: argparse.Namespace) -> int:
    tone = Path(args.tone)
    if not tone.exists():
        make_tone(tone)
    report = {}
    for method in args.methods:
        res = await run(method, args.cycles, tone)
        gaps = [r["gap_ms"] for r in res if r["gap_ms"] is not None]
        skews = [r["skew_ms"] for r in res if r["skew_ms"] is not None]
        report[method] = {"n": len(res), "gap_ms": stats(gaps), "skew_ms": stats(skews)}  # type: ignore[arg-type]
        print(method, json.dumps(report[method]))
        await asyncio.sleep(1)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--methods", nargs="+", default=["pwcli", "pwlink-seq", "pwlink-par"])
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--tone", default="out/tone180.wav")
    parser.add_argument("--out")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
