"""LOT-1 / config — scenarios critical : refus multi-adaptateur (V4), exemple valide."""

from __future__ import annotations

import pytest
from specsupport import REPO_ROOT, assert_has_error, output_of

EXAMPLE = REPO_ROOT / "config" / "config.example.yaml"

TWO_ADAPTERS = [
    {"mac": "AA:BB:CC:00:00:01", "name": "btmux-src", "roles": ["sources"]},
    {"mac": "AA:BB:CC:00:00:02", "name": "btmux-hp", "roles": ["headsets"]},
]


@pytest.mark.critical
def test_v4_two_adapters_split_roles_rejected_in_v010(errors_of, valid_config):
    """Le schema accepte 2 adaptateurs (v0.2.0), la politique v0.1.0 les refuse."""
    valid_config["adapters"] = TWO_ADAPTERS
    errs = errors_of(valid_config)
    assert_has_error(
        errs, "multi-adapter configuration is planned for v0.2.0 (found 2 adapters, max 1)"
    )
    # Roles correctement repartis : V3 ne doit pas se declencher en plus.
    assert not any("must be provided by exactly one adapter" in e for e in errs)


@pytest.mark.critical
def test_v4_three_adapters_reports_count(errors_of, valid_config):
    valid_config["adapters"] = TWO_ADAPTERS + [
        {"mac": "AA:BB:CC:00:00:03", "name": "btmux-3", "roles": ["sources"]}
    ]
    assert_has_error(errors_of(valid_config), "found 3 adapters, max 1")


@pytest.mark.critical
def test_check_config_cli_refuses_multi_adapter_with_code_2(
    run_btmuxd_cfg, write_config, valid_config
):
    valid_config["adapters"] = TWO_ADAPTERS
    path = write_config(valid_config)
    proc = run_btmuxd_cfg("--config", str(path), "--check-config")
    assert proc.returncode == 2
    assert "config: multi-adapter configuration is planned for v0.2.0" in output_of(proc)


@pytest.mark.critical
@pytest.mark.skipif(
    not EXAMPLE.exists(),
    reason="config/config.example.yaml absent (T1.6) — test actif des sa livraison",
)
def test_repo_config_example_is_valid(cfgmod):
    cfg = cfgmod.load_config(EXAMPLE)
    assert len(cfg.adapters) == 1
    assert set(cfg.adapters[0].roles) == {"sources", "headsets"}


@pytest.mark.critical
@pytest.mark.skipif(not EXAMPLE.exists(), reason="config/config.example.yaml absent (T1.6)")
def test_repo_config_example_passes_check_config_cli(run_btmuxd_cfg):
    proc = run_btmuxd_cfg("--config", str(EXAMPLE), "--check-config")
    assert proc.returncode == 0, output_of(proc)
    assert "config OK" in output_of(proc)
