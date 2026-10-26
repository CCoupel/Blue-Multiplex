#!/usr/bin/env python3
"""Prototype #13 — génère les règles WirePlumber `bluez5.roles` PAR CONTRÔLEUR (via `api.bluez5.path`).

Constat (investigation D-2, WirePlumber 0.5.13 / PipeWire 1.6.2) : les règles `monitor.bluez.rules` sont appliquées aux
propriétés de chaque appareil DISTANT à sa création ; ces propriétés contiennent `api.bluez5.path` =
`/org/bluez/hciN/dev_<MAC>`. Une règle `api.bluez5.path = "~/org/bluez/hciN/dev_*"` cible donc « les appareils vus
par le contrôleur hciN » : c'est l'équivalent d'un filtrage par adaptateur local, avec deux limites (voir README) :
  - `hciN` n'est pas stable (hotplug) : le fragment doit être régénéré depuis les rôles/MAC (ce script) ;
  - cela restreint les profils que le Pi utilise avec l'appareil, PAS les UUID annoncés par le contrôleur (identiques).

Usage : gen_rules.py [--from-json FICHIER | (défaut : `btmuxctl controllers`)] [--out FRAGMENT.conf]
Aucune écriture hors --out ; aucune modification de WirePlumber. Provisoire — à valider avec les dongles UB500 (T3.2b).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROLES_BY_ADAPTER_ROLE = {
    "sources": ["a2dp_sink", "hfp_hf"],  # le Pi se présente en casque aux PC / téléphones
    "headsets": ["a2dp_source", "hfp_ag"],  # le Pi se présente en source aux casques
}


def controllers(raw: str) -> list[dict[str, object]]:
    data = json.loads(raw)
    return [c for c in data["controllers"] if c.get("present") and c.get("role")]


def render(ctrls: list[dict[str, object]]) -> str:
    lines = [
        "# Généré par spikes/13-roles/gen_rules.py — rôles Bluetooth par contrôleur (api.bluez5.path). NON ACTIF par défaut.",
        "# Régénérer à chaque changement de rôles / hotplug (hciN n'est pas stable).",
        "monitor.bluez.rules = [",
    ]
    for c in sorted(ctrls, key=lambda x: str(x["hci"])):
        hci, role = str(c["hci"]), str(c["role"])
        if not re.fullmatch(r"hci\d+", hci) or role not in ROLES_BY_ADAPTER_ROLE:
            raise ValueError(f"contrôleur inattendu : {hci} / {role}")
        roles = " ".join(ROLES_BY_ADAPTER_ROLE[role])
        lines += [
            "  {",
            f"    # {hci} = rôle {role} ({c.get('name')})",
            f'    matches = [ {{ api.bluez5.path = "~/org/bluez/{hci}/dev_*" }} ]',
            f"    actions = {{ update-props = {{ bluez5.roles = [ {roles} ] }} }}",
            "  }",
        ]
    lines.append("]")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", help="sortie de `btmuxctl controllers` (défaut : l'appeler)")
    parser.add_argument("--out", help="fichier du fragment (défaut : sortie standard)")
    args = parser.parse_args()
    if args.from_json:
        raw = Path(args.from_json).read_text(encoding="utf-8")
    else:
        raw = subprocess.run(
            ["/opt/btmux/bin/btmuxctl", "controllers"], capture_output=True, text=True, check=True
        ).stdout
    text = render(controllers(raw))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
