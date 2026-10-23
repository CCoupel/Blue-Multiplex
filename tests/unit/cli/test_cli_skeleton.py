from pathlib import Path

import pytest

from btmux import __version__
from btmux.cli import btmuxctl, btmuxd


def test_btmuxd_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        btmuxd.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"btmuxd {__version__}"


def test_btmuxd_declares_config_options() -> None:
    args = btmuxd.build_parser().parse_args(["--config", "/x.yaml", "--check-config"])
    assert args.config == "/x.yaml"
    assert args.check_config is True


def test_btmuxd_default_config() -> None:
    assert btmuxd.build_parser().parse_args([]).config == btmuxd.DEFAULT_CONFIG


def test_btmuxd_missing_config_exits_2(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert btmuxd.main(["--config", str(tmp_path / "absent.yaml")]) == 2
    assert "config: cannot read" in capsys.readouterr().err


def test_btmuxctl_stub(capsys: pytest.CaptureFixture[str]) -> None:
    assert btmuxctl.main([]) == 1
    assert "not implemented" in capsys.readouterr().err
