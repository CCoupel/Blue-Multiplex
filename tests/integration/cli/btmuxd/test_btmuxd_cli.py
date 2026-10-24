"""LOT-1 / cli — btmuxd --config et --check-config (codes 0/2/3), contrat config-schema."""

from __future__ import annotations

import os
import subprocess
import sys

from specsupport import output_of


def test_check_config_valid_exits_0_and_reports_path(run_btmuxd_cfg, write_config, valid_config):
    path = write_config(valid_config)
    proc = run_btmuxd_cfg("--config", str(path), "--check-config")
    assert proc.returncode == 0, output_of(proc)
    assert f"config OK: {path}" in output_of(proc)


def test_check_config_missing_file_exits_2(run_btmuxd_cfg, tmp_path):
    missing = tmp_path / "nope.yaml"
    proc = run_btmuxd_cfg("--config", str(missing), "--check-config")
    assert proc.returncode == 2
    assert f"config: cannot read '{missing}'" in output_of(proc)


def test_check_config_malformed_yaml_exits_2(run_btmuxd_cfg, write_config):
    path = write_config("adapters: [unclosed\n  - : :\n")
    proc = run_btmuxd_cfg("--config", str(path), "--check-config")
    assert proc.returncode == 2
    assert "config: cannot read" in output_of(proc)


def test_check_config_invalid_reports_every_error_one_per_line(
    run_btmuxd_cfg, write_config, valid_config
):
    valid_config["adapters"][0]["mac"] = "zz"
    valid_config["devices"][0]["kind"] = "speaker"
    proc = run_btmuxd_cfg("--config", str(write_config(valid_config)), "--check-config")
    assert proc.returncode == 2
    lines = [ln for ln in output_of(proc).splitlines() if ln.startswith("config:")]
    assert any("adapters[0].mac" in ln for ln in lines)
    assert any("devices[0].kind" in ln for ln in lines)
    assert len(lines) >= 2


def test_check_config_unknown_key_exits_2(run_btmuxd_cfg, write_config, valid_config):
    valid_config["bogus"] = True
    proc = run_btmuxd_cfg("--config", str(write_config(valid_config)), "--check-config")
    assert proc.returncode == 2
    assert "config: unknown key 'bogus'" in output_of(proc)


def test_without_check_config_without_bluez_exits_3(write_config, valid_config, tmp_path):
    """Contrat (CHANGED v0.2.0, #20) : `btmuxd --config` se connecte a BlueZ.

    Adaptateur introuvable apres BTMUX_ADAPTER_WAIT s (defaut 30) -> code 3, API non demarree.
    Le maintien en vie (SIGTERM -> 0) avec un bus simule est couvert par tests/unit/ (FakeBus) et
    par tests/hardware/bluez/pairing sur le Pi ; la CI n'a pas de BlueZ.
    """
    code = "import sys; from btmux.cli.btmuxd import main; sys.exit(main())"
    proc = subprocess.run(
        [sys.executable, "-c", code, "--config", str(write_config(valid_config))],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "BTMUX_ADAPTER_WAIT": "1",
            "DBUS_SYSTEM_BUS_ADDRESS": f"unix:path={tmp_path}/no-bus",  # jamais de vrai BlueZ
        },
        timeout=60,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert "adapter_not_found" in out


def test_without_check_config_invalid_config_exits_2(run_btmuxd_cfg, write_config, valid_config):
    valid_config["adapters"][0]["mac"] = "zz"
    proc = run_btmuxd_cfg("--config", str(write_config(valid_config)))
    assert proc.returncode == 2
    assert "adapters[0].mac" in output_of(proc)
    assert "started" not in output_of(proc)  # config invalide : le daemon ne demarre pas


def test_default_config_path_is_etc_btmux_config_yaml(run_btmuxd_cfg):
    from pathlib import Path

    import pytest

    if Path("/etc/btmux/config.yaml").exists():
        pytest.skip("/etc/btmux/config.yaml existe sur cette machine")
    proc = run_btmuxd_cfg("--check-config")
    assert proc.returncode == 2
    assert "/etc/btmux/config.yaml" in output_of(proc)
