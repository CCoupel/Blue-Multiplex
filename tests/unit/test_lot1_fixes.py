"""Corrections revue/QA LOT-1 : validation adaptateurs, agent fail-closed, CLI config."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

from btmux.config import ConfigError, parse_config
from btmux.config.__main__ import main as config_main

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "spikes" / "common"))
import agent  # noqa: E402

BASE: dict[str, Any] = {
    "adapters": [
        {"mac": "aa:bb:cc:00:00:01", "name": "btmux", "roles": ["sources"]},
        {"mac": "aa:bb:cc:00:00:02", "name": "btmux-hp", "roles": ["headsets"]},
    ],
    "devices": [],
}


def _errors(data: Any) -> list[str]:
    with pytest.raises(ConfigError) as exc:
        parse_config(data)
    return exc.value.errors


def test_duplicate_adapter_mac_rejected() -> None:
    data = copy.deepcopy(BASE)
    data["adapters"][1]["mac"] = "AA:BB:CC:00:00:01"
    assert any("duplicate adapter mac" in e for e in _errors(data))


@pytest.mark.parametrize("name", ["a\tb", "a\nb", "a\rb", "", "a\x1b", "a\u2028b", "é" * 125])
def test_adapter_name_strict(name: str) -> None:
    data = copy.deepcopy(BASE)
    data["adapters"][0]["name"] = name
    assert any("adapters[0].name" in e for e in _errors(data))


def test_adapter_name_valid() -> None:
    data = copy.deepcopy(BASE)
    data["adapters"][0]["name"] = "btmux é-1"
    assert parse_config(data).adapters[0].name == "btmux é-1"


def test_config_cli_adapters_tsv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        'adapters:\n  - {mac: "AA:BB:CC:00:00:01", name: btmux, roles: [sources, headsets]}\n'
    )
    assert config_main(["adapters", "--config", str(cfg)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "AA:BB:CC:00:00:01\tbtmux\tsources,headsets"


def test_config_cli_invalid_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text("adapters: 3\n")
    assert config_main(["adapters", "--config", str(cfg)]) == 2
    assert capsys.readouterr().err


def test_agent_fail_closed_without_sources_adapter() -> None:
    policy = agent.PairingPolicy(window_until=10**12, clock=lambda: 0.0)
    assert policy.sources_adapter is None
    assert policy.window_open()
    assert not policy.accept_pairing("/org/bluez/hci0")
    policy.sources_adapter = "/org/bluez/hci0"
    assert policy.accept_pairing("/org/bluez/hci0")
    assert not policy.accept_pairing("/org/bluez/hci1")
