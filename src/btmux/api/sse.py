"""Flux SSE `/api/events` : tampon des 100 derniers évènements, `Last-Event-ID`, keep-alive 15 s."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

from aiohttp import web

from btmux.api.auth import SECURITY_HEADERS
from btmux.bluez.inventory import Event, Inventory

BUFFER_SIZE = 100
KEEPALIVE_S = 15.0
WRITE_TIMEOUT_S = 10.0
RETRY_MS = 3000


def format_event(event_id: int, kind: str, data: Any) -> bytes:
    return f"event: {kind}\nid: {event_id}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


class EventHub:
    """Consomme la file de l'inventaire, garde les 100 derniers évènements, réveille les clients."""

    def __init__(self, inventory: Inventory, keepalive: float = KEEPALIVE_S) -> None:
        self._inventory = inventory
        self.keepalive = keepalive
        self._buffer: deque[Event] = deque(maxlen=BUFFER_SIZE)
        self._changed = asyncio.Condition()
        self._base = inventory.last_event_id
        self._closing = False
        self._sub = inventory.subscribe()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        self._closing = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._sub.close()

    async def _pump(self) -> None:
        while True:
            event = await self._sub.get()
            async with self._changed:
                self._buffer.append(event)
                self._changed.notify_all()

    @property
    def latest_id(self) -> int:
        return self._buffer[-1].id if self._buffer else self._base

    def missed_since(self, last_id: int) -> list[Event] | None:
        """Évènements d'id > last_id ; `None` si le tampon ne couvre plus l'intervalle (→ évènement `state`)."""
        if not self._buffer:
            return [] if last_id == self._base else None
        oldest = self._buffer[0].id
        if last_id > self._buffer[-1].id or last_id < oldest - 1:
            return None
        return [e for e in self._buffer if e.id > last_id]

    async def wait_for_more(self, last_id: int) -> bool:
        """Attend un évènement plus récent que `last_id` (False après `keepalive` s sans rien)."""
        async with self._changed:
            try:
                await asyncio.wait_for(
                    self._changed.wait_for(lambda: self._closing or self.latest_id > last_id),
                    self.keepalive,
                )
            except TimeoutError:
                return False
        return True

    def close_streams(self) -> None:
        """Termine tous les flux SSE (arrêt du serveur) : réveille les clients en attente."""
        self._closing = True
        asyncio.ensure_future(self._wake())

    async def _wake(self) -> None:
        async with self._changed:
            self._changed.notify_all()

    async def _send(self, response: web.StreamResponse, payload: bytes) -> None:
        await asyncio.wait_for(response.write(payload), WRITE_TIMEOUT_S)

    async def stream(self, request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            headers={
                **SECURITY_HEADERS,
                "Content-Type": "text/event-stream; charset=utf-8",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)
        await self._send(response, f"retry: {RETRY_MS}\n\n".encode())
        raw = request.headers.get("Last-Event-ID")
        valid = raw is not None and raw.isascii() and raw.isdigit() and len(raw) <= 15
        last = self.latest_id
        # Sans (ou avec un) Last-Event-ID inutilisable : `state` complet ; valide et couvert : rejeu.
        if raw is None or not valid or self.missed_since(int(raw)) is None:
            await self._send(response, format_event(last, "state", self._inventory.state()))
        else:
            last = int(raw)
        try:
            while not self._closing:
                if not await self.wait_for_more(last):
                    if not self._closing:
                        await self._send(response, b": ping\n\n")
                    continue
                if self._closing:
                    break
                for event in self.missed_since(last) or []:
                    await self._send(response, format_event(event.id, event.kind, event.data))
                    last = event.id
                if self.missed_since(last) is None:  # tampon dépassé pendant l'envoi
                    last = self.latest_id
                    await self._send(response, format_event(last, "state", self._inventory.state()))
        except (ConnectionResetError, TimeoutError):
            pass
        return response
