"""Authentification Bearer (jeton statique de `api.token_file`) et middlewares transverses."""

from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiohttp import web

from btmux.bluez.errors import BluezError
from btmux.log import kv

log = logging.getLogger("btmux.api")

# Routes publiques : Web UI statique et sonde de vivacité.
PUBLIC_EXACT = {"/", "/api/health"}
PUBLIC_PREFIX = ("/static/",)
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
TOKEN_KEY = web.AppKey("token", str)


def load_token(path: Path) -> str | None:
    """Lit le jeton ; `None` (API verrouillée) si absent ou vide. Le contenu n'est jamais journalisé."""
    try:
        token = path.read_text(encoding="utf-8").strip()
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        log.error(kv("token_unreadable", file=path, error=exc.strerror))
        return None
    if not token:
        log.error(kv("token_empty", file=path))
        return None
    if mode & 0o077 and os.name == "posix":
        log.warning(kv("token_file_permissive", file=path, mode=oct(mode)))
    return token


def error_response(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": code, "message": message}, status=status)


def is_public(path: str) -> bool:
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIX)


def check_bearer(header: str | None, token: str | None) -> bool:
    """Comparaison à temps constant ; refus si aucun jeton n'est configuré."""
    if not token or not header:
        return False
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return False
    return hmac.compare_digest(value.strip().encode(), token.encode())


@web.middleware
async def auth_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    if not is_public(request.path) and not check_bearer(
        request.headers.get("Authorization"), request.app.get(TOKEN_KEY)
    ):
        response = error_response(401, "unauthorized", "missing or invalid bearer token")
        response.headers["WWW-Authenticate"] = 'Bearer realm="btmux"'
        return response
    return await handler(request)


@web.middleware
async def error_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    try:
        return await handler(request)
    except BluezError as exc:
        return error_response(exc.status, exc.code, str(exc))
    except web.HTTPException as exc:
        if exc.status < 400:
            raise
        code = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}.get(
            exc.status, "http_error"
        )
        return error_response(exc.status, code, exc.reason or "error")
    except Exception:
        log.exception(kv("api_internal_error", path=request.path))
        return error_response(500, "internal_error", "internal error")


@web.middleware
async def no_store_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    response: web.StreamResponse = await handler(request)
    response.headers["Cache-Control"] = "no-store"
    return response
