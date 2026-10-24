"""Support des tests d'API : chargement du mock, client HTTP/SSE, attente."""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import time

from specsupport import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "btmux_api_mock", REPO_ROOT / "tests" / "fixtures" / "api-mock" / "server.py"
)
mock_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock_mod)  # type: ignore[union-attr]

TOKEN = "t0k3n"
TARGET = os.environ.get("BTMUX_API_TARGET", "mock")


class Client:
    def __init__(self, api, token: str | None = TOKEN):
        self.api, self.token = api, token

    def _conn(self, timeout=10):
        host, port = self.api.httpd.server_address[:2]
        return http.client.HTTPConnection(host, port, timeout=timeout)

    def call(self, method, path, body=None, token="default", headers=None):
        conn = self._conn()
        h = dict(headers or {})
        tok = self.token if token == "default" else token
        if tok and "Authorization" not in h:
            h["Authorization"] = f"Bearer {tok}"
        data = None
        if body is not None:
            data = json.dumps(body)
            h["Content-Type"] = "application/json"
        conn.request(method, path, data, h)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, (json.loads(raw) if raw else None)

    def sse(
        self,
        n_events,
        trigger=None,
        headers="default",
        path="/api/events",
        timeout=8,
        keep_state=False,
    ):
        """Ouvre le flux SSE, execute `trigger`, lit `n_events` evenements -> (status, lignes)."""
        conn = self._conn(timeout)
        h = {"Authorization": f"Bearer {self.token}"} if headers == "default" else headers
        conn.request("GET", path, headers=h)
        resp = conn.getresponse()
        if resp.status != 200:
            conn.close()
            return resp.status, []
        out, events, first = [], 0, True
        if trigger:
            trigger()
        block: list[str] = []
        while events < n_events:
            line = resp.fp.readline().decode()
            if not line:
                break
            block.append(line)
            if line != "\n":
                continue
            name = next((x[7:].strip() for x in block if x.startswith("event:")), None)
            if name is not None:
                drop = first and name == "state" and not keep_state  # State initial (3db8c3c)
                first = False
                if not drop:
                    out.extend(block)
                    events += 1
            block = []
        conn.close()
        return resp.status, out


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False
