"""R-10 (#23) : `btmuxd --check-config` valide config et état."""

from __future__ import annotations

from pathlib import Path

import pytest

from btmux.cli import btmuxd

CFG = "adapters:\n  - {mac: 'AA:BB:CC:00:00:01', name: cfg, roles: [sources, headsets]}\n"
STATE = "adapters:\n  - {mac: 'AA:BB:CC:00:00:02', name: st, roles: [headsets]}\n"


def _run(tmp_path: Path, state: str | None) -> tuple[int, str, str]:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(CFG)
    path = tmp_path / "adapters.yaml"
    if state is not None:
        path.write_text(state)
    return btmuxd.main(["--config", str(cfg), "--state", str(path), "--check-config"]), "", ""


def test_check_config_without_state_reports_config_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = _run(tmp_path, None)
    out = capsys.readouterr().out
    assert code == 0 and "config OK:" in out and "source: config" in out
    assert "AA:BB:CC:00:00:01\tcfg\tsources,headsets" in out


def test_check_config_state_overrides_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = _run(tmp_path, STATE)
    out = capsys.readouterr().out
    assert code == 0 and "source: state" in out
    assert "AA:BB:CC:00:00:02\tst\theadsets" in out and "cfg" not in out.split("source:")[1]


def test_check_config_invalid_state_is_reported_and_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = _run(tmp_path, "adapters: 3\n")
    captured = capsys.readouterr()
    assert code == 0 and "source: config" in captured.out
    assert "state:" in captured.err and "ignored" in captured.err
