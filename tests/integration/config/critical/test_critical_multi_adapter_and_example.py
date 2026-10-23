"""config — scenarios critical : V4 (max 2 adaptateurs, CHANGED v0.2.0) et exemple valide.

Reecriture justifiee par contracts/CHANGELOG.md [20261023] : V4 « max 1 » devient « max 2 » ;
le test critical « multi-adaptateur refuse » devient « 3 adaptateurs refuses » (+ bi accepte).
"""

from __future__ import annotations

import pytest
from specsupport import REPO_ROOT, XFAIL_T11, assert_has_error, output_of

EXAMPLE = REPO_ROOT / "config" / "config.example.yaml"

TWO_ADAPTERS = [
    {"mac": "AA:BB:CC:00:00:01", "name": "btmux", "roles": ["sources"]},
    {"mac": "AA:BB:CC:00:00:02", "name": "btmux-src", "roles": ["headsets"]},
]
THIRD = {"mac": "AA:BB:CC:00:00:03", "name": "btmux-3", "roles": ["sources"]}


@pytest.mark.critical
@XFAIL_T11
def test_v4_three_adapters_rejected(errors_of, valid_config):
    valid_config["adapters"] = TWO_ADAPTERS + [THIRD]
    assert_has_error(errors_of(valid_config), "at most 2 adapters are supported (found 3)")


@pytest.mark.critical
@XFAIL_T11
def test_v4_two_adapters_split_roles_accepted(load, valid_config):
    valid_config["adapters"] = TWO_ADAPTERS
    cfg = load(valid_config)
    assert len(cfg.adapters) == 2
    assert cfg.adapter_for_role("sources").mac == "AA:BB:CC:00:00:01"
    assert cfg.adapter_for_role("headsets").mac == "AA:BB:CC:00:00:02"


@pytest.mark.critical
def test_v4_mono_adapter_still_accepted(load, valid_config):
    assert len(load(valid_config).adapters) == 1


@pytest.mark.critical
@XFAIL_T11
def test_check_config_cli_refuses_three_adapters_with_code_2(
    run_btmuxd_cfg, write_config, valid_config
):
    valid_config["adapters"] = TWO_ADAPTERS + [THIRD]
    proc = run_btmuxd_cfg("--config", str(write_config(valid_config)), "--check-config")
    assert proc.returncode == 2
    assert "config: at most 2 adapters are supported" in output_of(proc)


@pytest.mark.critical
@XFAIL_T11
def test_check_config_cli_accepts_bi_adapter_with_code_0(
    run_btmuxd_cfg, write_config, valid_config
):
    valid_config["adapters"] = TWO_ADAPTERS
    path = write_config(valid_config)
    proc = run_btmuxd_cfg("--config", str(path), "--check-config")
    assert proc.returncode == 0, output_of(proc)
    assert f"config OK: {path}" in output_of(proc)


@pytest.mark.critical
@pytest.mark.skipif(not EXAMPLE.exists(), reason="config/config.example.yaml absent")
def test_repo_config_example_is_valid(cfgmod):
    """Exemple du depot : 1 ou 2 adaptateurs, et les deux roles sont couverts."""
    cfg = cfgmod.load_config(EXAMPLE)
    assert 1 <= len(cfg.adapters) <= 2
    assert {r for a in cfg.adapters for r in a.roles} == {"sources", "headsets"}


@pytest.mark.critical
@pytest.mark.skipif(not EXAMPLE.exists(), reason="config/config.example.yaml absent")
def test_repo_config_example_passes_check_config_cli(run_btmuxd_cfg):
    proc = run_btmuxd_cfg("--config", str(EXAMPLE), "--check-config")
    assert proc.returncode == 0, output_of(proc)
    assert "config OK" in output_of(proc)
