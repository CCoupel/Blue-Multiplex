"""config — forme bi-adaptateur (#14) : V2/V3/V4 version v0.2.0 (contracts/config-schema.md)."""

from __future__ import annotations

import pytest
from specsupport import assert_has_error

SRC = {"mac": "AA:BB:CC:00:00:01", "name": "btmux", "roles": ["sources"]}
HP = {"mac": "AA:BB:CC:00:00:02", "name": "btmux-src", "roles": ["headsets"]}
BOTH_A = {"mac": "AA:BB:CC:00:00:01", "name": "a", "roles": ["sources", "headsets"]}
BOTH_B = {"mac": "AA:BB:CC:00:00:02", "name": "b", "roles": ["sources", "headsets"]}


def test_mono_two_roles_accepted(load, valid_config):
    cfg = load(valid_config)
    assert cfg.adapter_for_role("sources").mac == cfg.adapter_for_role("headsets").mac


def test_bi_adapter_accepted_and_roles_resolved(load, valid_config):
    valid_config["adapters"] = [SRC, HP]
    cfg = load(valid_config)
    assert [a.mac for a in cfg.adapters] == ["AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02"]
    assert cfg.adapter_for_role("sources").name == "btmux"
    assert cfg.adapter_for_role("headsets").name == "btmux-src"


def test_bi_adapter_keeps_file_order(load, valid_config):
    valid_config["adapters"] = [HP, SRC]
    cfg = load(valid_config)
    assert [a.name for a in cfg.adapters] == ["btmux-src", "btmux"]
    assert cfg.adapter_for_role("sources").name == "btmux"


def test_bi_adapter_mac_normalized_to_uppercase(load, valid_config):
    valid_config["adapters"] = [dict(SRC, mac="aa:bb:cc:00:00:01"), HP]
    assert load(valid_config).adapters[0].mac == "AA:BB:CC:00:00:01"


def test_v3_duplicated_roles_across_two_adapters_rejected(errors_of, valid_config):
    valid_config["adapters"] = [BOTH_A, BOTH_B]
    errs = errors_of(valid_config)
    assert_has_error(errs, "role 'sources' must be provided by exactly one adapter (found 2)")
    assert_has_error(errs, "role 'headsets' must be provided by exactly one adapter (found 2)")


def test_v3_same_role_on_both_adapters_rejected(errors_of, valid_config):
    valid_config["adapters"] = [SRC, dict(HP, roles=["sources"])]
    errs = errors_of(valid_config)
    assert_has_error(errs, "role 'sources' must be provided by exactly one adapter (found 2)")
    assert_has_error(errs, "role 'headsets' must be provided by exactly one adapter (found 0)")


def test_v2_zero_adapters_rejected(errors_of, valid_config):
    valid_config["adapters"] = []
    assert_has_error(errors_of(valid_config), "adapters")


@pytest.mark.parametrize("extra_count", [1, 2])
def test_v4_more_than_two_adapters_rejected(errors_of, valid_config, extra_count):
    extras = [
        {"mac": f"AA:BB:CC:00:00:0{3 + i}", "name": f"x{i}", "roles": ["sources"]}
        for i in range(extra_count)
    ]
    valid_config["adapters"] = [SRC, HP, *extras]
    assert_has_error(
        errors_of(valid_config), f"at most 2 adapters are supported (found {2 + extra_count})"
    )


@pytest.mark.xfail(
    reason="ecart a trancher : V4 (validation croisee) non collectee avec une erreur de champ "
    "(contrat : « toutes les erreurs sont collectees »)",
    strict=False,
)
def test_v4_error_is_collected_with_other_errors(errors_of, valid_config):
    valid_config["adapters"] = [SRC, HP, {"mac": "bad", "name": "x", "roles": ["sources"]}]
    errs = errors_of(valid_config)
    assert_has_error(errs, "at most 2 adapters are supported")
    assert_has_error(errs, "adapters[2].mac")


def test_devices_and_routes_work_with_bi_adapter(load, valid_config):
    valid_config["adapters"] = [SRC, HP]
    cfg = load(valid_config)
    assert [d.alias for d in cfg.sources] == ["pc-pro", "tel-perso"]
    assert [d.alias for d in cfg.headsets] == ["xm5"]
