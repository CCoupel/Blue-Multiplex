"""Chargement et validation (V1–V11) : toutes les erreurs sont collectées."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from btmux.config.models import (
    DEFAULT_LISTEN,
    DEFAULT_PRIORITY,
    DEFAULT_TOKEN_FILE,
    Adapter,
    ApiConfig,
    Config,
    ConfigError,
    Device,
    MqttConfig,
    PairingConfig,
)

PREFIX = "config: "
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
ROLES = ("sources", "headsets")
KINDS = ("source", "headset")
MAX_NAME_BYTES = 248
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
MAX_ADAPTERS = 2  # V4 (levée à 2 adaptateurs en v0.2.0)
PAIRING_DURATION_RANGE = (1, 300)

TOP_KEYS = {"adapters", "devices", "default_routes", "api", "mqtt", "pairing"}
ADAPTER_KEYS = {"mac", "name", "roles"}
DEVICE_KEYS = {"mac", "alias", "kind", "priority"}
API_KEYS = {"listen", "token_file"}
MQTT_KEYS = {"enabled"}
PAIRING_KEYS = {"default_duration", "accept_incoming"}


class _Errors:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, msg: str) -> None:
        self.items.append(PREFIX + msg.replace("\n", " "))

    def unknown_keys(self, data: Mapping[Any, Any], allowed: set[str], where: str | None) -> None:
        for key in data:
            if key not in allowed:
                self.add(f"unknown key '{key}'" + (f" in {where}" if where else ""))


def _mac(value: Any, where: str, err: _Errors) -> str | None:
    if isinstance(value, str) and MAC_RE.match(value):
        return value.upper()
    err.add(f"{where}.mac: invalid MAC address '{value}'")
    return None


def _adapters(raw: Any, err: _Errors) -> tuple[list[Adapter], list[list[str]], int]:
    """Retourne (adaptateurs valides, rôles valides de toutes les entrées, nombre d'entrées).

    Les règles croisées (V3, V4) portent sur toutes les entrées, même si l'une a une erreur de champ
    (« toutes les erreurs sont collectées »).
    """
    if not isinstance(raw, list) or not raw:
        err.add("adapters: expected a non-empty list")
        return [], [], 0
    result: list[Adapter] = []
    all_roles: list[list[str]] = []
    seen_macs: set[str] = set()
    for i, item in enumerate(raw):
        where = f"adapters[{i}]"
        if not isinstance(item, dict):
            err.add(f"{where}: expected a mapping")
            continue
        err.unknown_keys(item, ADAPTER_KEYS, where)
        mac = _mac(item["mac"], where, err) if "mac" in item else None
        if "mac" not in item:
            err.add(f"{where}.mac: required")
        name = item.get("name")
        name_ok = (
            isinstance(name, str)
            and 1 <= len(name.encode("utf-8")) <= MAX_NAME_BYTES
            and not any(unicodedata.category(c) in _FORBIDDEN_CATEGORIES for c in name)
        )
        if not name_ok:
            err.add(
                f"{where}.name: required, 1..{MAX_NAME_BYTES} bytes (UTF-8), no control characters"
            )
        roles = _roles(item.get("roles"), where, err)
        if roles:
            all_roles.append(roles)
        if mac is not None:
            if mac in seen_macs:
                err.add(f"{where}.mac: duplicate adapter mac '{mac}'")
            seen_macs.add(mac)
        if mac is not None and name_ok and roles:
            result.append(Adapter.model_validate({"mac": mac, "name": name, "roles": tuple(roles)}))
    return result, all_roles, len(raw)


def _roles(raw: Any, where: str, err: _Errors) -> list[str]:
    if not isinstance(raw, list) or not raw:
        err.add(f"{where}.roles: expected a non-empty list")
        return []
    roles: list[str] = []
    ok = True
    for role in raw:
        if role not in ROLES:
            err.add(f"{where}.roles: unknown role '{role}'")
            ok = False
        elif role in roles:
            err.add(f"{where}.roles: duplicate role '{role}'")
            ok = False
        else:
            roles.append(role)
    return roles if ok else []


def _priority(item: dict[str, Any], where: str, err: _Errors) -> int | None:
    if "priority" not in item:
        return None
    if item.get("kind") == "headset":
        err.add(f"{where}.priority: only allowed for kind 'source'")
        return None
    prio = item["priority"]
    if isinstance(prio, bool) or not isinstance(prio, int) or prio < 0:
        err.add(f"{where}.priority: expected an integer >= 0")
        return None
    return prio


def _devices(raw: Any, err: _Errors) -> list[Device]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        err.add("devices: expected a list")
        return []
    result: list[Device] = []
    seen_alias: set[str] = set()
    seen_mac: set[str] = set()
    for i, item in enumerate(raw):
        where = f"devices[{i}]"
        if not isinstance(item, dict):
            err.add(f"{where}: expected a mapping")
            continue
        err.unknown_keys(item, DEVICE_KEYS, where)
        mac = _mac(item.get("mac"), where, err)
        alias = item.get("alias")
        alias_ok = isinstance(alias, str) and bool(ALIAS_RE.match(alias))
        if not alias_ok:
            err.add(f"{where}.alias: expected {ALIAS_RE.pattern}")
        kind = item.get("kind")
        kind_ok = kind in KINDS
        if not kind_ok:
            err.add(f"{where}.kind: expected one of {', '.join(KINDS)}")
        priority = _priority(item, where, err)
        if alias_ok:
            if alias in seen_alias:
                err.add(f"devices: duplicate alias '{alias}'")
            seen_alias.add(str(alias))
        if mac is not None:
            if mac in seen_mac:
                err.add(f"devices: duplicate mac '{mac}'")
            seen_mac.add(mac)
        if mac is not None and alias_ok and kind_ok:
            if kind == "source" and priority is None:
                priority = DEFAULT_PRIORITY
            result.append(
                Device.model_validate(
                    {"mac": mac, "alias": alias, "kind": kind, "priority": priority}
                )
            )
    return result


def _routes(raw: Any, devices: list[Device], err: _Errors) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        err.add("default_routes: expected a mapping")
        return {}
    headsets = {d.alias for d in devices if d.kind == "headset"}
    sources = {d.alias for d in devices if d.kind == "source"}
    routes: dict[str, str] = {}
    for head, src in raw.items():
        if not isinstance(head, str) or not isinstance(src, str):
            err.add(f"default_routes: expected alias strings (got {head!r}: {src!r})")
            continue
        if head not in headsets:
            err.add(f"default_routes: unknown headset alias '{head}'")
        elif src not in sources:
            err.add(f"default_routes: unknown source alias '{src}'")
        else:
            routes[str(head)] = str(src)
    return routes


def _api(raw: Any, err: _Errors) -> ApiConfig:
    if raw is None:
        return ApiConfig()
    if not isinstance(raw, dict):
        err.add("api: expected a mapping")
        return ApiConfig()
    err.unknown_keys(raw, API_KEYS, "api")
    listen = raw.get("listen", DEFAULT_LISTEN)
    if not _valid_listen(listen):
        err.add("api.listen: expected host:port")
        listen = DEFAULT_LISTEN
    token = raw.get("token_file", str(DEFAULT_TOKEN_FILE))
    if not isinstance(token, str) or not token.startswith("/"):
        err.add("api.token_file: expected an absolute path")
        token = str(DEFAULT_TOKEN_FILE)
    return ApiConfig(listen=listen, token_file=Path(token))


def _valid_listen(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    host, sep, port = value.partition(":")
    return bool(
        sep
        and host
        and ":" not in port
        and port.isascii()
        and port.isdigit()
        and 1 <= int(port) <= 65535
    )


def _mqtt(raw: Any, err: _Errors) -> MqttConfig:
    if raw is None:
        return MqttConfig()
    if not isinstance(raw, dict):
        err.add("mqtt: expected a mapping")
        return MqttConfig()
    err.unknown_keys(raw, MQTT_KEYS, "mqtt")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        err.add("mqtt.enabled: expected a boolean")
        enabled = False
    return MqttConfig(enabled=enabled)


def _pairing(raw: Any, err: _Errors) -> PairingConfig:
    if raw is None:
        return PairingConfig()
    if not isinstance(raw, dict):
        err.add("pairing: expected a mapping")
        return PairingConfig()
    err.unknown_keys(raw, PAIRING_KEYS, "pairing")
    low, high = PAIRING_DURATION_RANGE
    duration = raw.get("default_duration", 60)
    if isinstance(duration, bool) or not isinstance(duration, int) or not low <= duration <= high:
        err.add(f"pairing.default_duration: expected an integer between {low} and {high}")
        duration = 60
    accept = raw.get("accept_incoming", True)
    if not isinstance(accept, bool):
        err.add("pairing.accept_incoming: expected a boolean")
        accept = True
    return PairingConfig(default_duration=duration, accept_incoming=accept)


def _role_policy(all_roles: list[list[str]], count: int, err: _Errors) -> None:
    """V3 (rôle porté par exactement un adaptateur) et V4 (au plus 2 adaptateurs)."""
    if count:
        for role in ROLES:
            found = sum(1 for roles in all_roles if role in roles)
            if found != 1:
                err.add(f"role '{role}' must be provided by exactly one adapter (found {found})")
    if count > MAX_ADAPTERS:
        err.add(f"at most {MAX_ADAPTERS} adapters are supported (found {count})")


def parse_config(data: Any) -> Config:
    """Valide un document déjà parsé ; lève `ConfigError` avec toutes les erreurs."""
    err = _Errors()
    if not isinstance(data, dict):
        raise ConfigError([f"{PREFIX}expected a YAML mapping at top level"])
    err.unknown_keys(data, TOP_KEYS, None)
    adapters, all_roles, adapter_count = _adapters(data.get("adapters"), err)
    devices = _devices(data.get("devices"), err)
    routes = _routes(data.get("default_routes"), devices, err)
    api = _api(data.get("api"), err)
    mqtt = _mqtt(data.get("mqtt"), err)
    pairing = _pairing(data.get("pairing"), err)
    _role_policy(all_roles, adapter_count, err)
    if err.items:
        raise ConfigError(err.items)
    return Config(
        adapters=tuple(adapters),
        devices=tuple(devices),
        default_routes=routes,
        api=api,
        mqtt=mqtt,
        pairing=pairing,
    )


def load_config(path: str | Path) -> Config:
    """Lit et valide le fichier YAML ; V10 : fichier illisible ou YAML invalide → `ConfigError`."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        reason = " ".join(str(exc).split())
        raise ConfigError([f"{PREFIX}cannot read '{path}': {reason}"]) from exc
    if not isinstance(data, dict):
        raise ConfigError([f"{PREFIX}cannot read '{path}': expected a YAML mapping at top level"])
    return parse_config(data)
