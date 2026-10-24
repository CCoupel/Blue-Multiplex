"""Point d'entree du daemon btmuxd."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from btmux import __version__, daemon
from btmux.config import Config, ConfigError, load_effective, load_state
from btmux.config.models import DEFAULT_STATE_PATH

DEFAULT_CONFIG = "/etc/btmux/config.yaml"
EXIT_CONFIG_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="btmuxd", description="Daemon multiplexeur Bluetooth.")
    parser.add_argument("--version", action="version", version=f"btmuxd {__version__}")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"fichier de configuration (defaut {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_PATH),
        help=f"fichier d'état des affectations (prime sur la config, defaut {DEFAULT_STATE_PATH})",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="valide la configuration et le fichier d'état puis sort (0 = OK, 2 = erreurs)",
    )
    return parser


def _check(config_path: str, state_path: str, config: Config) -> int:
    """`--check-config` : état invalide signalé (ignoré au runtime), puis liste effective."""
    print(f"config OK: {config_path}")
    try:
        load_state(state_path)
    except ConfigError as exc:
        for line in exc.errors:
            line = line if line.startswith("state:") else f"state: {line}"
            print(f"{line} (ignored: falling back to config)", file=sys.stderr)
    print(f"adapters source: {config.adapters_source}")
    for adapter in config.adapters:
        print(f"  {adapter.mac}\t{adapter.name}\t{','.join(adapter.roles)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_effective(args.config, args.state)
    except ConfigError as exc:
        for line in exc.errors:
            print(line, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    if args.check_config:
        return _check(args.config, args.state, config)
    return daemon.run(config)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
