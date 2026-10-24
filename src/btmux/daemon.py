"""Boucle principale de btmuxd : couche BlueZ (agent, appairage, inventaire) ; le serveur HTTP s'y branche (#21)."""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from btmux import __version__
from btmux.bluez.daemon import EXIT_ADAPTER_NOT_FOUND, BluezService
from btmux.bluez.errors import AdaptersNotFound
from btmux.config import Config
from btmux.log import configure

# Point d'accroche de l'API (#21) : reçoit le service BlueZ, retourne un gestionnaire de contexte asynchrone
# qui démarre/arrête le serveur HTTP autour de la boucle principale.
Extension = Callable[[BluezService], AbstractAsyncContextManager[None]]


async def serve(
    stop: asyncio.Event,
    config: Config,
    *,
    service: BluezService | None = None,
    extension: Extension | None = None,
) -> int:
    """Démarre la couche BlueZ puis attend `stop`. Codes : 0 arrêt propre, 3 adaptateur introuvable."""
    svc = service or BluezService(config)
    announce = asyncio.create_task(_announce(svc))
    try:
        if extension is None:
            code = await svc.run(stop)
        else:
            async with extension(svc):
                code = await svc.run(stop)
    except AdaptersNotFound as exc:
        print(f"btmuxd: {exc}", file=sys.stderr, flush=True)
        return EXIT_ADAPTER_NOT_FOUND
    finally:
        announce.cancel()
    print(f"btmuxd {__version__} stopped", flush=True)
    return code


async def _announce(svc: BluezService) -> None:
    await svc.ready.wait()
    print(f"btmuxd {__version__} started", flush=True)


async def _run(config: Config) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    return await serve(stop, config)


def run(config: Config) -> int:
    """Point d'entrée synchrone : 0 sur arrêt propre (SIGTERM/SIGINT), 3 si l'adaptateur reste introuvable."""
    configure()
    return asyncio.run(_run(config))
