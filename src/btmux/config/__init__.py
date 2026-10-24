"""Configuration de btmuxd (`/etc/btmux/config.yaml`) — contrat `contracts/config-schema.md`."""

from btmux.config.loader import load_config, parse_adapter_list, parse_config
from btmux.config.models import (
    Adapter,
    ApiConfig,
    Config,
    ConfigError,
    Device,
    MqttConfig,
    PairingConfig,
)
from btmux.config.state import (
    load_effective,
    load_state,
    write_identity_request,
    write_state_atomic,
)

__all__ = [
    "Adapter",
    "ApiConfig",
    "Config",
    "ConfigError",
    "Device",
    "MqttConfig",
    "PairingConfig",
    "load_config",
    "load_effective",
    "load_state",
    "parse_adapter_list",
    "parse_config",
    "write_identity_request",
    "write_state_atomic",
]
