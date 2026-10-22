"""LOT-1 / config — regles V5 (unicite, alias), V6 (kind, priority), V7 (routes), accesseurs."""

from __future__ import annotations

import pytest
from specsupport import assert_has_error


# --- V5 ---------------------------------------------------------------------------------------
def test_v5_duplicate_alias_rejected(errors_of, valid_config):
    valid_config["devices"][1]["alias"] = "xm5"
    valid_config["devices"][2]["alias"] = "xm5"
    assert_has_error(errors_of(valid_config), "devices: duplicate alias 'xm5'")


def test_v5_duplicate_mac_rejected(errors_of, valid_config):
    valid_config["devices"][1]["mac"] = valid_config["devices"][0]["mac"].lower()
    assert_has_error(errors_of(valid_config), "devices: duplicate mac")


@pytest.mark.parametrize("bad", ["PC", "-pc", "pc_pro", "pc pro", "", "a" * 33, "é"])
def test_v5_invalid_alias_rejected(errors_of, valid_config, bad):
    valid_config["devices"][0]["alias"] = bad
    valid_config["default_routes"] = {}
    assert_has_error(errors_of(valid_config), "devices[0].alias")


@pytest.mark.parametrize("good", ["a", "0pc", "pc-pro", "a" * 32, "x-1-y"])
def test_v5_valid_alias_accepted(load, valid_config, good):
    valid_config["devices"][0]["alias"] = good
    valid_config["default_routes"] = {}
    assert any(d.alias == good for d in load(valid_config).sources)


def test_v5_missing_alias_rejected(errors_of, valid_config):
    del valid_config["devices"][0]["alias"]
    assert_has_error(errors_of(valid_config), "devices[0].alias")


# --- V6 ---------------------------------------------------------------------------------------
def test_v6_invalid_kind_rejected(errors_of, valid_config):
    valid_config["devices"][0]["kind"] = "speaker"
    valid_config["default_routes"] = {}
    assert_has_error(errors_of(valid_config), "devices[0].kind")


def test_v6_missing_kind_rejected(errors_of, valid_config):
    del valid_config["devices"][0]["kind"]
    assert_has_error(errors_of(valid_config), "devices[0].kind")


def test_v6_priority_on_headset_rejected(errors_of, valid_config):
    valid_config["devices"][2]["priority"] = 5
    assert_has_error(errors_of(valid_config), "devices[2].priority: only allowed for kind 'source'")


@pytest.mark.parametrize("bad", [-1, "high", 1.5, None])
def test_v6_invalid_priority_rejected(errors_of, valid_config, bad):
    valid_config["devices"][0]["priority"] = bad
    assert_has_error(errors_of(valid_config), "devices[0].priority")


def test_v6_priority_zero_accepted(load, valid_config):
    valid_config["devices"][0]["priority"] = 0
    assert load(valid_config).sources[0].priority == 0


def test_v6_priority_defaults_to_100(load, valid_config):
    del valid_config["devices"][0]["priority"]
    cfg = load(valid_config)
    assert next(d for d in cfg.sources if d.alias == "pc-pro").priority == 100


# --- V7 ---------------------------------------------------------------------------------------
def test_v7_unknown_headset_alias_rejected(errors_of, valid_config):
    valid_config["default_routes"] = {"ghost": "pc-pro"}
    assert_has_error(errors_of(valid_config), "default_routes: unknown headset alias 'ghost'")


def test_v7_key_must_be_a_headset_not_a_source(errors_of, valid_config):
    valid_config["default_routes"] = {"pc-pro": "tel-perso"}
    assert_has_error(errors_of(valid_config), "default_routes: unknown headset alias 'pc-pro'")


def test_v7_unknown_source_alias_rejected(errors_of, valid_config):
    valid_config["default_routes"] = {"xm5": "ghost"}
    assert_has_error(errors_of(valid_config), "default_routes")


def test_v7_value_must_be_a_source_not_a_headset(errors_of, valid_config):
    valid_config["default_routes"] = {"xm5": "xm5"}
    assert_has_error(errors_of(valid_config), "default_routes")


def test_v7_empty_or_absent_default_routes_accepted(load, valid_config):
    valid_config["default_routes"] = {}
    load(valid_config)
    del valid_config["default_routes"]
    load(valid_config)


# --- accesseurs -------------------------------------------------------------------------------
def test_sources_sorted_by_priority_then_alias(load, valid_config):
    valid_config["devices"] = [
        {"mac": "11:22:33:44:55:01", "alias": "zeta", "kind": "source", "priority": 10},
        {"mac": "11:22:33:44:55:02", "alias": "alpha", "kind": "source", "priority": 10},
        {"mac": "11:22:33:44:55:03", "alias": "first", "kind": "source", "priority": 1},
        {"mac": "11:22:33:44:55:04", "alias": "xm5", "kind": "headset"},
    ]
    valid_config["default_routes"] = {}
    assert [d.alias for d in load(valid_config).sources] == ["first", "alpha", "zeta"]


def test_headsets_sorted_by_alias(load, valid_config):
    valid_config["devices"] = [
        {"mac": "11:22:33:44:55:01", "alias": "wh1000", "kind": "headset"},
        {"mac": "11:22:33:44:55:02", "alias": "airpods", "kind": "headset"},
    ]
    valid_config["default_routes"] = {}
    assert [d.alias for d in load(valid_config).headsets] == ["airpods", "wh1000"]
