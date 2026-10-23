import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "btmux-install-wireplumber.sh"
CONF = Path(__file__).resolve().parents[2] / "config" / "wireplumber" / "51-btmux-no-seat.conf"


def _run(home: Path, user: str = "alice", src: Path = CONF) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "BTMUX_HOME": str(home), "BTMUX_NO_RESTART": "1"}
    return subprocess.run(
        ["sh", str(SCRIPT), user, str(src)], env=env, capture_output=True, text=True, check=False
    )


def test_repo_conf_disables_seat_monitoring() -> None:
    text = CONF.read_text()
    assert "monitor.bluez.seat-monitoring = disabled" in text
    assert "wireplumber.profiles" in text


def test_installed_in_user_home(tmp_path: Path) -> None:
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    dest = tmp_path / ".config/wireplumber/wireplumber.conf.d/51-btmux-no-seat.conf"
    assert dest.read_text() == CONF.read_text()


def test_existing_file_never_overwritten(tmp_path: Path) -> None:
    dest = tmp_path / ".config/wireplumber/wireplumber.conf.d/51-btmux-no-seat.conf"
    dest.parent.mkdir(parents=True)
    dest.write_text("# admin\n")
    proc = _run(tmp_path)
    assert proc.returncode == 0
    assert "conservé" in proc.stdout
    assert dest.read_text() == "# admin\n"


def test_invalid_user_and_missing_source_rejected(tmp_path: Path) -> None:
    assert _run(tmp_path, user="root").returncode == 2
    assert _run(tmp_path, user="a;b").returncode == 2
    assert _run(tmp_path, src=tmp_path / "absent.conf").returncode == 1


def test_root_path_uses_install_with_explicit_owner(tmp_path: Path) -> None:
    """Chemin root, BTMUX_USER ≠ utilisateur de déploiement : `install -o/-g`, pas de `su -c cp`."""
    log = tmp_path / "install.log"
    fake = tmp_path / "fake-install"
    fake.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$LOG"\n'
        'if [ "$1" = "-d" ]; then shift; shift 6; mkdir -p "$1"; exit 0; fi\n'
        'shift 6; cp "$1" "$2"\n'
    )
    fake.chmod(0o755)
    src_dir = tmp_path / "deploy-0700"
    src_dir.mkdir(mode=0o700)
    src = src_dir / "51-btmux-no-seat.conf"
    src.write_text(CONF.read_text())
    home = tmp_path / "home-bob"
    home.mkdir()
    env = {
        **os.environ,
        "BTMUX_HOME": str(home),
        "BTMUX_NO_RESTART": "1",
        "BTMUX_ASSUME_ROOT": "1",
        "BTMUX_INSTALL": str(fake),
        "BTMUX_GROUP": "bobgrp",
        "LOG": str(log),
    }
    proc = subprocess.run(
        ["sh", str(SCRIPT), "bob", str(src)], env=env, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    lines = log.read_text().splitlines()
    dest = home / ".config/wireplumber/wireplumber.conf.d/51-btmux-no-seat.conf"
    assert any(ln.startswith("-d -o bob -g bobgrp -m 755") for ln in lines)
    assert f"-o bob -g bobgrp -m 644 {src} {dest}" in lines
    assert dest.read_text() == CONF.read_text()
