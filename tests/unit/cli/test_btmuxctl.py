from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from btmux.cli import btmuxctl

SEEN: list[tuple[str, str, str | None, bytes]] = []


class Handler(BaseHTTPRequestHandler):
    def _go(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        SEEN.append((self.command, self.path, self.headers.get("Authorization"), body))
        if "boom" in self.path:
            payload, status = {"error": "stale_bond", "message": "oublier des deux côtés"}, 409
        elif self.path == "/api/state":
            payload, status = {"version": "x", "adapters": []}, 200
        elif self.command == "DELETE":
            payload, status = None, 204
        else:
            payload, status = {"ok": True}, 202
        self.send_response(status)
        if payload is not None:
            data = json.dumps(payload).encode()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.end_headers()

    do_GET = do_POST = do_DELETE = _go

    def log_message(self, *args: Any) -> None: ...


@pytest.fixture
def url() -> Any:
    SEEN.clear()
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_state_prints_json_with_bearer(url: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert btmuxctl.main(["--url", url, "--token", "tok", "state"]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == "x"
    assert SEEN[0][:3] == ("GET", "/api/state", "Bearer tok")


def test_pairing_open_close_and_device_actions(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BTMUX_URL", url)
    monkeypatch.setenv("BTMUX_TOKEN", "envtok")
    assert btmuxctl.main(["pairing", "open", "headsets", "45"]) == 0
    assert btmuxctl.main(["pairing", "open", "sources"]) == 0
    assert btmuxctl.main(["pairing", "close"]) == 0
    for action in ("pair", "connect", "disconnect", "forget"):
        assert btmuxctl.main(["device", action, "AA:BB:CC:DD:EE:FF"]) == 0
    assert json.loads(SEEN[0][3]) == {"adapter": "headsets", "duration": 45}
    assert json.loads(SEEN[1][3]) == {"adapter": "sources"}
    assert SEEN[2][:2] == ("DELETE", "/api/pairing") and SEEN[2][2] == "Bearer envtok"
    assert [s[1] for s in SEEN[3:]] == [
        f"/api/devices/AA:BB:CC:DD:EE:FF/{a}" for a in ("pair", "connect", "disconnect", "forget")
    ]


def test_api_error_exits_1_with_message(url: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert btmuxctl.main(["--url", url, "--token", "t", "device", "pair", "boom"]) == 1
    err = capsys.readouterr().err
    assert "409" in err and "stale_bond" in err


def test_unreachable_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    import socket

    with socket.socket() as sock:  # port libre puis fermé : connexion refusée immédiatement
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert btmuxctl.main(["--url", f"http://127.0.0.1:{port}", "--token", "t", "state"]) == 2
    assert "cannot reach" in capsys.readouterr().err


def test_resolve_token_prefers_argument(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    assert btmuxctl.resolve_token("abc") == "abc"
    f = tmp_path / "token"
    f.write_text("fromfile\n")
    monkeypatch.setattr(btmuxctl, "DEFAULT_TOKEN_FILE", f)
    assert btmuxctl.resolve_token(None) == "fromfile"
    f.write_text("")
    assert btmuxctl.resolve_token(None) is None
    monkeypatch.setattr(btmuxctl, "DEFAULT_TOKEN_FILE", tmp_path / "absent")
    assert btmuxctl.resolve_token(None) is None


def test_usage_errors_exit_2() -> None:
    with pytest.raises(SystemExit) as info:
        btmuxctl.main([])
    assert info.value.code == 2
