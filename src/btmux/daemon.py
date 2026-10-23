"""Boucle principale de btmuxd (v0.1.0 : aucune logique, reste vivant jusqu'à SIGTERM/SIGINT)."""

from __future__ import annotations

import asyncio
import signal

from btmux import __version__


async def serve(stop: asyncio.Event) -> int:
    """Journalise le démarrage puis attend `stop`. Aucun accès BlueZ/PipeWire/réseau."""
    print(f"btmuxd {__version__} started — no daemon logic yet (v0.3.0)", flush=True)
    await stop.wait()
    print(f"btmuxd {__version__} stopped", flush=True)
    return 0


async def _run() -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    return await serve(stop)


def run() -> int:
    """Point d'entrée synchrone : code 0 sur arrêt propre (SIGTERM/SIGINT)."""
    return asyncio.run(_run())
