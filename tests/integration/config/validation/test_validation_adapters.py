"""LOT-1 / config — regles V1 (MAC), V2 (adaptateurs, roles), V3 (role unique), V10 (fichier).

Contrat : contracts/config-schema.md. Skippes tant que `btmux.config` (T1.5) est absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from specsupport import assert_has_error

FIXTURES = Path(__file__).parent / "fixtures"


# --- configuration valide ---------------------------------------------------------------------
def test_valid_full_fixture_loads_and_normalizes_mac(cfgmod):
    cfg = cfgmod.load_config(FIXTURES / "valid_full.yaml")
    assert cfg.adapters[0].mac == "AA:BB:CC:00:00:01"
    assert cfg.adapter_for_role("headsets").mac == "AA:BB:CC:00:00:01"
    assert cfg.adapter_for_role("sources").name == "btmux"


def test_minimal_valid_config_without_devices(load, valid_config):
    valid_config["devices"] = []
    valid_config.pop("default_routes")
    cfg = load(valid_config)
    assert cfg.sources == [] and cfg.headsets == []


# --- V1 : MAC ---------------------------------------------------------------------------------
def test_v1_adapter_mac_is_uppercased(load, valid_config):
    valid_config["adapters"][0]["mac"] = "aa:bb:cc:dd:ee:ff"
    assert load(valid_config).adapters[0].mac == "AA:BB:CC:DD:EE:FF"


def test_v1_device_mac_is_uppercased(load, valid_config):
    valid_config["devices"][0]["mac"] = "aa:bb:cc:dd:ee:ff"
    assert any(d.mac == "AA:BB:CC:DD:EE:FF" for d in load(valid_config).sources)


@pytest.mark.parametrize(
    "bad",
    [
        "AA:BB:CC:00:00",
        "AA-BB-CC-00-00-01",
        "GG:BB:CC:00:00:01",
        "AABBCC000001",
        "",
        "hci0",
        "AA:BB:CC:00:00:01:02",
    ],
)
def test_v1_invalid_adapter_mac_rejected(errors_of, valid_config, bad):
    valid_config["adapters"][0]["mac"] = bad
    assert_has_error(errors_of(valid_config), "adapters[0].mac: invalid MAC address")


def test_v1_invalid_device_mac_rejected(errors_of, valid_config):
    valid_config["devices"][1]["mac"] = "not-a-mac"
    assert_has_error(errors_of(valid_config), "devices[1].mac: invalid MAC address 'not-a-mac'")


def test_v1_missing_adapter_mac_rejected(errors_of, valid_config):
    del valid_config["adapters"][0]["mac"]
    assert_has_error(errors_of(valid_config), "adapters[0].mac")


# --- V2 : adaptateurs et roles ----------------------------------------------------------------
def test_v2_empty_adapters_accepted_since_23(load, valid_config):
    valid_config["adapters"] = []
    assert load(valid_config).adapters == ()


def test_v2_missing_adapters_rejected(errors_of, valid_config):
    del valid_config["adapters"]
    assert_has_error(errors_of(valid_config), "adapters")


def test_v2_empty_roles_rejected(errors_of, valid_config):
    valid_config["adapters"][0]["roles"] = []
    assert_has_error(errors_of(valid_config), "adapters[0].roles")


def test_v2_missing_roles_rejected(errors_of, valid_config):
    del valid_config["adapters"][0]["roles"]
    assert_has_error(errors_of(valid_config), "adapters[0].roles")


def test_v2_unknown_role_rejected(errors_of, valid_config):
    valid_config["adapters"][0]["roles"] = ["sources", "speakers"]
    assert_has_error(errors_of(valid_config), "adapters[0].roles: unknown role 'speakers'")


def test_v2_duplicate_role_rejected(errors_of, valid_config):
    valid_config["adapters"][0]["roles"] = ["sources", "sources", "headsets"]
    assert_has_error(errors_of(valid_config), "adapters[0].roles")


def test_v2_missing_name_rejected(errors_of, valid_config):
    del valid_config["adapters"][0]["name"]
    assert_has_error(errors_of(valid_config), "adapters[0].name")


def test_v2_empty_name_rejected(errors_of, valid_config):
    valid_config["adapters"][0]["name"] = ""
    assert_has_error(errors_of(valid_config), "adapters[0].name")


def test_v2_name_248_bytes_utf8_accepted(load, valid_config):
    valid_config["adapters"][0]["name"] = "é" * 124  # 248 octets UTF-8
    assert len(load(valid_config).adapters[0].name.encode("utf-8")) == 248


def test_v2_name_over_248_bytes_rejected(errors_of, valid_config):
    valid_config["adapters"][0]["name"] = "é" * 125  # 250 octets UTF-8 (mais 125 caracteres)
    assert_has_error(errors_of(valid_config), "adapters[0].name")


# --- V3 : chaque role porte par exactement un adaptateur --------------------------------------
@pytest.mark.parametrize("missing", ["headsets", "sources"])
def test_v3_role_provided_by_no_adapter_accepted_since_23(load, valid_config, missing):
    """#23 : un rôle non couvert est admis (daemon en état `role_unassigned`)."""
    present = "sources" if missing == "headsets" else "headsets"
    valid_config["adapters"][0]["roles"] = [present]
    cfg = load(valid_config)
    with pytest.raises(LookupError):
        cfg.adapter_for_role(missing)


