"""packaging — syntaxe des scripts shell et `btmux-adapters.sh --dry-run` (#18).

Aucun adaptateur reel : `btmgmt`, `busctl` et `sudo` sont de faux executables (BTMUX_BTMGMT,
BTMUX_BUSCTL, PATH) ; leurs invocations sont journalisees dans fake.log. Interface : voir l'en-tete
de scripts/btmux-adapters.sh (`--config`, `--dry-run`, `--wait`).
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from specsupport import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "btmux-adapters.sh"

SHELL_FILES = sorted(
    {
        *(REPO_ROOT / "scripts").glob("*.sh"),
        *(REPO_ROOT / "spikes").rglob("*.sh"),
    }
)


def _shell_for(path: Path) -> str:
    first = path.read_text(errors="replace").splitlines()[:1]
    return "sh" if first and re.search(r"(^|/)sh(\s|$)", first[0]) else "bash"


@pytest.mark.parametrize("path", SHELL_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_shell_script_has_valid_syntax(path):
    proc = subprocess.run(
        [_shell_for(path), "-n", str(path)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "path", [p for p in SHELL_FILES if p.parent.name == "scripts"], ids=lambda p: p.name
)
def test_repo_scripts_start_with_a_shebang(path):
    assert path.read_text(errors="replace").startswith("#!")


# --- btmux-adapters.sh --------------------------------------------------------------------------
pytestmark_adapters = pytest.mark.skipif(
    not SCRIPT.exists(), reason="scripts/btmux-adapters.sh absent (T1.3 #18, dev-backend)"
)

BTMGMT_TWO = """Index list with 2 items
hci0:\tPrimary controller
\taddr AA:BB:CC:00:00:01 version 11 manufacturer 93 class 0x000000
\tsupported settings: powered connectable discoverable bondable
hci1:\tPrimary controller
\taddr AA:BB:CC:00:00:02 version 11 manufacturer 93 class 0x000000
\tsupported settings: powered connectable discoverable bondable
"""
BTMGMT_NONE = "Index list with 0 items\n"

BI_CONFIG = {
    "adapters": [
        {"mac": "AA:BB:CC:00:00:02", "name": "btmux-src", "roles": ["headsets"]},
        {"mac": "AA:BB:CC:00:00:01", "name": "btmux", "roles": ["sources"]},
    ],
    "devices": [],
}
MUTATING = re.compile(r"\b(class|set-property|power|bondable|discov)\b")


def _fake_bin(tmp_path: Path, btmgmt_out: str) -> tuple[Path, Path]:
    """Faux `btmgmt`, `busctl`, `sudo` (transparent) ; appels journalises dans fake.log."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "fake.log"
    (tmp_path / "btmgmt.out").write_text(btmgmt_out)
    scripts = {
        "btmgmt": (
            f'echo "btmgmt $*" >> "{log}"\n'
            f'case "$*" in info) cat "{tmp_path / "btmgmt.out"}";; esac\nexit 0\n'
        ),
        "busctl": f'echo "busctl $*" >> "{log}"\nexit 0\n',
        "sudo": 'while [ "${1:-}" = "-n" ]; do shift; done\nexec "$@"\n',
    }
    for name, body in scripts.items():
        exe = bindir / name
        exe.write_text("#!/bin/sh\n" + body)
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return bindir, log


def _env(bindir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "BTMUX_BTMGMT": str(bindir / "btmgmt"),
        "BTMUX_BUSCTL": str(bindir / "busctl"),
        "BTMUX_PYTHON": sys.executable,  # interprete du venv de test : `-m btmux.config` disponible
    }


def _run(tmp_path: Path, cfg: dict, btmgmt: str, _btctl: str = "", *args: str):
    bindir, log = _fake_bin(tmp_path, btmgmt)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--config", str(cfg_path), "--wait", "0", *args],
        capture_output=True,
        text=True,
        env=_env(bindir),
        cwd=tmp_path,
        timeout=30,
        check=False,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


@pytestmark_adapters
def test_dry_run_two_adapters_exits_0_and_maps_mac_to_index(tmp_path):
    proc, _ = _run(tmp_path, BI_CONFIG, BTMGMT_TWO, "", "--dry-run")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "AA:BB:CC:00:00:01" in out and "AA:BB:CC:00:00:02" in out
    # MAC -> hciN : la config liste le casque (…02) en premier, l'index vient de `btmgmt info`
    assert re.search(r"hci0.*AA:BB:CC:00:00:01|AA:BB:CC:00:00:01.*hci0", out)
    assert re.search(r"hci1.*AA:BB:CC:00:00:02|AA:BB:CC:00:00:02.*hci1", out)


