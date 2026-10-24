"""packaging — `btmux-adapters.sh` : attente D-Bus de l'alias, journal du déclencheur (#23, I-2).

Après un hotplug, l'index mgmt (`btmgmt info`) peut exister avant que `bluetoothd` expose
`/org/bluez/hciN` : le script attend (≤ BTMUX_ALIAS_WAIT s, pas de 0,5 s) que
`busctl get-property … Alias` réponde avant de poser l'alias ; sinon avertissement, classe et
fermeture restent appliquées.
Faux exécutables : `btmgmt`, `busctl` (échoue sur les N premiers `get-property`), `sudo`,
Python.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "btmux-adapters.sh"

BTMGMT_ONE = (
    "Index list with 1 items\n"
    "hci1:\tPrimary controller\n\taddr AA:BB:CC:00:00:01 version 11 manufacturer 93\n"
)
ONLY_SOURCES = "AA:BB:CC:00:00:01\tbtmux\tsources\n"


def _exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(
    tmp_path: Path,
    *args: str,
    absent_polls: int = 0,
    alias: str = "old",
    env_extra: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str], int]:
    """`absent_polls` : `get-property` en échec avant que l'objet D-Bus réponde (-1 : jamais)."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "fake.log"
    polls = tmp_path / "polls"
    polls.write_text("0")
    (tmp_path / "btmgmt.out").write_text(BTMGMT_ONE)
    (tmp_path / "listing").write_text(ONLY_SOURCES)
    _exe(
        bindir / "btmgmt",
        f'case "$*" in info) cat "{tmp_path / "btmgmt.out"}"; exit 0;; esac\n'
        f'echo "btmgmt $*" >> "{log}"\n',
    )
    _exe(
        bindir / "busctl",
        'if [ "$1" = get-property ]; then\n'
        f'  n=$(cat "{polls}"); n=$((n + 1)); echo "$n" > "{polls}"\n'
        f'  if [ {absent_polls} -lt 0 ] || [ "$n" -le {absent_polls} ]; then\n'
        '    echo "Unknown object" >&2; exit 1\n'
        "  fi\n"
        f"  echo 's \"{alias}\"'; exit 0\n"
        "fi\n"
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
        "BTMUX_ALIAS_WAIT": "1",
        **(env_extra or {}),
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
    return proc, calls, int(polls.read_text())


SET_ALIAS = "busctl set-property org.bluez /org/bluez/hci1 org.bluez.Adapter1 Alias s btmux"


def test_alias_is_set_once_the_dbus_object_appears(tmp_path: Path) -> None:
    proc, calls, polls = _run(tmp_path, absent_polls=1)
    assert proc.returncode == 0, proc.stderr
    assert polls == 2  # un échec, puis l'objet répond (pas de 0,5 s)
    assert SET_ALIAS in calls
    assert "AVERTISSEMENT" not in proc.stderr


def test_missing_dbus_object_warns_and_still_applies_class_and_closing(tmp_path: Path) -> None:
    proc, calls, polls = _run(tmp_path, absent_polls=-1)  # BTMUX_ALIAS_WAIT=1 : 1 + 2 essais
    assert proc.returncode == 0, proc.stderr
    assert polls == 3
    assert "/org/bluez/hci1 absent du bus après 1 s" in proc.stderr
    assert not [c for c in calls if "set-property" in c]
    for expected in (
        "btmgmt -i 1 power on",
        "btmgmt -i 1 class 4 4",
        "btmgmt -i 1 bondable off",
        "btmgmt -i 1 discov no",
    ):
        assert expected in calls, expected


def test_alias_already_right_is_not_rewritten(tmp_path: Path) -> None:
    proc, calls, polls = _run(tmp_path, alias="btmux")
    assert proc.returncode == 0, proc.stderr
    assert polls == 1  # objet présent : aucune attente
    assert not [c for c in calls if "set-property" in c]


def test_dry_run_does_not_wait_for_dbus(tmp_path: Path) -> None:
    proc, _, polls = _run(tmp_path, "--dry-run", absent_polls=-1)
    assert proc.returncode == 0, proc.stderr
    assert polls == 0
    planned = [line for line in proc.stdout.splitlines() if line.startswith("DRY-RUN:")]
    assert [line for line in planned if line.endswith(SET_ALIAS.removeprefix("busctl "))]


def test_invalid_alias_wait_exits_2(tmp_path: Path) -> None:
    proc, _, _ = _run(tmp_path, env_extra={"BTMUX_ALIAS_WAIT": "abc"})
    assert proc.returncode == 2 and "BTMUX_ALIAS_WAIT" in proc.stderr


def test_one_log_line_names_the_trigger(tmp_path: Path) -> None:
    proc, _, _ = _run(tmp_path, env_extra={"BTMUX_TRIGGER": "hotplug"})
    assert proc.stdout.count("btmux-adapters: passe identité (déclencheur : hotplug)") == 1
    reset, _, _ = _run(tmp_path, "--reset", env_extra={"BTMUX_TRIGGER": "btmuxd"})
    assert "btmux-adapters: passe fermeture (déclencheur : btmuxd)" in reset.stdout
    manual, _, _ = _run(tmp_path)
    assert "passe identité (déclencheur : manuel)" in manual.stdout
