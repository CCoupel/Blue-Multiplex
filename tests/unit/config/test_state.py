from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from btmux.config import (
    ConfigError,
    load_effective,
    load_state,
    parse_adapter_list,
    write_state_atomic,
)
from btmux.config.models import Adapter

CONFIG = """\
adapters:
  - {mac: "AA:BB:CC:00:00:01", name: btmux, roles: [sources, headsets]}
"""
SRC = Adapter(mac="18:69:45:42:9D:E2", name="btmux", roles=("sources",))
HP = Adapter(mac="18:69:45:42:B5:54", name="btmux-hp", roles=("headsets",))


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG)
    return path


def test_state_absent_means_config(tmp_path: Path) -> None:
    cfg = load_effective(_config(tmp_path), tmp_path / "adapters.yaml")
    assert cfg.adapters_source == "config" and cfg.adapters[0].mac == "AA:BB:CC:00:00:01"
    assert load_state(tmp_path / "absent.yaml") is None


def test_state_overrides_config_and_roundtrips(tmp_path: Path) -> None:
    state = tmp_path / "var" / "adapters.yaml"
    write_state_atomic(state, [SRC, HP])
    assert stat.S_IMODE(os.stat(state).st_mode) == 0o640
    assert not [p for p in state.parent.iterdir() if p.name != "adapters.yaml"]  # pas de temporaire
    cfg = load_effective(_config(tmp_path), state)
    assert cfg.adapters_source == "state" and cfg.state_path == state
    assert [(a.mac, a.name, a.roles) for a in cfg.adapters] == [
        ("18:69:45:42:9D:E2", "btmux", ("sources",)),
        ("18:69:45:42:B5:54", "btmux-hp", ("headsets",)),
    ]
    assert cfg.adapter_for_role("headsets").mac == "18:69:45:42:B5:54"


def test_empty_state_list_frees_all_roles(tmp_path: Path) -> None:
    state = tmp_path / "adapters.yaml"
    write_state_atomic(state, [])
    cfg = load_effective(_config(tmp_path), state)
    assert cfg.adapters == () and cfg.adapters_source == "state"
    with pytest.raises(LookupError):
        cfg.adapter_for_role("sources")


@pytest.mark.parametrize(
    "text",
    [
        "adapters: 3\n",
        "other: 1\n",
        "- not a mapping\n",
        "adapters: [ {mac: bad, name: x, roles: [sources]} ]\n",
        (
            "adapters:\n"
            "  - {mac: 'AA:BB:CC:00:00:01', name: a, roles: [sources]}\n"
            "  - {mac: 'AA:BB:CC:00:00:02', name: b, roles: [sources]}\n"
        ),
        "adapters: [unclosed\n",
    ],
)
def test_invalid_state_falls_back_to_config_and_is_reported(
    tmp_path: Path, text: str, caplog: pytest.LogCaptureFixture
) -> None:
    state = tmp_path / "adapters.yaml"
    state.write_text(text)
    with pytest.raises(ConfigError):
        load_state(state)
    cfg = load_effective(_config(tmp_path), state)
    assert cfg.adapters_source == "config"
    assert "event=state_invalid" in caplog.text


def test_unreadable_state_is_an_error(tmp_path: Path) -> None:
    directory = tmp_path / "adapters.yaml"
    directory.mkdir()  # lire un dossier : OSError
    with pytest.raises(ConfigError, match="cannot read"):
        load_state(directory)


def test_write_failure_leaves_no_temporary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(src: str, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_state_atomic(tmp_path / "adapters.yaml", [SRC])
    assert list(tmp_path.iterdir()) == []


def test_parse_adapter_list_rules() -> None:
    assert parse_adapter_list([]) == ()
    with pytest.raises(ConfigError, match="at most one adapter"):
        parse_adapter_list(
            [
                {"mac": "AA:BB:CC:00:00:01", "name": "a", "roles": ["headsets"]},
                {"mac": "AA:BB:CC:00:00:02", "name": "b", "roles": ["headsets"]},
            ]
        )
