#!/usr/bin/env python3
"""Routeur de prototype : bascule d'une source vers une autre par création/suppression de liens `pw-link`.

Mesure, pour chaque bascule A→B puis B→A, le délai entre l'émission de la commande et :
  t_link   : apparition des liens (événement `link` du graphe),
  t_active : tous les liens de la nouvelle source à l'état `active`,
  t_run    : nœud de la nouvelle source à l'état `running` (règle de routage n°3 du cadrage).

Usage :
  router.py --virtual --cycles 12 [--out results.json]            (hors matériel : sources virtuelles)
  router.py --sink bluez_output.XX --a bluez_input.YY --b virt-srcB --cycles 10   (nœuds existants)
  router.py --sink bluez_output.XX --a bluez_input.YY --virtual-b --cycles 10     (B = tonalité virtuelle)
  router.py --sink bluez_output.XX --virtual-sources --cycles 10 --hold 4          (A/B = tonalités 440/660 Hz)
  --sink/--a/--b acceptent `@hciN[:classe[:texte]]` (nœud d'un adaptateur) : router.py --sink @hci1:Audio/Sink --a @hci0:Stream/Output/Audio --virtual-b
Provisoire — à revalider avec dongle RTL8761B (spike #7).
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import re
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

from pw_graph import Graph, Node, Port
from virtual import SINK_NAME, SOURCE_NAMES, Virtual, _run, make_tone


def resolve_node(graph: Graph, spec: str) -> Node | None:
    """Résout un nœud : nom exact, ou `@hciN[:classe[:sous-chaîne]]` = nœud Bluetooth de cet adaptateur.

    Exemples : `@hci1:Audio/Sink` (sink du casque sur hci-hp), `@hci0:Stream/Output/Audio:84_7B` (flux d'un appareil
    dont le nom contient 84_7B sur hci0). Sans classe : premier nœud de l'adaptateur.
    """
    if not spec.startswith("@"):
        return graph.node_by_name(spec)
    adapter, _, rest = spec[1:].partition(":")
    media_class, _, needle = rest.partition(":")
    candidates = [
        n
        for n in graph.nodes.values()
        if graph.adapter_of(n) == adapter
        and (not media_class or n.media_class == media_class)
        and (not needle or needle in n.name)
    ]
    return sorted(candidates, key=lambda n: n.name)[0] if candidates else None


def pair_ports(src: list[Port], sink: list[Port]) -> list[tuple[Port, Port]]:
    """Association des ports : 1 port source -> tous les ports du sink (mono) ; sinon par canal, puis par ordre."""
    if len(src) == 1:
        return [(src[0], p) for p in sink]
    by_channel = {p.channel: p for p in sink}
    pairs = [(s, by_channel[s.channel]) for s in src if s.channel in by_channel]
    return pairs or list(zip(src, sink, strict=False))


class Linker:
    """Mécanisme de création/suppression de liens (comparaison des méthodes)."""

    name = "base"

    async def start(self) -> None:  # pragma: no cover - interface
        return None

    async def stop(self) -> None:  # pragma: no cover - interface
        return None

    def check(self) -> None:
        """Lève RuntimeError si le mécanisme a signalé une erreur (par défaut : rien à signaler)."""
        return None

    async def unlink(self, link_ids: list[int]) -> None:
        raise NotImplementedError

    async def link(self, pairs: list[tuple[Port, Port]]) -> None:
        raise NotImplementedError


class PwLinkSeq(Linker):
    """Un processus `pw-link` par lien, en séquence."""

    name = "pwlink-seq"

    async def unlink(self, link_ids: list[int]) -> None:
        for lid in link_ids:
            await _run("pw-link", "-d", str(lid))

    async def link(self, pairs: list[tuple[Port, Port]]) -> None:
        for out_port, in_port in pairs:
            code, out = await _run("pw-link", str(out_port.id), str(in_port.id))
            if code != 0:
                raise RuntimeError(f"pw-link {out_port.id} {in_port.id} : {out.strip()}")


class PwLinkPar(Linker):
    """Un processus `pw-link` par lien, tous lancés en parallèle."""

    name = "pwlink-par"

    async def unlink(self, link_ids: list[int]) -> None:
        await asyncio.gather(*(_run("pw-link", "-d", str(lid)) for lid in link_ids))

    async def link(self, pairs: list[tuple[Port, Port]]) -> None:
        results = await asyncio.gather(*(_run("pw-link", str(o.id), str(i.id)) for o, i in pairs))
        for code, out in results:
            if code != 0:
                raise RuntimeError(f"pw-link : {out.strip()}")


ERROR_RE = re.compile(r"error id:(\d+) seq:\d+ res:(-\d+) \(([^)]*)\): (.*)")


class PwCliSession(Linker):
    """Une session `pw-cli` persistante : on écrit `create-link` / `destroy` sur son stdin (aucun fork).

    DURÉE DE VIE DES LIENS (vérifiée sur sink virtuel, 2026-10-23) : un lien créé par `create-link` appartient à la
    session. Il est **détruit dès que la session se ferme**, que ce soit par `quit` ou par SIGKILL de `pw-cli`
    (4 liens présents pendant la session, 0 après). Conséquence : si la session meurt, le routage est perdu ;
    btmuxd doit surveiller `proc.returncode` (voir `_send`) et reconstruire la session et les liens.
    ERREURS : `pw-cli` répond « 1 = @proxy:N » même pour un lien invalide ; l'échec arrive plus tard, en asynchrone
    (« remote 0: error id:N seq:S res:-22 (Invalid argument): link-factory: unknown output port 99999 »). On lit donc
    sa sortie (stdout+stderr) et `check()` lève RuntimeError avec ces lignes.
    """

    name = "pwcli-session"

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.proc: asyncio.subprocess.Process | None = None
        self.tail: collections.deque[str] = collections.deque(maxlen=40)
        self.errors: list[str] = []
        self._reader: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            "pw-cli",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._reader = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        async for raw in self.proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            self.tail.append(line)
            match = ERROR_RE.search(line)
            if match:
                self.errors.append(f"id {match[1]} res {match[2]} ({match[3]}) : {match[4]}")

    def check(self) -> None:
        if self.errors:
            errors, self.errors = self.errors, []
            raise RuntimeError("pw-cli a signalé : " + " ; ".join(errors))

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            assert self.proc.stdin is not None
            self.proc.stdin.write(b"quit\n")
            await self.proc.stdin.drain()
            self.proc.stdin.close()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except TimeoutError:
                self.proc.kill()
                raise RuntimeError("pw-cli ne s'est pas fermé en 5 s (tué)") from None
        if self._reader:
            await asyncio.gather(self._reader, return_exceptions=True)

    async def _send(self, text: str) -> None:
        if self.proc is None or self.proc.returncode is not None or self.proc.stdin is None:
            raise RuntimeError("session pw-cli terminée : les liens qu'elle portait sont perdus")
        self.proc.stdin.write(text.encode())
        await self.proc.stdin.drain()

    async def unlink(self, link_ids: list[int]) -> None:
        await self._send("".join(f"destroy {lid}\n" for lid in link_ids))

    async def link(self, pairs: list[tuple[Port, Port]]) -> None:
        lines = [f"create-link {o.node_id} {o.id} {i.node_id} {i.id}\n" for o, i in pairs]
        await self._send("".join(lines))


def make_linker(method: str, graph: Graph) -> Linker:
    return {"pwlink-seq": PwLinkSeq, "pwlink-par": PwLinkPar}.get(
        method, lambda: PwCliSession(graph)
    )()  # type: ignore[return-value]


async def _wait(graph: Graph, linker: Linker, predicate: Callable[[], bool], what: str) -> None:
    """Attend un état du graphe ; en cas de délai dépassé, remonte l'erreur du mécanisme de lien (pw-cli...)."""
    try:
        await graph.wait_for(predicate, timeout=5)
    except TimeoutError:
        linker.check()  # lève avec le détail si pw-cli a signalé une erreur
        tail = " | ".join(getattr(linker, "tail", [])[-3:]) if hasattr(linker, "tail") else ""
        raise RuntimeError(
            f"délai dépassé (5 s) : {what}" + (f" ; sortie pw-cli : {tail}" if tail else "")
        ) from None


