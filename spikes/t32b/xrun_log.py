#!/usr/bin/env python3
"""Taux de dropouts/underruns (#8) : échantillonne `pw-top -b` et cumule la colonne ERR des nœuds Bluetooth.

Usage : xrun_log.py [--minutes 30] [--interval 10] [--match bluez] [--out xruns.json]
Chaque échantillon = un cliché de `pw-top`; le résultat donne, par nœud, les erreurs ajoutées pendant la durée.
Provisoire — à valider avec les dongles UB500 (T3.2b).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time


def parse_pw_top(text: str) -> dict[str, int]:
    """Dernier cliché de `pw-top -b` -> {nom du nœud: ERR}. Colonnes : S ID QUANT RATE WAIT BUSY W/Q B/Q ERR FORMAT NAME."""
    snapshot: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if parts[:2] == ["S", "ID"]:  # nouvel en-tête = nouveau cliché
            snapshot = {}
            continue
        if len(parts) >= 10 and parts[0] in "RSIB" and parts[1].isdigit():
            name = parts[-1]
            err_index = 8
            if parts[err_index].isdigit():
                snapshot[name] = int(parts[err_index])
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--match", default="bluez")
    parser.add_argument("--out")
    args = parser.parse_args()
    first: dict[str, int] = {}
    last: dict[str, int] = {}
    end = time.monotonic() + args.minutes * 60
    while time.monotonic() < end:
        out = subprocess.run(
            ["pw-top", "-b", "-n", "2"], capture_output=True, text=True, timeout=30, check=False
        ).stdout
        snap = {k: v for k, v in parse_pw_top(out).items() if args.match in k}
        for name, err in snap.items():
            first.setdefault(name, err)
            last[name] = err
        time.sleep(args.interval)
    added = {name: last[name] - first[name] for name in last}
    result = {"minutes": args.minutes, "xruns_ajoutes": added}
    print(json.dumps(result, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
