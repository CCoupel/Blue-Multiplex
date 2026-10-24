"""Application aiohttp + cycle de vie du serveur (se branche sur le daemon via `serve_api`)."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from aiohttp import web

from btmux.api.auth import (
    TOKEN_KEY,
    auth_middleware,
    error_middleware,
    load_token,
    no_store_middleware,
)
from btmux.api.routes import HUB, SERVICE, routes
from btmux.api.sse import EventHub
from btmux.bluez.daemon import BluezService
from btmux.log import kv

log = logging.getLogger("btmux.api")
STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY = 16 * 1024


class ApiStartError(Exception):
    """Le serveur HTTP n'a pas pu démarrer (adresse invalide, port occupé) — code de sortie 2."""


def parse_listen(value: str) -> tuple[str, int]:
    host, sep, port = value.rpartition(":")
    if not sep or not port.isdigit() or not 0 <= int(port) <= 65535:
        raise ApiStartError(f"invalid api.listen '{value}' (expected host:port)")
    return host.strip("[]") or "0.0.0.0", int(port)


def create_app(
    service: BluezService,
    token: str | None,
    *,
    hub: EventHub | None = None,
    static: Path | None = None,
) -> web.Application:
    """Construit l'application ; `token=None` verrouille tout `/api/*` (sauf `/api/health`)."""
    app = web.Application(
        middlewares=[no_store_middleware, error_middleware, auth_middleware],
        client_max_size=MAX_BODY,
    )
    app[SERVICE] = service
    app[HUB] = hub or EventHub(service.inventory)
    if token is not None:
        app[TOKEN_KEY] = token
    app.add_routes(routes)
    directory = STATIC_DIR if static is None else static
    if directory.is_dir():
        index = directory / "index.html"

        async def root(request: web.Request) -> web.StreamResponse:
            if not index.is_file():
                raise web.HTTPNotFound()
            return web.FileResponse(index)

        app.router.add_get("/", root)
        app.router.add_static("/static/", directory, follow_symlinks=False)
    return app


class ApiServer:
    """Gestionnaire de contexte asynchrone : démarre le serveur HTTP et le hub SSE."""

    def __init__(self, service: BluezService, *, static: Path | None = None) -> None:
        self.service = service
        self._static = static
        self._runner: web.AppRunner | None = None
        self._hub: EventHub | None = None
        self.port: int | None = None

    async def __aenter__(self) -> ApiServer:
        cfg = self.service.config.api
        host, port = parse_listen(cfg.listen)
        token = load_token(Path(cfg.token_file))
        self._hub = EventHub(self.service.inventory)
        app = create_app(self.service, token, hub=self._hub, static=self._static)
        self._hub.start()
        self._runner = web.AppRunner(app, access_log=None, handler_cancellation=True)
        await self._runner.setup()
        try:
            site = web.TCPSite(self._runner, host, port)
            await site.start()
        except OSError as exc:
            await self._cleanup()
            raise ApiStartError(f"cannot listen on {cfg.listen}: {exc.strerror}") from exc
        sockets = getattr(site._server, "sockets", None) or []
        self.port = sockets[0].getsockname()[1] if sockets else port
        log.info(kv("api_listening", listen=f"{host}:{self.port}", locked=token is None))
        return self

    async def _cleanup(self) -> None:
        if self._hub is not None:
            await self._hub.stop()
        if self._runner is not None:
            await self._runner.cleanup()

    async def __aexit__(self, *exc: object) -> None:
        await self._cleanup()


@contextlib.asynccontextmanager
async def serve_api(service: BluezService) -> AsyncIterator[ApiServer]:
    """Extension de `daemon.serve` : `async with serve_api(service): ...`."""
    async with ApiServer(service) as server:
        yield server
