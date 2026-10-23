#!/usr/bin/env python3
"""Modèle du graphe PipeWire alimenté par événements (`pw-dump -m`), sans polling.

`pw-dump -m` imprime d'abord le graphe complet puis, à chaque changement, un tableau JSON contenant
uniquement les objets modifiés (`info: null` = objet supprimé). On maintient nœuds / ports / liens et on
réveille les attentes (`wait_for`) à chaque mise à jour.

Provisoire — à revalider avec dongle RTL8761B (spike #7, Bluetooth interne du Pi 3).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

NODE = "PipeWire:Interface:Node"
PORT = "PipeWire:Interface:Port"
LINK = "PipeWire:Interface:Link"


@dataclass
class Node:
    id: int
    props: dict[str, Any] = field(default_factory=dict)
    state: str = ""

    @property
    def name(self) -> str:
        return str(self.props.get("node.name", ""))

    @property
    def media_class(self) -> str:
        return str(self.props.get("media.class", ""))


@dataclass
class Port:
    id: int
    props: dict[str, Any] = field(default_factory=dict)
    direction: str = ""

    @property
    def node_id(self) -> int:
        return int(self.props.get("node.id", -1))

    @property
    def channel(self) -> str:
        return str(self.props.get("audio.channel", self.props.get("port.name", "")))


@dataclass
class Link:
    id: int
    out_node: int = -1
    out_port: int = -1
    in_node: int = -1
    in_port: int = -1
    state: str = ""


class Graph:
    """Graphe courant ; `events` reçoit (horodatage perf_counter, genre, objet) à chaque changement."""

    def __init__(self) -> None:
        self.nodes: dict[int, Node] = {}
        self.ports: dict[int, Port] = {}
        self.links: dict[int, Link] = {}
        self.connected = asyncio.Event()
        self.synced = asyncio.Event()  # graphe initial complet reçu
        self.events: list[tuple[float, str, Any]] = []
        self.listeners: list[Callable[[float, str, Any], None]] = []
        self._cond = asyncio.Condition()
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None
        self.exited = asyncio.Event()

    # ---- cycle de vie ------------------------------------------------------------------------
    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            "pw-dump",
            "-m",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.exited.clear()
        self._task = asyncio.create_task(self._reader())

    async def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            await self._proc.wait()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    def reset(self) -> None:
        self.nodes.clear()
        self.ports.clear()
        self.links.clear()
        self.connected.clear()
        self.synced.clear()

    async def _reader(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        decoder = json.JSONDecoder()
        buf = ""
        first = True
        while True:
            chunk = await self._proc.stdout.read(65536)
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="replace")
            while True:
                text = buf.lstrip()
                if not text.rstrip().endswith("]"):
                    break  # tableau incomplet : attendre la suite
                try:
                    objs, end = decoder.raw_decode(text)
                except json.JSONDecodeError:
                    break
                buf = text[end:]
                await self._apply(objs)
                if first:
                    first = False
                    self.connected.set()
                    self.synced.set()
        self.exited.set()
        async with self._cond:
            self._cond.notify_all()

    # ---- application des événements ----------------------------------------------------------
    async def _apply(self, objs: list[dict[str, Any]]) -> None:
        now = time.perf_counter()
        for obj in objs:
            kind, oid, info = obj.get("type"), obj.get("id"), obj.get("info")
            if not isinstance(oid, int):
                continue
            if info is None:
                self._remove(oid, now)
                continue
            if kind == NODE:
                node = self.nodes.setdefault(oid, Node(oid))
                node.props.update(info.get("props") or {})
                node.state = info.get("state", node.state)
                self._emit(now, "node", node)
            elif kind == PORT:
                port = self.ports.setdefault(oid, Port(oid))
                port.props.update(info.get("props") or {})
                port.direction = info.get("direction", port.direction)
                self._emit(now, "port", port)
            elif kind == LINK:
                link = self.links.setdefault(oid, Link(oid))
                link.out_node = info.get("output-node-id", link.out_node)
                link.out_port = info.get("output-port-id", link.out_port)
                link.in_node = info.get("input-node-id", link.in_node)
                link.in_port = info.get("input-port-id", link.in_port)
                link.state = info.get("state", link.state)
                self._emit(now, "link", link)
        async with self._cond:
            self._cond.notify_all()

    def _remove(self, oid: int, now: float) -> None:
        # En mode moniteur, un objet supprimé arrive sans `type` : {"id": N, "info": null}.
        for kind, table in (("node", self.nodes), ("port", self.ports), ("link", self.links)):
            if oid in table:
                self._emit(now, f"{kind}-removed", table.pop(oid))
                return

    def _emit(self, now: float, kind: str, obj: Any) -> None:
        self.events.append((now, kind, obj))
        for cb in self.listeners:
            cb(now, kind, obj)

    # ---- attentes sans polling ---------------------------------------------------------------
    async def wait_for(self, predicate: Callable[[], bool], timeout: float = 10.0) -> float:
        """Attend que `predicate()` soit vrai ; retourne l'instant (perf_counter) où c'est constaté."""
        async with self._cond:
            await asyncio.wait_for(self._cond.wait_for(predicate), timeout)
        return time.perf_counter()

    # ---- requêtes ----------------------------------------------------------------------------
    def node_by_name(self, name: str) -> Node | None:
        return next((n for n in self.nodes.values() if n.name == name), None)

    def ports_of(self, node_id: int, direction: str) -> list[Port]:
        found = [
            p for p in self.ports.values() if p.node_id == node_id and p.direction == direction
        ]
        return sorted(found, key=lambda p: p.channel)

    def links_between(self, out_node: int, in_node: int) -> list[Link]:
        return [
            lk for lk in self.links.values() if lk.out_node == out_node and lk.in_node == in_node
        ]

    def links_from(self, out_node: int) -> list[Link]:
        return [lk for lk in self.links.values() if lk.out_node == out_node]


async def _demo() -> None:  # pragma: no cover - exploration manuelle
    graph = Graph()

    def show(t: float, kind: str, obj: object) -> None:
        if kind.startswith("node"):
            print(f"{t:.3f} {kind} {obj.name} {obj.state}", flush=True)  # type: ignore[attr-defined]
        elif kind.startswith("link"):
            lk = obj  # type: ignore[assignment]
            print(f"{t:.3f} {kind} {lk.id} {lk.out_node}->{lk.in_node} {lk.state}", flush=True)  # type: ignore[attr-defined]

    graph.listeners.append(show)
    await graph.start()
    await graph.synced.wait()
    print(
        f"{len(graph.nodes)} nœuds, {len(graph.ports)} ports, {len(graph.links)} liens", flush=True
    )
    await graph.exited.wait()


if __name__ == "__main__":
    asyncio.run(_demo())
