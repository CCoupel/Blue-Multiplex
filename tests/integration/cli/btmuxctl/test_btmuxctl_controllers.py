"""btmuxctl — contrôleurs et affectation des rôles (#23, précision G8).

Commandes : `btmuxctl controllers` (JSON de GET /api/controllers) et
`btmuxctl roles set --sources <MAC|none> --headsets <MAC|none> [--confirm]`.
Code 0 = succès (200/202), 1 = erreur API (409 : `details` affichés), 2 = usage/réseau.
Cible : mock API. Skippés tant que les sous-commandes ne sont pas livrées (R-15 dev-backend).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from apisupport import TOKEN

CODE = (
    "import sys; from btmux.cli.btmuxctl import main; "
    "rc = main(); sys.exit(rc if isinstance(rc, int) else 0)"
)
SRC = "AA:BB:CC:00:00:01"
HP = "AA:BB:CC:00:00:02"
UART = "B8:27:EB:1A:2E:D6"
PC_PRO = "11:22:33:44:55:01"


@pytest.fixture
def make_ctl(api_factory, tmp_path):
    """`make_ctl(scenario)` -> (runner, client) ; skip tant que `controllers` n'existe pas."""
    pytest.importorskip("btmux.cli.btmuxctl")

    def _make(scenario="swap-ready", time_scale=100.0):
        client = api_factory(scenario, time_scale=time_scale)
        host, port = client.api.httpd.server_address[:2]
        url = f"http://{host}:{port}"

        def run(*args, token=TOKEN):
            env = {**os.environ, "BTMUX_URL": url, "BTMUX_TOKEN": token}
            return subprocess.run(
                [sys.executable, "-c", CODE, "--url", url, "--token", token, *args],
                capture_output=True,
                text=True,
                cwd=tmp_path,
                env=env,
                timeout=30,
                check=False,
            )

        probe = run("controllers")
        if "invalid choice" in probe.stderr or "not implemented" in probe.stdout + probe.stderr:
            pytest.skip("btmuxctl controllers/roles non livré (R-15 dev-backend)")
        return run, client

    return _make


def _roles(client):
    return client.call("GET", "/api/controllers")[1]["roles"]


def test_controllers_prints_the_api_json(make_ctl):
    run, client = make_ctl()
    proc = run("controllers")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out == client.call("GET", "/api/controllers")[1]
    assert {c["mac"] for c in out["controllers"]} == {SRC, HP, UART}


def test_controllers_with_wrong_token_exits_nonzero_without_leaking_it(make_ctl):
    run, _ = make_ctl()
    proc = run("controllers", token="wrong-secret")
    assert proc.returncode != 0
    assert "wrong-secret" not in proc.stdout + proc.stderr


def test_roles_set_swaps_the_roles(make_ctl):
    run, client = make_ctl()
    proc = run("roles", "set", "--sources", HP, "--headsets", SRC)
    assert proc.returncode == 0, proc.stderr
    roles = _roles(client)
    assert (roles["sources"], roles["headsets"]) == (HP, SRC)
    assert roles["pending"] is True and roles["restart_expected"] is True


def test_roles_set_none_unassigns_a_role(make_ctl):
    run, client = make_ctl()
    proc = run("roles", "set", "--sources", SRC, "--headsets", "none")
    assert proc.returncode == 0, proc.stderr
    roles = _roles(client)
    assert roles["sources"] == SRC and roles["headsets"] is None


def test_roles_set_uart_controller_is_accepted(make_ctl):
    run, client = make_ctl()
    assert run("roles", "set", "--sources", UART, "--headsets", HP).returncode == 0
    assert _roles(client)["sources"] == UART


def test_roles_set_unchanged_assignment_exits_zero(make_ctl):
    run, client = make_ctl()
    assert run("roles", "set", "--sources", SRC, "--headsets", HP).returncode == 0
    assert _roles(client)["pending"] is False


@pytest.mark.parametrize(
    "args",
    [
        ("--sources", "not-a-mac", "--headsets", HP),
        ("--sources", SRC, "--headsets", SRC),  # même contrôleur pour deux rôles
        ("--sources", "FF:FF:FF:FF:FF:FF", "--headsets", HP),  # contrôleur inconnu
    ],
)
def test_roles_set_rejected_by_the_api_exits_1_with_message(make_ctl, args):
    run, client = make_ctl()
    proc = run("roles", "set", *args)
    assert proc.returncode == 1 and proc.stderr.strip()
    assert _roles(client)["pending"] is False


@pytest.mark.parametrize("args", [(), ("--sources", SRC), ("--headsets", HP)])
def test_roles_set_requires_both_roles(make_ctl, args):
    """Corps strict (G3) : `sources` et `headsets` obligatoires, `none` pour retirer un rôle."""
    run, client = make_ctl()
    proc = run("roles", "set", *args)
    assert proc.returncode == 2 and proc.stderr.strip()
    assert _roles(client)["pending"] is False


def test_roles_set_409_devices_connected_exits_1_and_prints_details(make_ctl):
    run, client = make_ctl("default", time_scale=20.0)
    proc = run("roles", "set", "--sources", HP, "--headsets", SRC)
    assert proc.returncode == 1
    text = proc.stdout + proc.stderr
    assert "devices_connected" in text or "connect" in text.lower()
    assert PC_PRO in text  # `details` : la liste des appareils connectés est affichée
    assert _roles(client)["pending"] is False


def test_roles_set_confirm_disconnects_and_applies(make_ctl):
    run, client = make_ctl("default", time_scale=20.0)
    proc = run("roles", "set", "--sources", HP, "--headsets", SRC, "--confirm")
    assert proc.returncode == 0, proc.stderr
    roles = _roles(client)
    assert (roles["sources"], roles["headsets"]) == (HP, SRC) and roles["pending"] is True
    devices = client.call("GET", "/api/state")[1]["devices"]
    assert not any(d["connected"] for d in devices)


def test_roles_set_pairing_open_exits_1(make_ctl):
    run, client = make_ctl()
    client.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    proc = run("roles", "set", "--sources", HP, "--headsets", SRC)
    assert proc.returncode == 1 and "pairing_open" in proc.stdout + proc.stderr


def test_roles_set_while_change_pending_exits_1(make_ctl):
    run, client = make_ctl("restart-pending")
    proc = run("roles", "set", "--sources", HP, "--headsets", SRC)
    assert proc.returncode == 1 and "change_pending" in proc.stdout + proc.stderr
