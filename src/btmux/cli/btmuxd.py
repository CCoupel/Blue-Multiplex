"""Point d'entree du daemon btmuxd."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from btmux import __version__, daemon
from btmux.config import ConfigError, load_config

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
        "--check-config",
        action="store_true",
        help="valide la configuration puis sort (0 = OK, 2 = erreurs)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        for line in exc.errors:
            print(line, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    if args.check_config:
        print(f"config OK: {args.config}")
        return 0
    return daemon.run(config)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
