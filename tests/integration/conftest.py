"""Fixtures partagees des tests d'integration de specification (config + CLI).

Source : contracts/config-schema.md (v0.1.0). Aucun acces BlueZ/PipeWire.

Garde CI : tant que le code n'existe pas (T1.1 squelette, T1.5 module config), les tests
sont *skippes* (pytest.importorskip) au lieu d'echouer, pour ne pas casser la CI de
dev-backend. Des que `btmux.config` est livre (T1.5), ils deviennent actifs et doivent passer.
"""

from __future__ import annotations

import copy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from apisupport import TARGET, TOKEN, Client, mock_mod

VALID_CONFIG: dict[str, Any] = {
    "adapters": [
        {"mac": "AA:BB:CC:00:00:01", "name": "btmux", "roles": ["sources", "headsets"]},
    ],
    "devices": [
        {"mac": "11:22:33:44:55:01", "alias": "pc-pro", "kind": "source", "priority": 10},
        {"mac": "11:22:33:44:55:02", "alias": "tel-perso", "kind": "source", "priority": 20},
        {"mac": "11:22:33:44:55:03", "alias": "xm5", "kind": "headset"},
    ],
    "default_routes": {"xm5": "pc-pro"},
}


@pytest.fixture
def cfgmod():
    """Module `btmux.config` (skip tant que T1.5 n'est pas livre)."""
    return pytest.importorskip("btmux.config")


@pytest.fixture
def valid_config() -> dict[str, Any]:
    """Copie fraiche d'une configuration valide (mono-adaptateur, 2 sources, 1 casque)."""
    return copy.deepcopy(VALID_CONFIG)


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[..., Path]:
    """Ecrit une config (dict -> YAML, ou str brut) dans tmp_path et retourne le chemin."""

    def _write(data: dict[str, Any] | str, name: str = "config.yaml") -> Path:
        path = tmp_path / name
        text = data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False)
        path.write_text(text, encoding="utf-8")
        return path

    return _write


@pytest.fixture
def load(cfgmod, write_config):
    """`load(data)` -> Config ; leve ConfigError si invalide."""

    def _load(data: dict[str, Any] | str):
        return cfgmod.load_config(write_config(data))

    return _load


@pytest.fixture
def errors_of(cfgmod, write_config):
    """`errors_of(data)` -> liste des erreurs (sans le prefixe 'config: '), exige un ConfigError."""

    def _errors(data: dict[str, Any] | str) -> list[str]:
        with pytest.raises(cfgmod.ConfigError) as exc:
            cfgmod.load_config(write_config(data))
        errs = list(exc.value.errors)
        assert errs, "ConfigError doit porter au moins une erreur"
        return [e.removeprefix("config: ") for e in errs]

    return _errors


@pytest.fixture
def run_btmuxd(tmp_path: Path):
    """`run_btmuxd(*args)` -> CompletedProcess (stdout/stderr texte).

    Lance `btmux.cli.btmuxd.main()` dans un sous-processus (argv = args). Aucun reseau/BlueZ.
    Hypothese : main() lit sys.argv et retourne un code (ou leve SystemExit).
    """
    pytest.importorskip("btmux.cli.btmuxd")
    code = (
        "import sys; from btmux.cli.btmuxd import main; "
        "rc = main(); sys.exit(rc if isinstance(rc, int) else 0)"
    )

    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", code, *args],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=30,
            check=False,
        )

    return _run


@pytest.fixture
def run_btmuxd_cfg(run_btmuxd, cfgmod):
    """Comme run_btmuxd, mais exige aussi le module config (T1.5) : --config/--check-config."""
    return run_btmuxd


@pytest.fixture
def run_btmuxctl(tmp_path: Path):
    pytest.importorskip("btmux.cli.btmuxctl")
    code = (
        "import sys; from btmux.cli.btmuxctl import main; "
        "rc = main(); sys.exit(rc if isinstance(rc, int) else 0)"
    )

    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", code, *args],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=30,
            check=False,
        )

    return _run


@pytest.fixture
def api_factory():
    """`api_factory(scenario="default", time_scale=20)` -> Client ; arrete les serveurs a la fin."""
    started = []

    def _make(scenario="default", time_scale=20.0):
        if TARGET != "mock":
            pytest.skip("cible `real` : harnais de l'application reelle (T2.3) non disponible")
        api = mock_mod.MockApi(scenario, token=TOKEN, time_scale=time_scale).start()
        started.append(api)
        return Client(api)

    yield _make
    for a in started:
        a.stop()


@pytest.fixture
def api(api_factory):
    return api_factory("default")
