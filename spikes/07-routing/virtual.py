#!/usr/bin/env python3
"""Sources et sink virtuels pour valider le routage hors matériel (aucun accès Bluetooth).

- sink : `support.null-audio-sink` (Audio/Sink) créé via `pw-cli create-node` avec `object.linger=true` ;
- sources : deux `pw-play` d'une tonalité, `node.autoconnect=false` (aucun lien tant que le routeur n'en crée pas).

Provisoire — à revalider avec dongle RTL8761B (spike #7).
"""

from __future__ import annotations

import array
import asyncio
import math
import wave
from pathlib import Path

from pw_graph import Graph

SINK_NAME = "virt-sink"
SOURCE_NAMES = ("virt-srcA", "virt-srcB")


def make_tone(path: Path, seconds: int = 180, freq: float = 440.0) -> None:
    """Tonalité stéréo 8 kHz (fichier léger, générée une seule fois)."""
    rate = 8000
    one_second = array.array(
        "h",
        (int(6000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(rate) for _ in (0, 1)),
    )
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for _ in range(seconds):
            wav.writeframes(one_second.tobytes())


async def _run(*cmd: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace")


class Virtual:
    """Cycle de vie des nœuds virtuels (création, destruction, recréation après un restart PipeWire)."""

    def __init__(self, graph: Graph, tone: Path) -> None:
        self.graph = graph
        self.tone = tone
        self.players: dict[str, asyncio.subprocess.Process] = {}

    async def create(self, names: tuple[str, ...] = SOURCE_NAMES, with_sink: bool = True) -> None:
        if with_sink and self.graph.node_by_name(SINK_NAME) is None:
            code, out = await _run(
                "pw-cli",
                "create-node",
                "adapter",
                f"{{ factory.name=support.null-audio-sink node.name={SINK_NAME} "
                "media.class=Audio/Sink object.linger=true audio.position=[FL,FR] "
                "node.autoconnect=false }",
            )
            if code != 0:
                raise RuntimeError(f"création du sink virtuel : {out.strip()}")
        for name in names:
            if name in self.players and self.players[name].returncode is None:
                continue
            self.players[name] = await asyncio.create_subprocess_exec(
                "pw-play",
                "-P",
                f"{{ node.name={name} node.autoconnect=false }}",
                str(self.tone),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        wanted = (SINK_NAME, *names) if with_sink else names
        await self.graph.wait_for(
            lambda: all(self.graph.node_by_name(n) for n in wanted), timeout=10
        )
        await self.graph.wait_for(
            lambda: all(
                self.graph.ports_of(self.graph.node_by_name(n).id, "output") for n in names
            ),  # type: ignore[union-attr]
            timeout=10,
        )

    async def destroy(self) -> None:
        for proc in self.players.values():
            if proc.returncode is None:
                proc.terminate()
        await asyncio.gather(*(p.wait() for p in self.players.values()), return_exceptions=True)
        self.players.clear()
        sink = self.graph.node_by_name(SINK_NAME)
        if sink is not None:
            await _run("pw-cli", "destroy", str(sink.id))
