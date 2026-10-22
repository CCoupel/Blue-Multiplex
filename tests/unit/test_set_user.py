import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "btmux-set-user.sh"


def _run(user: str, dropin: Path, uid: str = "1234") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "BTMUX_DROPIN_DIR": str(dropin), "BTMUX_UID": uid}
    return subprocess.run(
        ["sh", str(SCRIPT), user], env=env, capture_output=True, text=True, check=False
    )


def test_dropin_written_for_user(tmp_path: Path) -> None:
    proc = _run("alice", tmp_path / "d")
    assert proc.returncode == 0, proc.stderr
    conf = (tmp_path / "d" / "user.conf").read_text()
    assert "User=alice" in conf
    assert "XDG_RUNTIME_DIR=/run/user/1234" in conf
    assert "user@1234.service" in conf


def test_idempotent(tmp_path: Path) -> None:
    _run("alice", tmp_path)
    first = (tmp_path / "user.conf").read_text()
    _run("alice", tmp_path)
    assert (tmp_path / "user.conf").read_text() == first


@pytest.mark.parametrize("bad", ["Bad User", "a;b", "-x", "A"])
def test_invalid_user_rejected(tmp_path: Path, bad: str) -> None:
    proc = _run(bad, tmp_path)
    assert proc.returncode == 2
    assert not (tmp_path / "user.conf").exists()
