"""Outil CLI minimal sur la configuration (utilisé par `scripts/btmux-adapters.sh`).

python -m btmux.config adapters --config /etc/btmux/config.yaml
    -> une ligne par adaptateur : MAC<TAB>nom<TAB>rôles (séparés par des virgules)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from btmux.config import ConfigError, load_config


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m btmux.config", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    adapters = sub.add_parser("adapters", help="liste les adaptateurs (MAC, nom, rôles)")
    adapters.add_argument("--config", default="/etc/btmux/config.yaml")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        for line in exc.errors:
            print(line, file=sys.stderr)
        return 2
    for adapter in cfg.adapters:
        print(f"{adapter.mac}\t{adapter.name}\t{','.join(adapter.roles)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
