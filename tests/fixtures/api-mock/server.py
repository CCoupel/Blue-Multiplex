#!/usr/bin/env python3
"""Mock de l'API HTTP btmuxd v0.2.0 (appairages) — bibliotheque standard uniquement.

Rejoue contracts/http-endpoints.md et contracts/models.md (Web UI #16 sans BlueZ).
Usage :
    python tests/fixtures/api-mock/server.py --port 8099 --scenario default [--token mock-token]
                                             [--static-dir src/btmux/api/static] [--time-scale 1.0]
Usage Python (tests) : `MockApi(scenario="default", token="t").start()` -> `.url`, `.stop()`.

Hors contrat (pilotage, prefixe /__mock__/ sans jeton) : voir README.md.
"""

from __future__ import annotations

import argparse
import copy
import hmac
import json
import mimetypes
import queue
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
SCENARIOS = HERE / "scenarios"
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
ROLES = ("sources", "headsets")
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Clock:
    """Horloge virtuelle acceleree (time_scale > 1 : les delais passent plus vite)."""

    def __init__(self, scale: float = 1.0) -> None:
        self.scale = scale
        self._wall0 = datetime.now(UTC)
        self._mono0 = time.monotonic()

    def now(self) -> datetime:
        return self._wall0 + timedelta(seconds=(time.monotonic() - self._mono0) * self.scale)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