def test_v3_role_provided_by_two_adapters_rejected(errors_of, valid_config):
    valid_config["adapters"].append(
        {"mac": "AA:BB:CC:00:00:02", "name": "btmux2", "roles": ["headsets"]}
    )
    errs = errors_of(valid_config)
    assert_has_error(errs, "role 'headsets' must be provided by at most one adapter (found 2)")


# --- V10 : fichier absent / YAML invalide -----------------------------------------------------
def test_v10_missing_file_rejected(cfgmod, tmp_path):
    missing = tmp_path / "absent.yaml"
    with pytest.raises(cfgmod.ConfigError) as exc:
        cfgmod.load_config(missing)
    assert any(f"cannot read '{missing}'" in e for e in exc.value.errors)


def test_v10_malformed_yaml_rejected(cfgmod):
    with pytest.raises(cfgmod.ConfigError) as exc:
        cfgmod.load_config(FIXTURES / "malformed.yaml")
    assert any("cannot read" in e for e in exc.value.errors)


def test_v10_directory_instead_of_file_rejected(cfgmod, tmp_path):
    with pytest.raises(cfgmod.ConfigError) as exc:
        cfgmod.load_config(tmp_path)
    assert any("cannot read" in e for e in exc.value.errors)


@pytest.mark.parametrize("content", ["", "- just\n- a list\n", "42\n"])
def test_v10_non_mapping_document_rejected(cfgmod, write_config, content):
    with pytest.raises(cfgmod.ConfigError) as exc:
        cfgmod.load_config(write_config(content))
    assert exc.value.errors


# --- collecte de toutes les erreurs -----------------------------------------------------------
def test_all_errors_are_collected_not_first_only(errors_of, valid_config):
    valid_config["adapters"][0]["mac"] = "zz"
    valid_config["devices"][0]["alias"] = "BAD ALIAS"
    valid_config["api"] = {"listen": "nope"}
    errs = errors_of(valid_config)
    assert_has_error(errs, "adapters[0].mac")
    assert_has_error(errs, "devices[0].alias")
    assert_has_error(errs, "api.listen")
    assert len(errs) >= 3


def test_errors_are_single_line_messages(errors_of, valid_config):
    valid_config["adapters"][0]["mac"] = "zz"
    valid_config["devices"][0]["kind"] = "speaker"
    assert all("\n" not in e for e in errors_of(valid_config))