@pytestmark_adapters
def test_dry_run_mentions_configured_adapter_names(tmp_path):
    proc, _ = _run(tmp_path, BI_CONFIG, BTMGMT_TWO, "", "--dry-run")
    out = proc.stdout + proc.stderr
    assert "btmux" in out and "btmux-src" in out


@pytestmark_adapters
def test_dry_run_does_not_mutate_the_controllers(tmp_path):
    proc, calls = _run(tmp_path, BI_CONFIG, BTMGMT_TWO, "", "--dry-run")
    assert proc.returncode == 0
    mutating = [c for c in calls if MUTATING.search(c)]
    assert not mutating, f"commandes modifiantes en --dry-run : {mutating}"


@pytestmark_adapters
def test_dry_run_is_idempotent(tmp_path):
    a, _ = _run(tmp_path, BI_CONFIG, BTMGMT_TWO, "", "--dry-run")
    b, _ = _run(tmp_path, BI_CONFIG, BTMGMT_TWO, "", "--dry-run")
    assert (a.returncode, a.stdout) == (b.returncode, b.stdout)


@pytestmark_adapters
def test_no_adapter_present_exits_0_with_warning(tmp_path):
    proc, _ = _run(tmp_path, BI_CONFIG, BTMGMT_NONE, "", "--dry-run")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert re.search(r"warn|avertissement|no adapter|aucun", out, re.I), out


@pytestmark_adapters
def test_no_adapter_present_without_dry_run_exits_0_and_changes_nothing(tmp_path):
    proc, calls = _run(tmp_path, BI_CONFIG, BTMGMT_NONE, "")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not [c for c in calls if MUTATING.search(c)]


@pytestmark_adapters
def test_only_one_of_two_adapters_present_still_exits_0(tmp_path):
    one = BTMGMT_TWO.split("hci1:")[0].replace("2 items", "1 items")
    proc, _ = _run(
        tmp_path, BI_CONFIG, one, "Controller AA:BB:CC:00:00:01 srcpi [default]\n", "--dry-run"
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "AA:BB:CC:00:00:02" in out  # l'adaptateur manquant est signale


@pytestmark_adapters
def test_missing_config_file_fails_cleanly(tmp_path):
    bindir, _ = _fake_bin(tmp_path, BTMGMT_TWO)
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--config", str(tmp_path / "absent.yaml"), "--dry-run"],
        capture_output=True,
        text=True,
        env=_env(bindir),
        check=False,
        timeout=30,
    )
    assert proc.returncode == 2
    assert "absent.yaml" in proc.stdout + proc.stderr


@pytestmark_adapters
def test_dry_run_plans_class_alias_and_closes_pairing(tmp_path):
    proc, _ = _run(tmp_path, BI_CONFIG, BTMGMT_TWO, "", "--dry-run")
    planned = [ln for ln in proc.stdout.splitlines() if ln.startswith("DRY-RUN:")]
    joined = "\n".join(planned)
    assert "-i 0" in joined and "-i 1" in joined
    assert re.search(r"class", joined) and re.search(r"discov no", joined)
    assert re.search(r"Alias s .?btmux-src", joined) and re.search(r"Alias s .?btmux\b", joined)


@pytestmark_adapters
def test_sources_and_headsets_get_different_classes(tmp_path):
    proc, _ = _run(tmp_path, BI_CONFIG, BTMGMT_TWO, "", "--dry-run")
    out = proc.stdout
    src_line = next(ln for ln in out.splitlines() if "-i 0" in ln and "class" in ln)
    hp_line = next(ln for ln in out.splitlines() if "-i 1" in ln and "class" in ln)
    assert src_line.split("class", 1)[1].strip() != hp_line.split("class", 1)[1].strip()


@pytestmark_adapters
def test_invalid_config_exits_2(tmp_path):
    bad = {"adapters": [{"mac": "zz", "name": "x", "roles": ["sources"]}]}
    proc, _ = _run(tmp_path, bad, BTMGMT_TWO, "", "--dry-run")
    assert proc.returncode == 2


@pytestmark_adapters
def test_unknown_option_exits_2(tmp_path):
    bindir, _ = _fake_bin(tmp_path, BTMGMT_TWO)
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--bogus"],
        capture_output=True,
        text=True,
        env=_env(bindir),
        check=False,
        timeout=30,
    )
    assert proc.returncode == 2