class MockState:
    """Etat en memoire + planificateur d'actions differees + diffusion SSE."""

    def __init__(self, scenario: str | dict, clock: Clock) -> None:
        self.clock = clock
        self.lock = threading.RLock()
        self.subscribers: list[queue.Queue] = []
        self.event_id = 0
        self.buffer: list[tuple[int, str, str]] = []  # (id, event, message) — tampon de 100
        self.tasks: list[tuple[datetime, str, dict]] = []
        self.load(scenario)

    # --- scenario -------------------------------------------------------------------------
    def load(self, scenario: str | dict) -> None:
        if isinstance(scenario, str):
            path = Path(scenario) if scenario.endswith(".json") else SCENARIOS / f"{scenario}.json"
            scenario = json.loads(path.read_text(encoding="utf-8"))
        sc = copy.deepcopy(scenario)
        with self.lock:
            self.sc = sc
            self.version = sc.get("version", "0.2.0.0")
            self.adapters = sc["adapters"]
            self.devices = {d["mac"].upper(): self._full_device(d) for d in sc.get("devices", [])}
            self.discovered: dict[str, dict] = {}
            self.pending_discovered = copy.deepcopy(sc.get("discoverable_headsets", []))
            self.pairing: dict | None = None
            self.last_closed: dict = {"adapter": None, "closed_at": None, "reason": None}
            self.tasks = []
            self.unavailable = bool(sc.get("bluez_unavailable", False))
            self.stale_bond = {m.upper() for m in sc.get("stale_bond_macs", [])}
            self.bluez_error = {m.upper() for m in sc.get("bluez_error_macs", [])}
            self.pair_delay = float(sc.get("pair_delay_s", 1.0))
            self.connect_delay = float(sc.get("connect_delay_s", 0.5))
            w = sc.get("pairing")
            if w:
                self._open_window(w["adapter"], float(w.get("remaining_s", 60)), emit=False)
            self.buffer = []
            self.event_id = 0
            # --- #23 : controleurs et affectation des roles
            self.controllers = [dict(c, mac=c["mac"].upper()) for c in sc.get("controllers", [])]
            self.roles = {
                "sources": None,
                "headsets": None,
                "source": "config",
                "pending": False,
                "restart_expected": False,
            }
            self.roles.update(sc.get("roles", {}))
            self.restart_delay = float(sc.get("restart_delay_s", 3.0))
            self.restart_outage = float(sc.get("restart_outage_s", 12.0))
            self.outage = False

    @staticmethod
    def _full_device(d: dict) -> dict:
        base = {
            "mac": d["mac"].upper(),
            "adapter": "sources",
            "alias": None,
            "name": d["mac"],
            "kind": "unknown",
            "paired": True,
            "trusted": True,
            "connected": False,
            "blocked": False,
            "uuids": [],
            "profiles": [],
            "last_seen": None,
            "in_config": False,
        }
        base.update(d)
        base["mac"] = d["mac"].upper()
        return base

    # --- SSE ------------------------------------------------------------------------------
    def emit(self, event: str, data) -> None:
        with self.lock:
            self.event_id += 1
            msg = f"event: {event}\nid: {self.event_id}\ndata: {json.dumps(data)}\n\n"
            self.buffer.append((self.event_id, event, msg))
            del self.buffer[:-100]
            for q in list(self.subscribers):
                q.put(msg)

    def _state_event(self) -> str:
        return f"event: state\nid: {self.event_id}\ndata: {json.dumps(self.state())}\n\n"

    def subscribe(self, last_event_id: str = "") -> queue.Queue:
        """Abonne un client ; `Last-Event-ID` couvert -> rejoue, sinon (et sans id) -> `state`."""
        q: queue.Queue = queue.Queue()
        with self.lock:
            covered = False
            if last_event_id.isdigit():
                last = int(last_event_id)
                ids = [i for i, _, _ in self.buffer]
                covered = (last == 0) if not ids else (min(ids) - 1 <= last <= max(ids))
                if covered:
                    for i, _, msg in self.buffer:
                        if i > last:
                            q.put(msg)
            if not covered:  # premier evenement de la connexion (contrat 3db8c3c)
                q.put(self._state_event())
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    # --- planificateur --------------------------------------------------------------------
    def schedule(self, delay_s: float, action: str, **kw) -> None:
        with self.lock:
            self.tasks.append((self.clock.now() + timedelta(seconds=delay_s), action, kw))

    def tick(self) -> None:
        with self.lock:
            now = self.clock.now()
            if self.pairing and now >= self._expires(self.pairing):
                self._close_window("expired")
            due = [t for t in self.tasks if t[0] <= now]
            self.tasks = [t for t in self.tasks if t[0] > now]
            for _, action, kw in due:
                getattr(self, f"_do_{action}")(**kw)

    def _do_reveal(self, mac: str) -> None:
        if not self.pairing or self.pairing["adapter"] != "headsets":
            return
        for d in self.pending_discovered:
            if d["mac"].upper() == mac and mac not in self.discovered:
                item = {
                    "mac": mac,
                    "adapter": "headsets",
                    "name": d["name"],
                    "rssi": d.get("rssi", -60),
                    "class": d.get("class", "0x240404"),
                }
                self.discovered[mac] = item
                self.emit("discovered", item)

    def _do_paired(self, mac: str) -> None:
        item = self.discovered.pop(mac, None)
        if not item:
            return
        dev = self._full_device(
            {
                "mac": mac,
                "adapter": "headsets",
                "name": item["name"],
                "kind": "headset",
                "connected": True,
                "uuids": ["0000110a-0000-1000-8000-00805f9b34fb"],
                "profiles": ["a2dp_source", "hfp_ag"],
                "last_seen": _iso(self.clock.now()),
            }
        )
        self.devices[mac] = dev
        self.emit("device", dev)

    def _do_connected(self, mac: str, connected: bool) -> None:
        dev = self.devices.get(mac)
        if dev:
            dev["connected"] = connected
            dev["last_seen"] = _iso(self.clock.now())
            self.emit("device", dev)

    # --- fenetre d'appairage --------------------------------------------------------------
    def _expires(self, w: dict) -> datetime:
        return datetime.strptime(w["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    def window_model(self) -> dict | None:
        w = self.pairing
        if not w:
            return None
        remaining = max(0, int((self._expires(w) - self.clock.now()).total_seconds() + 0.999))
        return {"open": True, **w, "remaining_s": remaining}

    def pairing_view(self) -> dict:
        """PairingWindow ouverte, ou objet explicite `open:false` (jamais null)."""
        return self.window_model() or {"open": False, **self.last_closed}

    def _open_window(self, adapter: str, duration: float, emit: bool = True) -> dict:
        now = self.clock.now()
        self.pairing = {
            "adapter": adapter,
            "opened_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=duration)),
        }
        for a in self.adapters:
            if a["role"] == adapter:
                a["discoverable"] = a["pairable"] = True
        if adapter == "headsets":
            for d in self.pending_discovered:
                self.schedule(float(d.get("reveal_after_s", 1.0)), "reveal", mac=d["mac"].upper())
        model = self.window_model()
        if emit:
            for a in self.adapters:
                if a["role"] == adapter:
                    self.emit("adapter", a)
            self.emit("pairing", model)
        return model

    def _close_window(self, reason: str = "closed") -> None:
        w, self.pairing = self.pairing, None
        if not w:
            return
        self.last_closed = {
            "adapter": w["adapter"],
            "closed_at": _iso(self.clock.now()),
            "reason": reason,
        }
        for a in self.adapters:
            if a["role"] == w["adapter"]:
                a["discoverable"] = a["pairable"] = False
                self.emit("adapter", a)
        self.discovered.clear()
        self.emit("pairing", self.pairing_view())

    # --- vues -----------------------------------------------------------------------------
    def state(self) -> dict:
        return {
            "version": self.version,
            "adapters": self.adapters,
            "devices": list(self.devices.values()),
            "pairing": self.pairing_view(),
            "controllers": self.controllers,
            "roles": self.roles,
        }

    def check_bluez(self) -> None:
        if self.unavailable:
            raise ApiError(503, "bluez_unavailable", "BlueZ indisponible (org.bluez absent du bus)")

    def check_writable(self) -> None:
        """Ecritures refusees (409) entre l'acceptation d'un changement de roles et l'arret."""
        if self.roles["pending"]:
            raise ApiError(
                409, "change_pending", "changement de roles en cours : le service va redemarrer"
            )

    def check_role(self, role: str) -> None:
        """409 role_unassigned quand le role vise n'a pas de controleur affecte/present."""
        mac = self.roles.get(role)
        ctrl = next((c for c in self.controllers if c["mac"] == mac), None)
        if not mac or not ctrl or not ctrl.get("present", True):
            raise ApiError(409, "role_unassigned", f"aucun controleur affecte au role '{role}'")

    def check_mac(self, mac: str) -> str:
        if not MAC_RE.match(mac):
            raise ApiError(400, "invalid_mac", f"adresse MAC invalide : {mac!r}")
        return mac.upper()

    # --- actions de l'API -----------------------------------------------------------------
    def open_pairing(self, body: dict) -> dict:
        self.check_bluez()
        self.check_writable()
        adapter, duration = body.get("adapter"), body.get("duration", 60)
        if adapter not in ROLES:
            raise ApiError(400, "invalid_adapter", "adapter doit etre 'sources' ou 'headsets'")
        if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 300:
            raise ApiError(400, "invalid_duration", "duration doit etre un entier entre 1 et 300")
        self.check_role(adapter)
        if self.pairing:
            raise ApiError(409, "pairing_open", "une fenetre d'appairage est deja ouverte")
        return self._open_window(adapter, duration)

    def close_pairing(self) -> None:
        self.check_bluez()
        self.check_writable()
        self._close_window()

    def pair(self, mac: str) -> None:
        self.check_bluez()
        self.check_writable()
        mac = self.check_mac(mac)
        self.check_role("headsets")
        if mac in self.bluez_error:
            raise ApiError(502, "bluez_error", "org.bluez.Error.Failed: Page Timeout")
        if mac in self.stale_bond:
            raise ApiError(
                409, "stale_bond", "bond perime : oubliez l'appareil (forget) puis reessayez"
            )
        if not self.pairing or self.pairing["adapter"] != "headsets":
            raise ApiError(409, "pairing_closed", "ouvrez d'abord une fenetre 'headsets'")
        if mac not in self.discovered:
            raise ApiError(404, "not_discovered", f"{mac} n'a pas ete decouvert")
        if any(t[1] == "paired" and t[2].get("mac") == mac for t in self.tasks):
            raise ApiError(409, "operation_in_progress", f"appairage de {mac} deja en cours")
        self.schedule(self.pair_delay, "paired", mac=mac)

    def _known(self, mac: str, write: bool = True) -> dict:
        self.check_bluez()
        if write:
            self.check_writable()
        mac = self.check_mac(mac)
        if mac in self.bluez_error:
            raise ApiError(502, "bluez_error", "org.bluez.Error.Failed: Connection refused")
        dev = self.devices.get(mac)
        if not dev:
            raise ApiError(404, "unknown_device", f"appareil inconnu : {mac}")
        return dev

    def connect(self, mac: str, connected: bool) -> None:
        dev = self._known(mac)
        if connected:
            self.check_role(dev["adapter"])
        self.schedule(self.connect_delay, "connected", mac=dev["mac"], connected=connected)

    def forget(self, mac: str) -> None:
        dev = self._known(mac)
        mac = dev["mac"]
        self.stale_bond.discard(mac)
        self.emit("device.removed", {"mac": mac, "adapter": dev["adapter"]})
        if dev["in_config"]:  # placeholder : connu de la config, non appaire
            dev.update(
                paired=False,
                trusted=False,
                connected=False,
                name=None,
                uuids=[],
                profiles=[],
                last_seen=None,
            )
            self.emit("device", dev)
        else:
            del self.devices[mac]

    def patch(self, mac: str, body: dict) -> dict:
        dev = self._known(mac)
        if not isinstance(body, dict) or not body or set(body) - {"trusted", "alias"}:
            raise ApiError(400, "invalid_body", "champs acceptes : trusted (bool), alias (str)")
        if "trusted" in body and not isinstance(body["trusted"], bool):
            raise ApiError(400, "invalid_trusted", "trusted doit etre un booleen")
        if "alias" in body and not (
            isinstance(body["alias"], str) and ALIAS_RE.match(body["alias"])
        ):
            raise ApiError(400, "invalid_alias", "alias doit respecter ^[a-z0-9][a-z0-9-]{0,31}$")
        dev.update(body)
        self.emit("device", dev)
        return dev

    # --- #23 : controleurs ------------------------------------------------------------------
    def controllers_view(self) -> dict:
        self.check_bluez()
        return {"controllers": self.controllers, "roles": self.roles}

    def set_roles(self, body) -> tuple[int, dict]:
        self.check_bluez()
        self.check_writable()
        if not isinstance(body, dict) or set(body) - {"sources", "headsets", "confirm"}:
            raise ApiError(400, "invalid_body", "champs : sources, headsets (MAC ou null), confirm")
        if not {"sources", "headsets"} <= set(body):
            raise ApiError(
                400, "invalid_body", "sources et headsets sont obligatoires (MAC ou null)"
            )
        if not isinstance(body.get("confirm", False), bool):
            raise ApiError(400, "invalid_confirm", "confirm doit etre un booleen")
        new = {}
        for role in ROLES:
            v = body[role]
            if v is None:
                new[role] = None
                continue
            if not isinstance(v, str):
                raise ApiError(400, "invalid_mac", f"{role}: MAC attendue ou null")
            mac = self.check_mac(v)
            ctrl = next((c for c in self.controllers if c["mac"] == mac), None)
            if not ctrl or not ctrl.get("present", True):
                raise ApiError(400, "unknown_controller", f"controleur inconnu ou absent : {mac}")
            new[role] = mac
        if new["sources"] is not None and new["sources"] == new["headsets"]:
            raise ApiError(400, "same_controller", "un controleur ne peut porter qu'un seul role")
        if self.pairing:
            raise ApiError(409, "pairing_open", "fermez la fenetre d'appairage avant de changer")
        affected = [r for r in ROLES if new[r] != self.roles[r]]
        if not affected:
            return 200, self.roles
        connected = [
            {"mac": d["mac"], "alias": d["alias"], "name": d["name"], "adapter": d["adapter"]}
            for d in self.devices.values()
            if d["connected"] and d["adapter"] in affected
        ]
        if connected and not body.get("confirm", False):
            raise ApiError(
                409,
                "devices_connected",
                "des appareils sont connectes : confirm:true pour les deconnecter",
                details=connected,
            )
        for item in connected:  # confirm:true -> le daemon deconnecte d'abord
            dev = self.devices[item["mac"]]
            dev["connected"] = False
            self.emit("device", dev)
        for c in self.controllers:  # roles, controleurs sans role fermes
            c["role"] = next((r for r in ROLES if new[r] == c["mac"]), None)
            if c["role"] is None:
                c["pairable"] = c["discoverable"] = False
        self.roles.update(new, source="state", pending=True, restart_expected=True)
        self.emit("controllers", self.controllers)
        self.emit("roles", self.roles)
        self.schedule(self.restart_delay, "begin_outage")
        self.schedule(self.restart_delay + self.restart_outage, "end_outage")
        return 202, self.roles

    def _do_begin_outage(self) -> None:
        """Arret du service : l'API ne repond plus, les flux SSE sont coupes."""
        self.outage = True
        for q in list(self.subscribers):
            q.put(None)

    def _do_end_outage(self) -> None:
        """Redemarrage termine : ids remis a zero, premier evenement = `state` complet."""
        self.outage = False
        self.buffer, self.event_id = [], 0
        self.roles.update(pending=False, restart_expected=False)
        old = {a["role"]: a for a in self.adapters}
        adapters = []
        for role in ROLES:
            ctrl = next((c for c in self.controllers if c["mac"] == self.roles[role]), None)
            if not ctrl or not ctrl.get("present", True):
                continue
            base = old.get(role, {"class": "0x6c0404", "powered": True})
            adapters.append(
                {
                    "role": role,
                    "mac": ctrl["mac"],
                    "alias": ctrl["name"],
                    "hci": ctrl["hci"],
                    "powered": True,
                    "discoverable": False,
                    "pairable": False,
                    "class": base.get("class", "0x6c0404"),
                }
            )
        self.adapters = adapters

    def hotplug(self, body: dict) -> dict:
        """Pilotage mock : add / remove / update d'un controleur + evenement `controllers`."""
        action = body.get("action")
        if action == "add":
            ctrl = {
                "role": None,
                "powered": True,
                "pairable": False,
                "discoverable": False,
                "connected_devices": 0,
                "present": True,
                "usb_id": None,
                "bus": "usb",
                **body["controller"],
            }
            ctrl["mac"] = ctrl["mac"].upper()
            self.controllers.append(ctrl)
        elif action == "remove":
            mac = body["mac"].upper()
            self.controllers = [c for c in self.controllers if c["mac"] != mac]
        elif action == "update":
            mac = body["mac"].upper()
            for c in self.controllers:
                if c["mac"] == mac:
                    c.update(body.get("props", {}))
        else:
            raise ApiError(400, "invalid_action", "action : add|remove|update")
        self.emit("controllers", self.controllers)
        return {"controllers": self.controllers}

    # --- pilotage hors contrat ------------------------------------------------------------
    def incoming(self, body: dict) -> tuple[int, dict]:
        """Simule un appairage entrant (PC/telephone) : accepte pendant une fenetre sources."""
        mac = self.check_mac(body.get("mac", ""))
        if not (self.pairing and self.pairing["adapter"] == "sources"):
            return 409, {
                "error": "pairing_refused",
                "message": "hors fenetre : appairage entrant refuse",
            }
        dev = self._full_device(
            {
                "mac": mac,
                "adapter": "sources",
                "name": body.get("name", mac),
                "kind": "source",
                "connected": True,
                "uuids": ["0000110a-0000-1000-8000-00805f9b34fb"],
                "profiles": ["a2dp_source", "hfp_ag"],
                "last_seen": _iso(self.clock.now()),
            }
        )
        self.devices[mac] = dev
        self.emit("device", dev)
        return 200, dev


def make_handler(state: MockState, token: str, static_dir: Path | None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "btmux-api-mock/0.2"

        def log_message(self, *a) -> None:  # silencieux
            pass

        # --- helpers ---
        def _send(self, status: int, body=None, ctype="application/json", extra=None) -> None:
            raw = (
                b""
                if body is None
                else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
            )
            self.send_response(status)
            if status != 204:
                self.send_header(
                    "Content-Type", f"{ctype}; charset=utf-8" if "json" in ctype else ctype
                )
            self.send_header("Content-Length", str(len(raw)))
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if raw and self.command != "HEAD":
                self.wfile.write(raw)

        def _error(self, e: ApiError) -> None:
            body = {"error": e.code, "message": e.message}
            if e.details is not None:
                body["details"] = e.details
            self._send(e.status, body)

        def _authorized(self, query: dict) -> bool:
            got = self.headers.get("Authorization", "")
            if got.startswith("Bearer "):
                return hmac.compare_digest(got[7:].encode(), token.encode())
            return False

        def _json_body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                raise ApiError(400, "invalid_json", "corps JSON invalide") from None

        # --- dispatch ---
        def _dispatch(self) -> None:
            url = urlparse(self.path)
            path, query = url.path, parse_qs(url.query)
            try:
                if path.startswith("/__mock__/"):
                    return self._control(path, query)
                if path.startswith("/api/"):
                    if state.outage:  # service arrete : connexion coupee, aucune reponse
                        self.close_connection = True
                        self.connection.close()
                        return None
                    if path != "/api/health" and not self._authorized(query):
                        raise ApiError(401, "unauthorized", "jeton Bearer requis")
                    if path == "/api/events" and self.command == "GET":
                        return self._sse()  # hors verrou : flux bloquant
                    with state.lock:
                        return self._api(path)
                return self._static(path)
            except ApiError as e:
                self._error(e)

        do_GET = do_POST = do_DELETE = do_PATCH = do_PUT = _dispatch

        def _api(self, path: str) -> None:
            m, c = self.command, state
            if path == "/api/health" and m == "GET":
                return self._send(200, {"version": c.version, "adapters": len(c.adapters)})
            if path == "/api/state" and m == "GET":
                c.check_bluez()
                return self._send(200, c.state())
            if path == "/api/pairing" and m == "POST":
                return self._send(202, c.open_pairing(self._json_body()))
            if path == "/api/pairing" and m == "DELETE":
                c.close_pairing()
                return self._send(204)
            if path == "/api/controllers" and m == "GET":
                return self._send(200, c.controllers_view())
            if path == "/api/controllers/roles" and m == "PUT":
                status, body = c.set_roles(self._json_body())
                return self._send(status, body)
            if path == "/api/discovered" and m == "GET":
                c.check_bluez()
                return self._send(200, list(c.discovered.values()))
            mm = re.fullmatch(r"/api/devices/([^/]+)(?:/(pair|connect|disconnect|forget))?", path)
            if mm:
                mac, action = mm.group(1), mm.group(2)
                if action == "pair" and m == "POST":
                    c.pair(mac)
                    return self._send(202, {})
                if action == "connect" and m == "POST":
                    c.connect(mac, True)
                    return self._send(202, {})
                if action == "disconnect" and m == "POST":
                    c.connect(mac, False)
                    return self._send(202, {})
                if action == "forget" and m == "POST":
                    c.forget(mac)
                    return self._send(204)
                if action is None and m == "PATCH":
                    return self._send(200, c.patch(mac, self._json_body()))
            raise ApiError(404, "not_found", f"route inconnue : {m} {path}")

        def _sse(self) -> None:
            q = state.subscribe(self.headers.get("Last-Event-ID", ""))
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.wfile.write(b"retry: 3000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=15)
                    except queue.Empty:
                        msg = ": ping\n\n"
                    if msg is None:
                        break
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                state.unsubscribe(q)
                self.close_connection = True

        def _static(self, path: str) -> None:
            """Comme l'app reelle : `/` = index.html ; ressources UNIQUEMENT sous /static/*."""
            if not static_dir or self.command != "GET":
                raise ApiError(404, "not_found", "pas de Web UI servie par ce mock (--static-dir)")
            if path in ("/", ""):
                rel = "index.html"
            elif path.startswith("/static/"):
                rel = path.removeprefix("/static/")
            else:
                raise ApiError(404, "not_found", f"ressource hors /static/ : {path}")
            if Path(rel).suffix.lower() not in {".html", ".js", ".css"}:
                raise ApiError(404, "not_found", "seuls html/js/css sont servis")
            target = (static_dir / rel).resolve()
            if static_dir.resolve() not in target.parents:
                raise ApiError(404, "not_found", "chemin hors du dossier statique")
            if not target.is_file():
                raise ApiError(404, "not_found", f"fichier statique absent : {rel}")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), ctype=ctype)

        def _control(self, path: str, query: dict) -> None:
            c = state
            with c.lock:
                if path == "/__mock__/state":
                    return self._send(200, {**c.state(), "discovered": list(c.discovered.values())})
                if path == "/__mock__/reset":
                    c.load(query.get("scenario", ["default"])[0])
                    return self._send(200, {"ok": True})
                body = self._json_body() if self.command == "POST" else {}
                if path == "/__mock__/incoming":
                    status, out = c.incoming(body)
                    return self._send(status, out)
                if path == "/__mock__/controllers":
                    return self._send(200, c.hotplug(body))
                if path == "/__mock__/discovered-gone":
                    mac = c.check_mac(body.get("mac", ""))
                    if mac not in c.discovered:
                        return self._send(404, {"error": "not_discovered", "message": mac})
                    item = c.discovered.pop(mac)
                    c.emit("device.removed", {"mac": mac, "adapter": item["adapter"]})
                    return self._send(200, {"ok": True})
                if path == "/__mock__/event":
                    c.emit(body["event"], body.get("data"))
                    return self._send(200, {"ok": True})
                if path == "/__mock__/fail":
                    if "bluez_unavailable" in body:
                        c.unavailable = bool(body["bluez_unavailable"])
                    if "stale_bond_macs" in body:
                        c.stale_bond = {m.upper() for m in body["stale_bond_macs"]}
                    if "bluez_error_macs" in body:
                        c.bluez_error = {m.upper() for m in body["bluez_error_macs"]}
                    return self._send(200, {"ok": True})
                if path == "/__mock__/close-streams":
                    for s in list(c.subscribers):
                        s.put(None)
                    return self._send(200, {"ok": True})
            raise ApiError(404, "not_found", f"pilotage inconnu : {path}")

    return Handler


class MockApi:
    """Serveur du mock, demarrable dans un thread (tests) ou en processus (CLI)."""

    def __init__(
        self,
        scenario: str | dict = "default",
        token: str = "mock-token",
        host: str = "127.0.0.1",
        port: int = 0,
        static_dir: str | Path | None = None,
        time_scale: float = 1.0,
    ) -> None:
        self.token = token
        self.state = MockState(scenario, Clock(time_scale))
        sd = Path(static_dir) if static_dir else None
        self.httpd = ThreadingHTTPServer((host, port), make_handler(self.state, token, sd))
        self.httpd.daemon_threads = True
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> MockApi:
        def ticker() -> None:
            while not self._stop.wait(0.05):
                self.state.tick()

        for target in (self.httpd.serve_forever, ticker):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def stop(self) -> None:
        self._stop.set()
        for s in list(self.state.subscribers):
            s.put(None)
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self) -> MockApi:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--token", default="mock-token")
    ap.add_argument(
        "--scenario", default="default", help="nom (scenarios/<nom>.json) ou chemin .json"
    )
    ap.add_argument(
        "--static-dir", default=None, help="dossier de la Web UI (ex. src/btmux/api/static)"
    )
    ap.add_argument("--time-scale", type=float, default=1.0)
    a = ap.parse_args()
    api = MockApi(a.scenario, a.token, a.host, a.port, a.static_dir, a.time_scale).start()
    print(json.dumps({"url": api.url, "token": a.token, "scenario": a.scenario}), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        api.stop()


if __name__ == "__main__":
    main()
