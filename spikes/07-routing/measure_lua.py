#!/usr/bin/env python3
"""Mesure la bascule A<->B pilotée par la variante Lua (clé de métadonnées `btmux.route`).

Prérequis : `wireplumber/btmux-route.lua` chargé dans WirePlumber (cf. README.md). Sources/sink virtuels
(hors matériel). Chaque mesure = écriture de la clé (`pw-metadata`, un processus) -> liens `active` dans le graphe.
On mesure aussi le coût du seul `pw-metadata` (aller-retour sans effet) pour l'isoler.
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
from router import summarize
from virtual import SINK_NAME, SOURCE_NAMES, Virtual, _run, make_tone


async def set_route(value: str) -> None:
    await _run("pw-metadata", "-n", "default", "0", "btmux.route", value, "Spa:String")


async def main_async(args: argparse.Namespace) -> int:
    graph = Graph()
    await graph.start()
    await asyncio.wait_for(graph.synced.wait(), 10)
    tone = Path(args.tone)
    if not tone.exists():
        make_tone(tone)
    if args.sink:  # sink réel + deux sources virtuelles aux tonalités distinctes
        tones = {}
        for name, freq in zip(SOURCE_NAMES, (440.0, 660.0), strict=True):
            path = tone.with_name(f"tone{int(freq)}.wav")
            if not path.exists():
                make_tone(path, freq=freq)
            tones[name] = path
        virtual = Virtual(graph, tone, tones)
        await virtual.create(with_sink=False)
        sink_name = args.sink
    else:
        virtual = Virtual(graph, tone)
        await virtual.create()
        sink_name = SINK_NAME
    a, b = SOURCE_NAMES
    sink = graph.node_by_name(sink_name)
    assert sink is not None
    overhead: list[float] = []
    for _ in range(5):  # coût du lancement de pw-metadata seul (clé sans effet)
        t0 = time.perf_counter()
        await _run("pw-metadata", "-n", "default", "0", "btmux.noop", "x", "Spa:String")
        overhead.append((time.perf_counter() - t0) * 1000)
    results = []
    try:
        current = None
        for i, target in enumerate([a, b] * args.cycles + [a]):
            node = graph.node_by_name(target)
            assert node is not None
            other = graph.node_by_name(b if target == a else a)
            assert other is not None
            t0 = time.perf_counter()
            await set_route(f"{target}>{sink_name}")
            # PipeWire réutilise les identifiants de liens : on teste l'état final (liens de la cible actifs,
            # plus aucun lien de l'autre source), pas l'apparition d'un nouvel identifiant.
            await graph.wait_for(
                lambda n=node, o=other: (
                    len([lk for lk in graph.links_between(n.id, sink.id) if lk.state == "active"])
                    >= 2
                    and not graph.links_between(o.id, sink.id)
                ),
                timeout=10,
            )
            dt = (time.perf_counter() - t0) * 1000
            if current is not None:
                results.append({"n": i, "from": current, "to": target, "t_active_ms": dt})
            current = target
            await asyncio.sleep(0.5)
    finally:
        await set_route("")
        await virtual.destroy()
        await graph.stop()
    summary = summarize([r["t_active_ms"] for r in results])  # type: ignore[misc]
    print(
        f"Lua : {len(results)} bascules, t_active_ms "
        + " ".join(f"{k}={v:.1f}" for k, v in summary.items())
    )
    print(f"coût pw-metadata seul : médiane {sorted(overhead)[len(overhead) // 2]:.1f} ms")
    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {"results": results, "summary": summary, "pw_metadata_ms": overhead}, indent=1
            )
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sink", help="sink réel (sinon sink virtuel)")
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--tone", default="out/tone180.wav")
    parser.add_argument("--out")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