async def unlink_source(graph: Graph, source: Node, linker: Linker) -> int:
    """Supprime tous les liens sortants de `source` (routage exclusif : un seul flux vers le sink)."""
    links = graph.links_from(source.id)
    if links:
        ids = {lk.id for lk in links}
        await linker.unlink(sorted(ids))
        await _wait(graph, linker, lambda: not (ids & set(graph.links)), "suppression des liens")
    return len(links)


async def link_source(graph: Graph, source: Node, sink: Node, linker: Linker) -> list[int]:
    pairs = pair_ports(graph.ports_of(source.id, "output"), graph.ports_of(sink.id, "input"))
    before = set(graph.links)
    await linker.link(pairs)
    await _wait(
        graph, linker, lambda: len(set(graph.links) - before) >= len(pairs), "apparition des liens"
    )
    linker.check()
    return sorted(set(graph.links) - before)


async def switch(
    graph: Graph, old: Node | None, new: Node, sink: Node, linker: Linker, order: str = "bbm"
) -> dict[str, float]:
    """Bascule `old` -> `new` vers `sink` ; retourne les délais en millisecondes depuis la commande.

    order="bbm" (break-before-make, défaut) : supprime l'ancienne source puis lie la nouvelle (trou, jamais de mixage).
    order="mbb" (make-before-break) : lie la nouvelle puis supprime l'ancienne (pas de trou, bref mixage des deux).
    """
    t0 = time.perf_counter()
    if order == "bbm":
        if old is not None:
            await unlink_source(graph, old, linker)
        ids = await link_source(graph, new, sink, linker)
    else:
        ids = await link_source(graph, new, sink, linker)
        t_link = time.perf_counter()
        await graph.wait_for(
            lambda: all(graph.links[i].state == "active" for i in ids if i in graph.links), 5
        )
        if old is not None:
            await unlink_source(graph, old, linker)
    t_link = time.perf_counter()
    await graph.wait_for(
        lambda: all(graph.links[i].state == "active" for i in ids if i in graph.links), 5
    )
    t_active = time.perf_counter()
    await graph.wait_for(lambda: graph.nodes[new.id].state == "running", 5)
    t_run = time.perf_counter()
    return {
        "t_link_ms": (t_link - t0) * 1000,
        "t_active_ms": (t_active - t0) * 1000,
        "t_running_ms": (t_run - t0) * 1000,
    }


