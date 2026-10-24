"""packaging — `btmux-adapters.sh --state` et fermeture des contrôleurs sans rôle (#23, D3).

Aucun adaptateur réel ni dépendance au code de configuration : `btmgmt`, `busctl`, `sudo` et
l'interpréteur Python (`BTMUX_PYTHON`) sont de faux exécutables. Le faux Python journalise ses
arguments et renvoie la liste effective imposée par le test (lignes `MAC<TAB>nom<TAB>rôles`,
sortie de `python -m btmux.config adapters`).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "btmux-adapters.sh"

# hci0 = Bluetooth interne (UART, sans rôle), hci1 = sources, hci2 = dongle présent mais non affecté
BTMGMT_THREE = (
    "Index list with 3 items\n"
    "hci0:\tPrimary controller\n\taddr B8:27:EB:00:00:09 version 9 manufacturer 305\n"
    "hci1:\tPrimary controller\n\taddr AA:BB:CC:00:00:01 version 11 manufacturer 93\n"
    "hci2:\tPrimary controller\n\taddr AA:BB:CC:00:00:02 version 11 manufacturer 93\n"
)
ONLY_SOURCES = "AA:BB:CC:00:00:01\tbtmux\tsources\n"
BOTH = "AA:BB:CC:00:00:01\tbtmux\tsources\nAA:BB:CC:00:00:02\tbtmux-hp\theadsets\n"


def _exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(
    tmp_path: Path, listing: str, *args: str, btmgmt: str = BTMGMT_THREE, py_rc: int = 0
) -> tuple[subprocess.CompletedProcess[str], list[str], str]:
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "fake.log"
    py_args = tmp_path / "python.args"
    (tmp_path / "btmgmt.out").write_text(btmgmt)
    (tmp_path / "listing").write_text(listing)
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
    _exe(
        bindir / "python",
        f'echo "$*" > "{py_args}"\ncat "{tmp_path / "listing"}"\nexit {py_rc}\n',
    )
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "BTMUX_BTMGMT": str(bindir / "btmgmt"),
        "BTMUX_BUSCTL": str(bindir / "busctl"),
        "BTMUX_PYTHON": str(bindir / "python"),
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--config", str(tmp_path / "config.yaml"), "--wait", "0", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=30,
        check=False,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls, py_args.read_text() if py_args.exists() else ""


# --- --state --------------------------------------------------------------------------------------
def test_state_is_forwarded_to_btmux_config(tmp_path: Path) -> None:
    state = tmp_path / "adapters.yaml"
    proc, _, py_args = _run(tmp_path, ONLY_SOURCES, "--state", str(state), "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert f"-m btmux.config adapters --config {tmp_path / 'config.yaml'}" in py_args
    assert f"--state {state}" in py_args


def test_without_state_option_btmux_config_uses_its_default(tmp_path: Path) -> None:
    proc, _, py_args = _run(tmp_path, ONLY_SOURCES, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert "--state" not in py_args


def test_state_option_requires_a_value(tmp_path: Path) -> None:
    proc, _, _ = _run(tmp_path, ONLY_SOURCES, "--state")
    assert proc.returncode != 0


def test_invalid_effective_list_exits_2_and_names_the_state(tmp_path: Path) -> None:
    proc, calls, _ = _run(tmp_path, "", "--state", "/var/lib/btmux/adapters.yaml", py_rc=2)
    assert proc.returncode == 2
    assert "/var/lib/btmux/adapters.yaml" in proc.stderr
    assert calls == []


# --- contrôleurs sans rôle ------------------------------------------------------------------------
def test_dry_run_plans_closing_of_every_unassigned_controller(tmp_path: Path) -> None:
    proc, calls, _ = _run(tmp_path, ONLY_SOURCES, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    planned = [ln for ln in proc.stdout.splitlines() if ln.startswith("DRY-RUN:")]
    for idx in ("0", "2"):
        assert f"DRY-RUN: mgmt -i {idx} bondable off" in planned
        assert f"DRY-RUN: mgmt -i {idx} discov no" in planned
    assert not [c for c in calls if "bondable" in c or "discov" in c]  # rien d'exécuté


def test_unassigned_controllers_are_closed_without_touching_class_or_alias(tmp_path: Path) -> None:
    proc, calls, _ = _run(tmp_path, ONLY_SOURCES)
    assert proc.returncode == 0, proc.stderr
    for idx in ("0", "2"):
        assert f"btmgmt -i {idx} bondable off" in calls
        assert f"btmgmt -i {idx} discov no" in calls
        assert not [c for c in calls if f"-i {idx} class" in c or f"-i {idx} power" in c]
        assert not [c for c in calls if f"/org/bluez/hci{idx} " in c]  # alias intact
    assert "btmgmt -i 1 class 4 4" in calls  # le contrôleur affecté est configuré normalement
    assert "B8:27:EB:00:00:09 -> hci0 sans rôle" in proc.stdout


def test_assigned_controllers_are_not_closed_twice(tmp_path: Path) -> None:
    proc, calls, _ = _run(tmp_path, BOTH)
    assert proc.returncode == 0, proc.stderr
    assert calls.count("btmgmt -i 1 bondable off") == 1
    assert calls.count("btmgmt -i 2 discov no") == 1
    assert "btmgmt -i 2 class 1 12" in calls
    assert "btmgmt -i 0 bondable off" in calls  # seul le contrôleur interne est sans rôle


def test_empty_assignment_closes_all_present_controllers(tmp_path: Path) -> None:
    proc, calls, _ = _run(tmp_path, "")
    assert proc.returncode == 0, proc.stderr
    for idx in ("0", "1", "2"):
        assert f"btmgmt -i {idx} bondable off" in calls and f"btmgmt -i {idx} discov no" in calls
    assert not [c for c in calls if " class " in c or "set-property" in c]


def test_reset_closes_assigned_and_unassigned_controllers(tmp_path: Path) -> None:
    proc, calls, _ = _run(tmp_path, ONLY_SOURCES, "--reset")
    assert proc.returncode == 0, proc.stderr
    for idx in ("0", "1", "2"):
        assert f"btmgmt -i {idx} bondable off" in calls and f"btmgmt -i {idx} discov no" in calls
    assert not [c for c in calls if " class " in c or "set-property" in c or " power " in c]


def test_configured_but_absent_controller_does_not_prevent_closing_the_others(
    tmp_path: Path,
) -> None:
    listing = "AA:BB:CC:00:00:07\tbtmux\tsources\n"  # MAC de l'état absente du système
    proc, calls, _ = _run(tmp_path, listing)
    assert proc.returncode == 0
    assert "introuvable" in proc.stderr
    for idx in ("0", "1", "2"):
        assert f"btmgmt -i {idx} bondable off" in calls


def test_closing_unassigned_is_idempotent(tmp_path: Path) -> None:
    a, _, _ = _run(tmp_path, ONLY_SOURCES, "--dry-run")
    b, _, _ = _run(tmp_path, ONLY_SOURCES, "--dry-run")
    assert (a.returncode, a.stdout) == (b.returncode, b.stdout)
