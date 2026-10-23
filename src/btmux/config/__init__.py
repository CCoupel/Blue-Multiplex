"""Configuration de btmuxd (`/etc/btmux/config.yaml`) — contrat `contracts/config-schema.md`."""

from btmux.config.loader import load_config, parse_config
from btmux.config.models import (
    Adapter,
    ApiConfig,
    Config,
    ConfigError,
    Device,
    MqttConfig,
    PairingConfig,
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
    "parse_config",
]
