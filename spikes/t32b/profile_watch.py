#!/usr/bin/env python3
"""Surveille les bascules A2DP <-> HFP d'un appareil (#6/#8) à partir des événements du graphe PipeWire.

Profil déduit du codec d'un nœud actif de l'appareil : aptx/sbc/aac/ldac/… = A2DP, msbc/cvsd/lc3-swb = HFP. Chaque
changement de profil donne une transition horodatée ; `switch_times()` calcule le délai entre la dernière activité de l'ancien
profil et le `running` du nouveau (cible A2DP -> HFP < 2 s). Usage : profile_watch.py --match 84_7B_57_XX_XX_XX [--out profile.json]
Provisoire — à valider avec les dongles UB500 (T3.2b).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "07-routing"))

from pw_graph import Graph  # noqa: E402

HFP_CODECS = {"msbc", "cvsd", "lc3-swb", "lc3_swb"}


def profile_of(codec: str) -> str:
    codec = codec.lower()
    if not codec:
        return ""
    return "hfp" if codec in HFP_CODECS else "a2dp"


def switch_times(events: list[tuple[float, str, str]]) -> list[dict[str, float | str]]:
    """events = [(t, profil, état)] avec profil 'a2dp'|'hfp' et état 'running'|'idle'|'gone'.

    Une bascule = dernier signe d'activité de l'ancien profil (running -> idle/gone) puis `running` du nouveau.
    Retourne [{from, to, ms}].
    """
    result: list[dict[str, float | str]] = []
    active: str | None = None
    left_at: float | None = None
    for t, profile, state in events:
        if state == "running":
            if active and profile != active and left_at is not None:
                result.append({"from": active, "to": profile, "ms": (t - left_at) * 1000})
            active, left_at = profile, None
        elif profile == active:
            left_at = t
    return result


async def main_async(args: argparse.Namespace) -> int:
    graph = Graph()
    events: list[tuple[float, str, str]] = []

    def on_event(t: float, kind: str, obj: object) -> None:
        if not kind.startswith("node"):
            return
        node = obj  # type: ignore[assignment]
        if args.match not in node.name:  # type: ignore[attr-defined]
            return
        profile = profile_of(str(node.props.get("api.bluez5.codec", "")))  # type: ignore[attr-defined]
        if not profile:
            return
        state = "gone" if kind.endswith("removed") else node.state  # type: ignore[attr-defined]
        events.append((t, profile, state))
        print(f"{time.strftime('%H:%M:%S')} {node.name} {profile} {state}", flush=True)  # type: ignore[attr-defined]

    graph.listeners.append(on_event)
    await graph.start()
    await asyncio.wait_for(graph.synced.wait(), 10)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    print("surveillance active ; Ctrl-C pour terminer", flush=True)
    await stop.wait()
    await graph.stop()
    times = switch_times(events)
    print(json.dumps(times, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps({"events": events, "switches": times}, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--match", required=True, help="sous-chaîne du nom des nœuds de l'appareil (MAC avec _)"
    )
    parser.add_argument("--out")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
