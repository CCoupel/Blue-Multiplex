"""Routes `/api/*` (contracts/http-endpoints.md)."""

from __future__ import annotations

import json
import re
from typing import Any

from aiohttp import web

from btmux import __version__
from btmux.api.auth import error_response
from btmux.api.sse import EventHub
from btmux.bluez.daemon import BluezService
from btmux.bluez.errors import (
    BluezUnavailable,
    ControllerError,
    InvalidMac,
    InvalidRequest,
    UnknownDevice,
)
from btmux.config.loader import ALIAS_RE

SERVICE = web.AppKey("service", BluezService)
HUB = web.AppKey("hub", EventHub)
MAC_RE = re.compile(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")

routes = web.RouteTableDef()


def _service(request: web.Request, *, write: bool = False) -> BluezService:
    service = request.app[SERVICE]
    if not service.ready.is_set():
        raise BluezUnavailable("BlueZ unavailable (daemon starting or BlueZ stopped)")
    if write:
        service.roles.check_writable()  # 409 change_pending entre l'écriture des rôles et l'arrêt
    return service


def _mac(request: web.Request) -> str:
    mac = request.match_info["mac"]
    if not MAC_RE.fullmatch(mac):
        raise InvalidMac(f"invalid MAC address '{mac}'")
    return mac.upper()


async def _json_body(request: web.Request) -> dict[str, Any]:
    raw = await request.read()
    if not raw:
        return {}
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise InvalidRequest("body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise InvalidRequest("body must be a JSON object")
    return body


def _device_json(service: BluezService, mac: str) -> dict[str, Any]:
    for device in service.inventory.devices():
        if device.mac == mac:
            return device.to_dict()
    raise UnknownDevice(f"device {mac} unknown")


@routes.get("/api/health")
async def health(request: web.Request) -> web.Response:
    service = request.app[SERVICE]
    found = sum(1 for info in service.registry.infos if info.path)
    return web.json_response({"version": __version__, "adapters": found})


@routes.get("/api/state")
async def state(request: web.Request) -> web.Response:
    return web.json_response(_service(request).inventory.state())


@routes.get("/api/discovered")
async def discovered(request: web.Request) -> web.Response:
    service = _service(request)
    return web.json_response([d.to_dict() for d in service.inventory.discovered()])


@routes.post("/api/pairing")
async def open_pairing(request: web.Request) -> web.Response:
    service = _service(request, write=True)
    body = await _json_body(request)
    adapter = body.get("adapter")
    if adapter not in ("sources", "headsets"):
        raise InvalidRequest("adapter must be 'sources' or 'headsets'")
    window = await service.pairing.open(adapter, body.get("duration"))
    return web.json_response(window.to_dict(), status=202)


@routes.delete("/api/pairing")
async def close_pairing(request: web.Request) -> web.Response:
    await _service(request, write=True).pairing.close()
    return web.Response(status=204)


@routes.post("/api/devices/{mac}/pair")
async def pair(request: web.Request) -> web.Response:
    service, mac = _service(request, write=True), _mac(request)
    await service.pairing.pair(mac)
    return web.json_response(_device_json(service, mac), status=202)


@routes.post("/api/devices/{mac}/connect")
async def connect(request: web.Request) -> web.Response:
    service, mac = _service(request, write=True), _mac(request)
    await service.pairing.connect(mac)
    return web.json_response(_device_json(service, mac), status=202)


@routes.post("/api/devices/{mac}/disconnect")
async def disconnect(request: web.Request) -> web.Response:
    service, mac = _service(request, write=True), _mac(request)
    await service.pairing.disconnect(mac)
    return web.json_response(_device_json(service, mac), status=202)


@routes.post("/api/devices/{mac}/forget")
async def forget(request: web.Request) -> web.Response:
    service, mac = _service(request, write=True), _mac(request)
    await service.pairing.forget(mac)
    return web.Response(status=204)


@routes.patch("/api/devices/{mac}")
async def patch_device(request: web.Request) -> web.Response:
    service, mac = _service(request, write=True), _mac(request)
    body = await _json_body(request)
    unknown = set(body) - {"trusted", "alias"}
    if unknown or not body:
        raise InvalidRequest("body must contain 'trusted' (bool) and/or 'alias' (string)")
    if "trusted" in body and not isinstance(body["trusted"], bool):
        raise InvalidRequest("'trusted' must be a boolean")
    alias = body.get("alias")
    if "alias" in body and not (isinstance(alias, str) and ALIAS_RE.fullmatch(alias)):
        raise InvalidRequest("'alias' must match [a-z0-9][a-z0-9-]{0,31}")
    _device_json(service, mac)  # 404 si inconnu, avant toute modification
    if "trusted" in body:
        await service.pairing.set_trusted(mac, body["trusted"])
    if "alias" in body:
        service.inventory.set_alias(mac, alias)
    return web.json_response(_device_json(service, mac))


@routes.get("/api/controllers")
async def controllers(request: web.Request) -> web.Response:
    inventory = _service(request).inventory
    return web.json_response(
        {
            "controllers": [c.to_dict() for c in inventory.controllers()],
            "roles": inventory.roles().to_dict(),
        }
    )


@routes.put("/api/controllers/roles")
async def put_roles(request: web.Request) -> web.Response:
    service = _service(request, write=True)
    try:
        body: Any = json.loads(await request.read() or b"null")
    except ValueError as exc:
        raise ControllerError("invalid_body", "body is not valid JSON") from exc
    status, roles = await service.roles.set_roles(body)
    return web.json_response(roles.to_dict(), status=status)


@routes.get("/api/events")
async def events(request: web.Request) -> web.StreamResponse:
    _service(request)
    return await request.app[HUB].stream(request)


async def not_found_api(request: web.Request) -> web.Response:
    return error_response(404, "not_found", "no such route")
