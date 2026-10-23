from pathlib import Path
from typing import Any

import pytest

from btmux.cli import btmuxd
from btmux.config import ConfigError, load_config, parse_config

VALID: dict[str, Any] = {
    "adapters": [{"mac": "aa:bb:cc:00:00:01", "name": "btmux", "roles": ["sources", "headsets"]}],
    "devices": [
        {"mac": "11:22:33:44:55:01", "alias": "pc", "kind": "source"},
        {"mac": "11:22:33:44:55:02", "alias": "xm5", "kind": "headset"},
    ],
    "default_routes": {"xm5": "pc"},
}


def _copy() -> dict[str, Any]:
    import copy

    return copy.deepcopy(VALID)


def _errors(data: Any) -> list[str]:
    with pytest.raises(ConfigError) as exc:
        parse_config(data)
    return exc.value.errors


def test_valid_defaults() -> None:
    cfg = parse_config(_copy())
    assert cfg.adapters[0].mac == "AA:BB:CC:00:00:01"
    assert cfg.sources[0].priority == 100
    assert cfg.api.listen == "0.0.0.0:8088"
    assert cfg.adapter_for_role("sources").name == "btmux"


def test_adapter_for_role_missing() -> None:
    cfg = parse_config(_copy())
    object.__setattr__(cfg.adapters[0], "roles", ("sources",))
    with pytest.raises(LookupError):
        cfg.adapter_for_role("headsets")


def test_top_level_not_mapping() -> None:
    assert "expected a YAML mapping" in _errors([1])[0]


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda d: d.update(adapters={"a": 1}), "adapters: expected a non-empty list"),
        (lambda d: d["adapters"].__setitem__(0, 3), "adapters[0]: expected a mapping"),
        (lambda d: d["adapters"][0].pop("mac"), "adapters[0].mac: required"),
        (lambda d: d["adapters"][0].update(roles=["x"]), "unknown role 'x'"),
        (lambda d: d["adapters"][0].update(roles=["sources", "sources"]), "duplicate role"),
        (lambda d: d.update(devices=3), "devices: expected a list"),
        (lambda d: d["devices"].__setitem__(0, 3), "devices[0]: expected a mapping"),
        (lambda d: d["devices"][0].update(priority=-1), "devices[0].priority"),
        (lambda d: d["devices"][0].update(priority=True), "devices[0].priority"),
        (lambda d: d.update(default_routes=[1]), "default_routes: expected a mapping"),
        (lambda d: d.update(default_routes={"xm5": "nope"}), "unknown source alias 'nope'"),
        (lambda d: d.update(api=1), "api: expected a mapping"),
        (lambda d: d.update(api={"token_file": "rel"}), "api.token_file"),
        (lambda d: d.update(api={"listen": 5}), "api.listen"),
        (lambda d: d.update(mqtt=1), "mqtt: expected a mapping"),
        (lambda d: d.update(mqtt={"enabled": "yes"}), "mqtt.enabled"),
        (lambda d: d["devices"][1].update(mac="x"), "devices[1].mac"),
    ],
)
def test_invalid(mutate: Any, fragment: str) -> None:
    data = _copy()
    mutate(data)
    assert any(fragment in e for e in _errors(data))


def test_none_sections_accepted() -> None:
    data = _copy()
    data.update(devices=None, default_routes=None, api=None, mqtt=None)
    assert parse_config(data).devices == ()


def test_load_config_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_bytes(b"\xff\xfe")
    for path in (bad, tmp_path / "absent.yaml", tmp_path):
        with pytest.raises(ConfigError) as exc:
            load_config(path)
        assert "cannot read" in exc.value.errors[0]


def test_cli_check_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "adapters:\n  - {mac: 'AA:BB:CC:00:00:01', name: n, roles: [sources, headsets]}\n"
    )
    assert btmuxd.main(["--config", str(cfg), "--check-config"]) == 0
    assert f"config OK: {cfg}" in capsys.readouterr().out


@pytest.mark.parametrize("routes", [{"xm5": ["pc"]}, {"xm5": {"a": 1}}, {1: "pc"}, {("a",): "pc"}])
def test_default_routes_non_string_is_error_not_traceback(routes: Any) -> None:
    data = _copy()
    data["default_routes"] = routes
    assert any(e.startswith("config: default_routes:") for e in _errors(data))


# --- v0.2.0 : bi-adaptateur (V4 levée à 2) et clé pairing (V11) ---
def _bi() -> dict[str, Any]:
    data = _copy()
    data["adapters"] = [
        {"mac": "AA:BB:CC:00:00:01", "name": "btmux", "roles": ["sources"]},
        {"mac": "AA:BB:CC:00:00:02", "name": "btmux-hp", "roles": ["headsets"]},
    ]
    return data


def test_two_adapters_with_split_roles_accepted() -> None:
    cfg = parse_config(_bi())
    assert [a.mac for a in cfg.adapters] == ["AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02"]
    assert cfg.adapter_for_role("sources").name == "btmux"
    assert cfg.adapter_for_role("headsets").name == "btmux-hp"


def test_three_adapters_refused_with_contract_message() -> None:
    data = _bi()
    data["adapters"].append({"mac": "AA:BB:CC:00:00:03", "name": "x", "roles": ["sources"]})
    errors = _errors(data)
    assert "config: at most 2 adapters are supported (found 3)" in errors


def test_two_adapters_same_role_is_a_v3_error() -> None:
    data = _bi()
    data["adapters"][1]["roles"] = ["sources"]
    errors = _errors(data)
    assert any(
        "role 'headsets' must be provided by exactly one adapter (found 0)" in e for e in errors
    )
    assert any(
        "role 'sources' must be provided by exactly one adapter (found 2)" in e for e in errors
    )


def test_pairing_defaults_and_values() -> None:
    cfg = parse_config(_copy())
    assert cfg.pairing.default_duration == 60 and cfg.pairing.accept_incoming is True
    data = _copy()
    data["pairing"] = {"default_duration": 300, "accept_incoming": False}
    cfg = parse_config(data)
    assert cfg.pairing.default_duration == 300 and cfg.pairing.accept_incoming is False


@pytest.mark.parametrize("duration", [0, 301, -5, "60", 1.5, True, None])
def test_pairing_invalid_duration(duration: Any) -> None:
    data = _copy()
    data["pairing"] = {"default_duration": duration}
    assert any("pairing.default_duration" in e for e in _errors(data))


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_pairing_invalid_accept_incoming(value: Any) -> None:
    data = _copy()
    data["pairing"] = {"accept_incoming": value}
    assert any("pairing.accept_incoming" in e for e in _errors(data))


def test_pairing_unknown_key_and_wrong_type() -> None:
    data = _copy()
    data["pairing"] = {"timeout": 5}
    assert any("unknown key 'timeout' in pairing" in e for e in _errors(data))
    data["pairing"] = [1]
    assert any("pairing: expected a mapping" in e for e in _errors(data))


def test_pairing_none_accepted() -> None:
    data = _copy()
    data["pairing"] = None
    assert parse_config(data).pairing.default_duration == 60


def test_example_config_is_bi_adapter(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    cfg = load_config(root / "config" / "config.example.yaml")
    assert len(cfg.adapters) == 2
    assert cfg.adapter_for_role("sources") is not cfg.adapter_for_role("headsets")
