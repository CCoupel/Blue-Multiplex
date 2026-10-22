"""Point d'entree du daemon btmuxd."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from btmux import __version__

DEFAULT_CONFIG = "/etc/btmux/config.yaml"


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
    build_parser().parse_args(argv)
    # Validation de la config branchee en T1.5 (module btmux.config).
    print(f"btmuxd {__version__}: not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
