"""packaging — `btmux-adapters.sh --only <MAC>` (répétable), `--requests FICHIER` (#23, aa962d0).

Passe ciblée au hotplug.

Seul le contrôleur réapparu est traité : identité s'il est affecté, simple fermeture sinon ;
les autres ne sont pas touchés (une fenêtre d'appairage ouverte ailleurs reste ouverte).
MAC vide, invalide ou absente : avertissement, code 0. Faux `btmgmt`, `busctl`, `sudo`, Python.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "btmux-adapters.sh"
SERVICE = ROOT / "systemd" / "btmux-adapters-identity.service"

# hci0 = interne (sans rôle), hci1 = sources, hci2 = headsets
BTMGMT_THREE = (
    "Index list with 3 items\n"
    "hci0:\tPrimary controller\n\taddr B8:27:EB:00:00:09 version 9 manufacturer 305\n"
    "hci1:\tPrimary controller\n\taddr AA:BB:CC:00:00:01 version 11 manufacturer 93\n"
    "hci2:\tPrimary controller\n\taddr AA:BB:CC:00:00:02 version 11 manufacturer 93\n"
)
BOTH = "AA:BB:CC:00:00:01\tbtmux\tsources\nAA:BB:CC:00:00:02\tbtmux-hp\theadsets\n"


def _exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(tmp_path: Path, *args: str, cmd: list[str] | None = None):
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "fake.log"
    (tmp_path / "btmgmt.out").write_text(BTMGMT_THREE)
    (tmp_path / "listing").write_text(BOTH)
    _exe(
        bindir / "btmgmt",
        f'case "$*" in info) cat "{tmp_path / "btmgmt.out"}"; exit 0;; esac\n'
        f'echo "btmgmt $*" >> "{log}"\n',
    )
    _exe(
        bindir / "busctl",
        'case "$1" in get-property) echo \'s "old"\'; exit 0;; esac\n'
        f'echo "busctl $*" >> "{log}"\n',
    )
    _exe(bindir / "sudo", 'while [ "${1:-}" = "-n" ]; do shift; done\nexec "$@"\n')
    _exe(bindir / "python", f'cat "{tmp_path / "listing"}"\n')
    env = {
        **{k: v for k, v in os.environ.items() if k != "BTMUX_TRIGGER"},
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "BTMUX_BTMGMT": str(bindir / "btmgmt"),
        "BTMUX_BUSCTL": str(bindir / "busctl"),
        "BTMUX_PYTHON": str(bindir / "python"),
        "BTMUX_ALIAS_WAIT": "0",
    }
    argv = cmd or [
        "bash",
        str(SCRIPT),
        "--config",
        str(tmp_path / "config.yaml"),
        "--wait",
        "0",
        *args,
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True, env=env, cwd=tmp_path, timeout=30, check=False
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


def _touched(calls: list[str], idx: str) -> list[str]:
    return [c for c in calls if f"-i {idx} " in c or f"/org/bluez/hci{idx} " in c]


def test_only_assigned_controller_gets_its_identity_and_nothing_else(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, "--only", "aa:bb:cc:00:00:02")  # casse indifférente
    assert proc.returncode == 0, proc.stderr
    for expected in (
        "btmgmt -i 2 power on",
        "btmgmt -i 2 class 1 12",
        "btmgmt -i 2 bondable off",
        "btmgmt -i 2 discov no",
    ):
        assert expected in calls, expected
    assert [c for c in calls if "/org/bluez/hci2 " in c and "Alias s btmux-hp" in c]
    assert not _touched(calls, "1") and not _touched(calls, "0")  # fenêtre ouverte ailleurs intacte
    assert "contrôleur AA:BB:CC:00:00:02 seul" in proc.stdout


def test_only_unassigned_controller_is_closed_without_identity(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, "--only", "B8:27:EB:00:00:09")
    assert proc.returncode == 0, proc.stderr
    assert calls == ["btmgmt -i 0 bondable off", "btmgmt -i 0 discov no"]


@pytest.mark.parametrize("mac", ["", "pas-une-mac", "AA:BB:CC:00:00", "AA:BB:CC:00:00:0G"])
def test_only_empty_or_invalid_mac_warns_and_exits_0(tmp_path: Path, mac: str) -> None:
    proc, calls = _run(tmp_path, "--only", mac)
    assert proc.returncode == 0
    assert "MAC vide ou invalide" in proc.stderr
    assert calls == []


def test_only_absent_controller_warns_and_exits_0(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, "--only", "AA:BB:CC:00:00:07")
    assert proc.returncode == 0
    assert "AA:BB:CC:00:00:07 absent" in proc.stderr
    assert calls == []


def test_only_requires_an_argument(tmp_path: Path) -> None:
    proc, _ = _run(tmp_path, "--only")
    assert proc.returncode == 2


def test_without_only_every_controller_is_still_handled(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert all(_touched(calls, idx) for idx in ("0", "1", "2"))


def _service_command(tmp_path: Path, request: Path) -> list[str]:
    """ExecStart de l'unité, chemins système -> chemins du test."""
    line = next(x for x in SERVICE.read_text().splitlines() if x.startswith("ExecStart="))
    argv = line.removeprefix("ExecStart=").split()
    assert argv[0] == "/usr/lib/btmux/btmux-adapters.sh"
    subst = {
        "/var/lib/btmux/identity.request": str(request),
        "/etc/btmux/config.yaml": str(tmp_path / "config.yaml"),
        "/var/lib/btmux/adapters.yaml": str(tmp_path / "adapters.yaml"),
    }
    argv = ["bash", str(SCRIPT), *(subst.get(x, x) for x in argv[1:])]
    argv[argv.index("--wait") + 1] = "0"
    return argv


