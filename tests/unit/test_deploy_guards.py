import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _deploy(
    tmp_path: Path, env_text: str, with_lock: bool = True
) -> subprocess.CompletedProcess[str]:
    env_file = tmp_path / "t.env"
    env_file.write_text(env_text)
    wheel = tmp_path / "btmux-0.0.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    if with_lock:
        (tmp_path / "btmux-0.0.0.requirements.lock.txt").write_text("x==1 --hash=sha256:0\n")
    # ssh/scp factices en tete du PATH : si une garde laisse passer, le test echoue (rc != attendu)
    # au lieu de joindre une vraie machine.
    fake = tmp_path / "bin"
    fake.mkdir()
    for name in ("ssh", "scp"):
        stub = fake / name
        stub.write_text("#!/bin/sh\necho SSH-APPELE >&2\nexit 99\n")
        stub.chmod(0o755)
    env = {**os.environ, "BTMUX_ENV_FILE": str(env_file), "PATH": f"{fake}:{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "deploy.sh"), "t", str(wheel)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )


@pytest.mark.parametrize(
    "env_text",
    [
        "SSH_KEY_PATH=/k\nDEPLOY_HOST=root@btmux.local\n",
        "SSH_KEY_PATH=/k\nDEPLOY_HOST=ubuntu@btmux.local\nBTMUX_USER=root\n",
    ],
)
def test_root_refused_before_ssh(tmp_path: Path, env_text: str) -> None:
    proc = _deploy(tmp_path, env_text)
    assert proc.returncode == 2, proc.stderr
    assert "root" in proc.stderr
    assert "SSH-APPELE" not in proc.stderr


@pytest.mark.parametrize(
    "env_text",
    [
        "SSH_KEY_PATH=/k\nDEPLOY_HOST=-oProxyCommand=x\n",
        "SSH_KEY_PATH=/k\nDEPLOY_HOST=a@h\nBTMUX_USER='a;b'\n",
    ],
)
def test_invalid_inputs_refused_before_ssh(tmp_path: Path, env_text: str) -> None:
    proc = _deploy(tmp_path, env_text)
    assert proc.returncode == 1, proc.stderr
    assert "invalide" in proc.stderr
    assert "SSH-APPELE" not in proc.stderr


def test_missing_lockfile_refused_before_ssh(tmp_path: Path) -> None:
    proc = _deploy(tmp_path, "SSH_KEY_PATH=/k\nDEPLOY_HOST=ubuntu@btmux.local\n", with_lock=False)
    assert proc.returncode == 1, proc.stderr
    assert "lockfile introuvable" in proc.stderr
    assert "SSH-APPELE" not in proc.stderr
