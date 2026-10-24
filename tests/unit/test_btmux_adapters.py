"""scripts/btmux-adapters.sh : identité persistante des adaptateurs (faux btmgmt/busctl)."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "btmux-adapters.sh"

BI_CONFIG = """\
adapters:
  - {mac: "AA:BB:CC:00:00:01", name: btmux, roles: [sources]}
  - {mac: "AA:BB:CC:00:00:02", name: btmux-hp, roles: [headsets]}
"""
MONO_CONFIG = """\
adapters:
  - {mac: "AA:BB:CC:00:00:01", name: btmux, roles: [sources, headsets]}
"""

BTMGMT_INFO_BI = (
    "Index list with 2 items\\n"
    "hci0:\\tPrimary controller\\n\\taddr AA:BB:CC:00:00:02 version 11 manufacturer 93\\n"
    "hci1:\\tPrimary controller\\n\\taddr AA:BB:CC:00:00:01 version 11 manufacturer 93\\n"
)


def _env(tmp_path: Path, info: str, current_alias: str = "old") -> dict[str, str]:
    log = tmp_path / "calls.log"
    btmgmt = tmp_path / "btmgmt"
    btmgmt.write_text(
        '#!/bin/sh\nif [ "$1" = info ]; then printf "' + info + '"; exit 0; fi\n'
        f'echo "btmgmt $*" >> "{log}"\n'
    )
    busctl = tmp_path / "busctl"
    busctl.write_text(
        '#!/bin/sh\nif [ "$1" = get-property ]; then echo \'s "'
        + current_alias
        + "\"'; exit 0; fi\n"
        f'echo "busctl $*" >> "{log}"\n'
    )
    for tool in (btmgmt, busctl):
        tool.chmod(0o755)
    return {
        **os.environ,
        "BTMUX_BTMGMT": str(btmgmt),
        "BTMUX_BUSCTL": str(busctl),
        "BTMUX_PYTHON": sys.executable,
        "PYTHONPATH": str(ROOT / "src"),
        "BTMUX_CALLS": str(log),
    }


def _run(tmp_path: Path, config: str, info: str, *args: str, alias: str = "old"):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(config)
    env = _env(tmp_path, info, alias)
    # hors root le script préfixe `sudo -n` : un faux sudo l'exécute tel quel
    sudo = tmp_path / "sudo"
    sudo.write_text('#!/bin/sh\nshift\nexec "$@"\n')  # `sudo -n cmd...` -> cmd
    sudo.chmod(0o755)
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--config", str(cfg), "--wait", "0", *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = (tmp_path / "calls.log").read_text() if (tmp_path / "calls.log").exists() else ""
    return proc, calls


def test_dry_run_plans_commands_without_executing(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, BI_CONFIG, BTMGMT_INFO_BI, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert calls == ""  # rien n'a été exécuté
    out = proc.stdout
    assert "AA:BB:CC:00:00:01 -> hci1" in out and "AA:BB:CC:00:00:02 -> hci0" in out
    assert "DRY-RUN:" in out and "-i 1 class 4 4" in out  # sources : casque
    assert "-i 0 class 1 12" in out  # headsets : ordinateur
    assert "-i 1 bondable off" in out and "-i 0 discov no" in out
    assert "Alias s btmux-hp" in out


def test_real_run_applies_class_alias_and_closes_pairing(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, BI_CONFIG, BTMGMT_INFO_BI)
    assert proc.returncode == 0, proc.stderr
    assert "btmgmt -i 1 class 4 4" in calls
    assert "btmgmt -i 0 class 1 12" in calls
    assert "busctl set-property org.bluez /org/bluez/hci1 org.bluez.Adapter1 Alias s btmux" in calls
    assert "btmgmt -i 0 bondable off" in calls and "btmgmt -i 1 discov no" in calls


def test_idempotent_alias_not_rewritten_when_identical(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, MONO_CONFIG, BTMGMT_INFO_BI, alias="btmux")
    assert proc.returncode == 0, proc.stderr
    assert "set-property" not in calls  # alias déjà bon
    assert "class 4 4" in calls  # mono : rôles sources + headsets -> classe casque


def test_missing_adapter_warns_and_exits_zero(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, BI_CONFIG, "Index list with 0 items\\n")
    assert proc.returncode == 0
    assert "AVERTISSEMENT" in proc.stderr and "introuvable" in proc.stderr
    assert calls == ""


def test_one_of_two_adapters_present(tmp_path: Path) -> None:
    info = (
        "Index list with 1 item\\nhci0:\\tPrimary controller\\n"
        "\\taddr AA:BB:CC:00:00:02 version 11\\n"
    )
    proc, calls = _run(tmp_path, BI_CONFIG, info)
    assert proc.returncode == 0
    assert "btmgmt -i 0 class 1 12" in calls
    assert "AA:BB:CC:00:00:01" in proc.stderr  # l'autre est signalé absent


def test_invalid_config_exits_2(tmp_path: Path) -> None:
    proc, _ = _run(tmp_path, "adapters: 3\n", BTMGMT_INFO_BI)
    assert proc.returncode == 2
    assert "configuration invalide" in proc.stderr


def test_btmgmt_failure_exits_zero_with_message(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BI_CONFIG)
    env = _env(tmp_path, BTMGMT_INFO_BI)
    (tmp_path / "btmgmt").write_text(
        "#!/bin/sh\nexit 1\n"
    )  # sudo refusé / socket mgmt indisponible
    sudo = tmp_path / "sudo"
    sudo.write_text('#!/bin/sh\nshift\nexec "$@"\n')
    sudo.chmod(0o755)
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--config", str(cfg), "--wait", "0"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "btmgmt" in proc.stderr and "aucun adaptateur configurable" in proc.stderr


def test_runs_without_tty_stdin_devnull(tmp_path: Path) -> None:
    """Contexte systemd (stdin /dev/null) : btmgmt s'y bloque, le script lui fournit un tube."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BI_CONFIG)
    env = _env(tmp_path, BTMGMT_INFO_BI)
    log = tmp_path / "calls.log"
    (tmp_path / "btmgmt").write_text(
        '#!/bin/sh\n[ "$(readlink /proc/self/fd/0)" = /dev/null ] && exec sleep 60\n'
        'if [ "$1" = info ]; then printf "' + BTMGMT_INFO_BI + '"; exit 0; fi\n'
        f'echo "btmgmt $*" >> "{log}"\n'
    )
    (tmp_path / "btmgmt").chmod(0o755)
    sudo = tmp_path / "sudo"
    sudo.write_text('#!/bin/sh\nshift\nexec "$@"\n')
    sudo.chmod(0o755)
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--config", str(cfg), "--wait", "0"],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "btmgmt -i 1 class 4 4" in log.read_text()


def test_unit_file_shape() -> None:
    unit = (ROOT / "systemd" / "btmux-adapters.service").read_text()
    assert "TimeoutStartSec=60" in unit and "Requires=" not in unit
    assert "Type=oneshot" in unit and "After=bluetooth.service" in unit
    assert "/usr/lib/btmux/btmux-adapters.sh" in unit and "RemainAfterExit=yes" in unit
