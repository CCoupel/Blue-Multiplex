"""Outils des tests hardware : client HTTP vers btmuxd reel, attente, confirmation operateur."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

import pytest

MAX_LINKS = int(os.environ.get("BTMUX_HW_MAX_LINKS", "1"))


class HardwareApi:
    def __init__(self, base: str, token: str) -> None:
        self.base, self.token = base.rstrip("/"), token

    def call(self, method: str, path: str, body=None, token: str | None = None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token if token is None else token}")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, (json.loads(raw) if raw else None)

    def assert_reachable(self) -> None:
        try:
            status, _ = self.call("GET", "/api/health")
        except OSError as e:
            pytest.skip(f"btmuxd injoignable ({e})")
        assert status == 200

    def state(self) -> dict:
        status, st = self.call("GET", "/api/state")
        assert status == 200, st
        return st

    def devices(self) -> dict[str, dict]:
        return {d["mac"]: d for d in self.state()["devices"]}

    def connected_links(self) -> int:
        return sum(1 for d in self.state()["devices"] if d["connected"])

    def assert_link_budget(self, extra: int = 1) -> None:
        """Garde-fou : jamais plus de MAX_LINKS liens ACL (UART/USB partage, sans audio)."""
        n = self.connected_links()
        assert n + extra <= MAX_LINKS, (
            f"{n} lien(s) connecte(s) + {extra} > plafond {MAX_LINKS} : deconnecter avant l'etape"
        )

    def close_window(self) -> None:
        self.call("DELETE", "/api/pairing")


def wait_for(cond, timeout: float, step: float = 1.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = cond()
        if result:
            return result
        time.sleep(step)
    return None


def operator(message: str) -> None:
    """Etape manuelle : affiche la consigne et attend Entree (necessite `pytest -s`)."""
    if not sys.stdin.isatty():
        pytest.skip("etape manuelle : relancer avec `pytest -s` depuis un terminal")
    print(f"\n>>> {message}\n    [Entree quand c'est fait] ", end="", flush=True)
    input()


def operator_confirms(question: str) -> bool:
    if not sys.stdin.isatty():
        pytest.skip("etape manuelle : relancer avec `pytest -s` depuis un terminal")
    print(f"\n>>> {question} [o/N] ", end="", flush=True)
    return input().strip().lower() in {"o", "y", "oui", "yes"}
