#!/usr/bin/env python3
"""Pause / reprise d'un flux vers un sink réel : délais de passage `running` -> `idle/suspended` et retour.

Lie une source virtuelle (tonalité 440 Hz) au sink, attend `running`, supprime les liens (pause), mesure le
temps jusqu'à ce que le sink quitte `running`, puis relie (reprise) et mesure le retour à `running`.
Usage : sink_state.py --sink bluez_output.XX [--rounds 3] [--out sink-state.json]
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
from virtual import SOURCE_NAMES, Virtual, make_tone


async def main_async(args: argparse.Namespace) -> int:
    graph = Graph()
    await graph.start()
    await asyncio.wait_for(graph.synced.wait(), 10)
    tone = Path(args.tone).with_name("tone440.wav")
    if not tone.exists():
        make_tone(tone, freq=440.0)
    virtual = Virtual(graph, tone)
    await virtual.create(names=(SOURCE_NAMES[0],), with_sink=False)
    sink, src = graph.node_by_name(args.sink), graph.node_by_name(SOURCE_NAMES[0])
    if sink is None or src is None:
        print("nœuds introuvables")
        return 2
    linker = PwCliSession(graph)
    await linker.start()
    rounds = []
    try:
        for i in range(args.rounds):
            t0 = time.perf_counter()
            await link_source(graph, src, sink, linker)
            await graph.wait_for(lambda: graph.nodes[sink.id].state == "running", 15)
            t_run = (time.perf_counter() - t0) * 1000
            await asyncio.sleep(2.0)
            t1 = time.perf_counter()
            await unlink_source(graph, src, linker)
            await graph.wait_for(lambda: graph.nodes[sink.id].state != "running", 30)
            t_idle = (time.perf_counter() - t1) * 1000
            state_after = graph.nodes[sink.id].state
            rounds.append(
                {
                    "round": i + 1,
                    "resume_to_running_ms": t_run,
                    "pause_to_not_running_ms": t_idle,
                    "state_after_pause": state_after,
                }
            )
            print(rounds[-1], flush=True)
            await asyncio.sleep(1.0)
    finally:
        await linker.stop()
        await virtual.destroy()
        await graph.stop()
    if args.out:
        Path(args.out).write_text(json.dumps(rounds, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sink", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--tone", default="out/tone180.wav")
    parser.add_argument("--out")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
