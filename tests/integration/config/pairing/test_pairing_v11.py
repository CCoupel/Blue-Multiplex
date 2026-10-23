"""config — cle optionnelle `pairing` (V11, v0.2.0 #20/#21) : contracts/config-schema.md."""

from __future__ import annotations

import pytest
from specsupport import assert_has_error


def test_pairing_absent_uses_defaults(load, valid_config):
    cfg = load(valid_config)
    assert cfg.pairing.default_duration == 60
    assert cfg.pairing.accept_incoming is True


def test_pairing_partial_keeps_other_default(load, valid_config):
    valid_config["pairing"] = {"default_duration": 120}
    cfg = load(valid_config)
    assert cfg.pairing.default_duration == 120
    assert cfg.pairing.accept_incoming is True


def test_pairing_accept_incoming_false(load, valid_config):
    valid_config["pairing"] = {"accept_incoming": False}
    cfg = load(valid_config)
    assert cfg.pairing.accept_incoming is False
    assert cfg.pairing.default_duration == 60


@pytest.mark.parametrize("ok", [1, 60, 300])
def test_v11_duration_bounds_accepted(load, valid_config, ok):
    valid_config["pairing"] = {"default_duration": ok}
    assert load(valid_config).pairing.default_duration == ok


@pytest.mark.parametrize("bad", [0, -1, 301, 1000, 1.5, "abc", None])
def test_v11_duration_out_of_range_or_wrong_type_rejected(errors_of, valid_config, bad):
    valid_config["pairing"] = {"default_duration": bad}
    assert_has_error(errors_of(valid_config), "pairing.default_duration")


@pytest.mark.parametrize("bad", ["maybe", "nope", 2, None])
def test_v11_accept_incoming_must_be_boolean(errors_of, valid_config, bad):
    valid_config["pairing"] = {"accept_incoming": bad}
    assert_has_error(errors_of(valid_config), "pairing.accept_incoming")


def test_v9_unknown_key_in_pairing_rejected(errors_of, valid_config):
    valid_config["pairing"] = {"default_duration": 60, "pin": "0000"}
    assert_has_error(errors_of(valid_config), "unknown key 'pin'")


def test_pairing_must_be_a_mapping(errors_of, valid_config):
    valid_config["pairing"] = 60
    assert_has_error(errors_of(valid_config), "pairing")


def test_check_config_cli_rejects_invalid_pairing(run_btmuxd_cfg, write_config, valid_config):
    valid_config["pairing"] = {"default_duration": 301}
    proc = run_btmuxd_cfg("--config", str(write_config(valid_config)), "--check-config")
    assert proc.returncode == 2
    assert "pairing.default_duration" in (proc.stdout + proc.stderr)
