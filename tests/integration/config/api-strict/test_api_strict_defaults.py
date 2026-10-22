"""LOT-1 / config — regles V8 (api), V9 (cles inconnues, strict) et valeurs par defaut."""

from __future__ import annotations

import pytest
from specsupport import assert_has_error


# --- defauts ----------------------------------------------------------------------------------
def test_defaults_when_api_and_mqtt_absent(load, valid_config):
    cfg = load(valid_config)
    assert cfg.api.listen == "0.0.0.0:8088"
    assert str(cfg.api.token_file) == "/etc/btmux/token"
    assert cfg.mqtt.enabled is False


def test_api_partial_keeps_other_default(load, valid_config):
    valid_config["api"] = {"listen": "127.0.0.1:9000"}
    cfg = load(valid_config)
    assert cfg.api.listen == "127.0.0.1:9000"
    assert str(cfg.api.token_file) == "/etc/btmux/token"


# --- V8 ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad", ["8088", "host:0", "host:65536", "host:abc", ":8088", "", "host:-1", "a:b:c:80"]
)
def test_v8_invalid_listen_rejected(errors_of, valid_config, bad):
    valid_config["api"] = {"listen": bad}
    assert_has_error(errors_of(valid_config), "api.listen: expected host:port")


@pytest.mark.parametrize("good", ["127.0.0.1:1", "0.0.0.0:65535", "btmux.local:8088"])
def test_v8_valid_listen_accepted(load, valid_config, good):
    valid_config["api"] = {"listen": good}
    assert load(valid_config).api.listen == good


@pytest.mark.parametrize("bad", ["relative/token", "token", ""])
def test_v8_token_file_must_be_absolute(errors_of, valid_config, bad):
    valid_config["api"] = {"token_file": bad}
    assert_has_error(errors_of(valid_config), "api.token_file")


def test_v8_absolute_token_file_accepted(load, valid_config):
    valid_config["api"] = {"token_file": "/run/btmux/token"}
    assert str(load(valid_config).api.token_file) == "/run/btmux/token"


# --- V9 : strict ------------------------------------------------------------------------------
def test_v9_unknown_top_level_key_rejected(errors_of, valid_config):
    valid_config["foo"] = 1
    assert_has_error(errors_of(valid_config), "unknown key 'foo'")


def test_v9_unknown_key_in_device_rejected(errors_of, valid_config):
    valid_config["devices"][0]["colour"] = "red"
    assert_has_error(errors_of(valid_config), "unknown key 'colour' in devices[0]")


def test_v9_unknown_key_in_adapter_rejected(errors_of, valid_config):
    valid_config["adapters"][0]["hci"] = "hci0"
    assert_has_error(errors_of(valid_config), "unknown key 'hci'")


def test_v9_unknown_key_in_api_rejected(errors_of, valid_config):
    valid_config["api"] = {"listen": "0.0.0.0:8088", "tls": True}
    assert_has_error(errors_of(valid_config), "unknown key 'tls'")


def test_v9_unknown_key_in_mqtt_rejected(errors_of, valid_config):
    valid_config["mqtt"] = {"enabled": False, "broker": "x"}
    assert_has_error(errors_of(valid_config), "unknown key 'broker'")


def test_v9_legacy_cadrage_schema_rejected(errors_of, valid_config):
    """Le schema historique de cadrage.md (adapters: {sources:, headsets:}) est refuse."""
    valid_config["adapters"] = {"sources": "hci0", "headsets": "hci1"}
    assert errors_of(valid_config)