def _req(*macs: str) -> str:
    return "".join(f"2026-10-25T07:12:0{i}Z\thci{i}\t{m}\n" for i, m in enumerate(macs))


def test_service_reads_the_mac_from_the_request_file(tmp_path: Path) -> None:
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:02"))
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0, proc.stderr
    assert "btmgmt -i 2 class 1 12" in calls
    assert not _touched(calls, "1") and not _touched(calls, "0")


def test_service_handles_every_pending_mac_once(tmp_path: Path) -> None:
    """Deux dongles réapparus ensemble : aucune MAC perdue, doublon traité 1 fois."""
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02", "aa:bb:cc:00:00:01"))
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0, proc.stderr
    assert calls.count("btmgmt -i 1 class 4 4") == 1
    assert calls.count("btmgmt -i 2 class 1 12") == 1
    assert not _touched(calls, "0")  # contrôleur interne non demandé : intact
    assert "contrôleurs AA:BB:CC:00:00:01, AA:BB:CC:00:00:02 seuls" in proc.stdout


def test_service_skips_invalid_lines_without_echoing_them(tmp_path: Path) -> None:
    request = tmp_path / "identity.request"
    secret = "root:$6$secrethash:19000:0:99999:7:::"
    request.write_text(secret + "\n" + _req("AA:BB:CC:00:00:02") + "x\thci9\tZZ:ZZ\n\n")
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0, proc.stderr
    assert "btmgmt -i 2 class 1 12" in calls
    assert not _touched(calls, "1")
    assert "2 ligne(s) invalide(s)" in proc.stderr and "MAC invalide" in proc.stderr
    out = proc.stdout + proc.stderr
    assert "secrethash" not in out and "ZZ:ZZ" not in out and "root:" not in out


def test_service_ignores_a_symlinked_request(tmp_path: Path) -> None:
    """Répertoire du compte de service : root ne suit jamais un lien (ex. vers /etc/shadow)."""
    target = tmp_path / "secret"
    target.write_text("root:x\n" + _req("AA:BB:CC:00:00:02"))
    request = tmp_path / "identity.request"
    request.symlink_to(target)
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0
    assert "n'est pas un fichier régulier" in proc.stderr
    assert calls == []
    assert "root:x" not in proc.stdout + proc.stderr


def test_service_ignores_a_non_regular_request(tmp_path: Path) -> None:
    request = tmp_path / "identity.request"
    request.mkdir()
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0
    assert "n'est pas un fichier régulier" in proc.stderr
    assert calls == []


@pytest.mark.parametrize("content", [None, "", "\n\n", "garbage\n", "2026-10-25T07:12:03Z\thci2\n"])
def test_service_with_missing_empty_or_invalid_request_exits_0(
    tmp_path: Path, content: str | None
) -> None:
    request = tmp_path / "identity.request"
    if content is not None:
        request.write_text(content)
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0
    assert "aucune MAC valide" in proc.stderr
    assert calls == []
    assert "garbage" not in proc.stderr


def test_only_is_repeatable_and_skips_invalid_values(tmp_path: Path) -> None:
    proc, calls = _run(
        tmp_path, "--only", "AA:BB:CC:00:00:01", "--only", "bad", "--only", "B8:27:EB:00:00:09"
    )
    assert proc.returncode == 0, proc.stderr
    assert "btmgmt -i 1 class 4 4" in calls
    assert "btmgmt -i 0 bondable off" in calls
    assert not _touched(calls, "2")
    assert "MAC vide ou invalide" in proc.stderr and "bad" not in proc.stderr