def summarize(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return {
        "n": len(values),
        "min": ordered[0],
        "median": statistics.median(values),
        "p95": p95,
        "max": ordered[-1],
    }


async def run_cycles(
    graph: Graph, a: Node, b: Node, sink: Node, cycles: int, linker: Linker, hold: float = 0.4
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    current: Node | None = None
    # A -> B -> A ... ; la 1re entrée établit simplement le routage initial
    order = [a, b] * cycles + [a]
    for i, target in enumerate(order):
        res = await switch(graph, current, target, sink, linker)
        if current is not None:
            results.append({"n": i, "from": current.name, "to": target.name, **res})
        current = target
        await asyncio.sleep(hold)  # laisse le flux s'établir (et s'écouter) entre deux bascules
    return results


async def main_async(args: argparse.Namespace) -> int:
    graph = Graph()
    await graph.start()
    await asyncio.wait_for(graph.synced.wait(), 10)
    virtual: Virtual | None = None
    linker = make_linker(args.method, graph)
    # PID enregistré pour que watch_uart.sh puisse l'arrêter (SIGINT) sans `pkill -f`
    pidfile = Path(__file__).resolve().parent / "out" / "router.pid"
    pidfile.parent.mkdir(exist_ok=True)
    pidfile.write_text(str(os.getpid()))
    try:
        if args.virtual:
            tone = Path(args.tone)
            if not tone.exists():
                make_tone(tone)
            virtual = Virtual(graph, tone)
            await virtual.create()
            sink_name, a_name, b_name = SINK_NAME, *SOURCE_NAMES
        elif args.virtual_sources:
            # Sink réel (ex. casque Bluetooth) + deux sources virtuelles aux tonalités distinctes (440 / 660 Hz)
            tones = {}
            for name, freq in zip(SOURCE_NAMES, (440.0, 660.0), strict=True):
                path = Path(args.tone).with_name(f"tone{int(freq)}.wav")
                if not path.exists():
                    make_tone(path, freq=freq)
                tones[name] = path
            virtual = Virtual(graph, Path(args.tone), tones)
            await virtual.create(with_sink=False)
            sink_name, a_name, b_name = args.sink, *SOURCE_NAMES
        elif args.virtual_b:
            # Source A et sink réels (ex. téléphone -> casque) ; source B = tonalité virtuelle (aucun lien BT de plus)
            tone = Path(args.tone)
            if not tone.exists():
                make_tone(tone)
            virtual = Virtual(graph, tone)
            await virtual.create(names=(SOURCE_NAMES[1],), with_sink=False)
            sink_name, a_name, b_name = args.sink, args.a, SOURCE_NAMES[1]
        else:
            sink_name, a_name, b_name = args.sink, args.a, args.b
        nodes = [resolve_node(graph, n) for n in (a_name, b_name, sink_name)]
        if not all(nodes):
            print(
                "nœuds introuvables :",
                [n for n, x in zip((a_name, b_name, sink_name), nodes, strict=True) if not x],
            )
            return 2
        a, b, sink = nodes  # type: ignore[misc]
        await linker.start()
        try:
            results = await run_cycles(graph, a, b, sink, args.cycles, linker, args.hold)
        finally:
            await linker.stop()
    finally:
        pidfile.unlink(missing_ok=True)
        if virtual is not None:
            await virtual.destroy()
        await graph.stop()
    summary = {
        k: summarize([float(r[k]) for r in results])
        for k in ("t_link_ms", "t_active_ms", "t_running_ms")
    }
    print(f"méthode {linker.name} : {len(results)} bascules")
    for key, stats in summary.items():
        print(f"{key:13s} " + " ".join(f"{name}={value:.1f}" for name, value in stats.items()))
    if args.out:
        Path(args.out).write_text(
            json.dumps({"method": linker.name, "results": results, "summary": summary}, indent=1)
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--virtual", action="store_true", help="crée sink + 2 sources virtuelles")
    parser.add_argument(
        "--virtual-b", action="store_true", help="--sink et --a réels, B = source virtuelle"
    )
    parser.add_argument(
        "--virtual-sources", action="store_true", help="--sink réel, A et B = tonalités 440/660 Hz"
    )
    parser.add_argument("--sink")
    parser.add_argument("--a")
    parser.add_argument("--b")
    parser.add_argument("--method", choices=["pwlink-seq", "pwlink-par", "pwcli"], default="pwcli")
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--hold", type=float, default=0.4, help="pause (s) entre deux bascules")
    parser.add_argument("--tone", default="out/tone180.wav")
    parser.add_argument("--out")
    args = parser.parse_args()
    if not args.virtual and not (
        args.sink and (args.virtual_sources or (args.a and (args.b or args.virtual_b)))
    ):
        parser.error("--virtual, ou --sink/--a/--b, ou --sink/--a/--virtual-b")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
