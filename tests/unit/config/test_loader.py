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
