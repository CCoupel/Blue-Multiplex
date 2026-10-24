"""cli — `btmuxctl` minimal v0.2.0 (#21) contre le mock.

Commandes (plan T2.3) : `state`, `pairing open|close`, `device pair|connect|disconnect|forget`.
Interface supposee (a confirmer avec dev-backend) : options `--url <base>` et `--token <jeton>` (ou
BTMUX_URL / BTMUX_TOKEN) ; code 0 = succes, != 0 = erreur API/reseau, message sur stderr ; `state`
imprime le JSON de `GET /api/state`. Skippes tant que btmuxctl est un stub.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from apisupport import TOKEN, wait_for

CODE = (
    "import sys; from btmux.cli.btmuxctl import main; "
    "rc = main(); sys.exit(rc if isinstance(rc, int) else 0)"
)


@pytest.fixture
def ctl(api, tmp_path):
    pytest.importorskip("btmux.cli.btmuxctl")
    probe = subprocess.run(
        [sys.executable, "-c", CODE], capture_output=True, text=True, check=False
    )
    if "not implemented" in probe.stdout + probe.stderr:
        pytest.skip("btmuxctl est encore un stub (T2.3 dev-backend)")
    host, port = api.api.httpd.server_address[:2]
    url = f"http://{host}:{port}"

    def _run(*args, token=TOKEN, url_=url):
        env = {**os.environ, "BTMUX_URL": url_, "BTMUX_TOKEN": token}
        return subprocess.run(
            [sys.executable, "-c", CODE, "--url", url_, "--token", token, *args],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env=env,
            timeout=30,
            check=False,
        )

    _run.url = url
    return _run


def test_state_prints_the_api_state_as_json(ctl):
    proc = ctl("state")
    assert proc.returncode == 0, proc.stderr
    st = json.loads(proc.stdout)
    assert set(st) == {"version", "adapters", "devices", "pairing"}


def test_pairing_open_then_close(ctl, api):
    assert ctl("pairing", "open", "sources", "60").returncode == 0
    assert api.call("GET", "/api/state")[1]["pairing"]["adapter"] == "sources"
    assert ctl("pairing", "close").returncode == 0
    assert api.call("GET", "/api/state")[1]["pairing"] is None


def test_pairing_open_twice_fails_with_message(ctl):
    assert ctl("pairing", "open", "sources", "60").returncode == 0
    proc = ctl("pairing", "open", "headsets", "60")
    assert proc.returncode != 0 and proc.stderr.strip()


def test_pairing_open_rejects_invalid_duration(ctl):
    assert ctl("pairing", "open", "sources", "999").returncode != 0


def test_device_connect_disconnect_forget(ctl, api):
    mac = "11:22:33:44:55:02"
    assert ctl("device", "connect", mac).returncode == 0
    assert wait_for(
        lambda: any(
            d["mac"] == mac and d["connected"] for d in api.call("GET", "/api/state")[1]["devices"]
        )
    )
    assert ctl("device", "disconnect", mac).returncode == 0
    assert ctl("device", "forget", mac).returncode == 0


def test_device_pair_requires_open_headsets_window(ctl):
    proc = ctl("device", "pair", "AA:11:22:33:44:55")
    assert proc.returncode != 0 and proc.stderr.strip()


def test_unknown_device_exits_nonzero(ctl):
    assert ctl("device", "connect", "AA:00:00:00:00:99").returncode != 0


def test_wrong_token_exits_nonzero_without_leaking_it(ctl):
    proc = ctl("state", token="wrong-secret")
    assert proc.returncode != 0
    assert "wrong-secret" not in proc.stdout + proc.stderr


def test_unreachable_server_exits_nonzero_with_message(ctl):
    proc = ctl("state", url_="http://127.0.0.1:9")
    assert proc.returncode != 0 and proc.stderr.strip()
