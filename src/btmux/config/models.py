"""Modèles typés de la configuration (Pydantic v2, `extra="forbid"`, immuables)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["sources", "headsets"]
Kind = Literal["source", "headset"]

DEFAULT_LISTEN = "0.0.0.0:8088"
DEFAULT_TOKEN_FILE = Path("/etc/btmux/token")
DEFAULT_PRIORITY = 100
DEFAULT_STATE_PATH = Path("/var/lib/btmux/adapters.yaml")


class ConfigError(Exception):
    """Configuration invalide : `errors` contient un message par ligne, préfixé `config: `."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Adapter(_Model):
    mac: str
    name: str
    roles: tuple[Role, ...]


class Device(_Model):
    mac: str
    alias: str
    kind: Kind
    priority: int | None = None


class ApiConfig(_Model):
    listen: str = DEFAULT_LISTEN
    token_file: Path = DEFAULT_TOKEN_FILE


class MqttConfig(_Model):
    enabled: bool = False


class PairingConfig(_Model):
    """Fenêtre d'appairage (#20/#21, V11)."""

    default_duration: int = 60
    accept_incoming: bool = True


class Config(_Model):
    adapters: tuple[Adapter, ...]
    devices: tuple[Device, ...] = ()
    default_routes: dict[str, str] = Field(default_factory=dict)
    api: ApiConfig = Field(default_factory=ApiConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    pairing: PairingConfig = Field(default_factory=PairingConfig)
    # Hors YAML : provenance de la liste `adapters` (#23) et chemin du fichier d'état
    adapters_source: Literal["state", "config"] = "config"
    state_path: Path = DEFAULT_STATE_PATH

    def adapter_for_role(self, role: Role) -> Adapter:
        for adapter in self.adapters:
            if role in adapter.roles:
                return adapter
        raise LookupError(f"no adapter provides role '{role}'")

    @property
    def sources(self) -> list[Device]:
        found = [d for d in self.devices if d.kind == "source"]
        return sorted(found, key=lambda d: (d.priority if d.priority is not None else 0, d.alias))

    @property
    def headsets(self) -> list[Device]:
        return sorted((d for d in self.devices if d.kind == "headset"), key=lambda d: d.alias)
