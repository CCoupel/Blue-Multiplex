"""API HTTP de btmuxd (aiohttp) : routes `/api/*`, flux SSE, Web UI statique (#21)."""

from btmux.api.server import ApiServer, create_app, serve_api

__all__ = ["ApiServer", "create_app", "serve_api"]
