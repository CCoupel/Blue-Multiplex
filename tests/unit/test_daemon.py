from pathlib import Path

import pytest

from btmux import daemon
from btmux.cli import btmuxd


def test_invalid_config_does_not_start_daemon(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon, "run", lambda *a: pytest.fail("daemon démarré"))
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("adapters: 3\n")
    assert btmuxd.main(["--config", str(cfg)]) == 2
    assert "config:" in capsys.readouterr().err
