"""Masque et filtre les preuves d'un spike avant leur copie sous `docs/` (dépôt public).

Règles :
- toute adresse MAC (`AA:BB:..`, `AA_BB_..`, `AA-BB-..`, majuscules ou minuscules) devient
  `OUI:xx:xx:xx` (3 premiers octets conservés), **sauf** celle du Pi (`--pi-mac`) ;
- dans un `.jsonl` (journal de `pair_watch.py`), seules les lignes des appareils listés par
  `--keep` (et celles qui ne concernent aucun appareil, ex. start/stop) sont conservées : les
  appareils tiers découverts pendant un scan de voisinage sont supprimés ;
- `--name-map ANCIEN=NOUVEAU` (répétable) remplace des noms d'appareils personnels.

Usage :
  mask_evidence.py --pi-mac B8:27:EB:1A:2E:D6 --keep AA:BB:CC:DD:EE:FF [--keep ...] \\
      [--name-map "ANCIEN=NOUVEAU"] -o docs/spikes/05-exposure fichier...
  mask_evidence.py --pi-mac B8:27:EB:1A:2E:D6 --check docs/spikes
      (code 1 si une MAC non autorisée subsiste)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MAC_RE = re.compile(
    r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{2})([:_-])([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})\2"
    r"([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})(?![0-9A-Fa-f])"
)
DEV_RE = re.compile(r"dev_(([0-9A-Fa-f]{2}_){5}[0-9A-Fa-f]{2})")


def norm(mac: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", mac).upper()


def mask_text(text: str, pi_mac: str) -> str:
    def repl(m: re.Match[str]) -> str:
        octets = [m.group(i) for i in (1, 3, 4, 5, 6, 7)]
        if norm("".join(octets)) == norm(pi_mac):
            return m.group(0)
        sep = m.group(2)
        return sep.join([octets[0], octets[1], octets[2], "xx", "xx", "xx"])

    return MAC_RE.sub(repl, text)


def apply_names(text: str, names: dict[str, str]) -> str:
    for old, new in names.items():
        text = text.replace(old, new)
    return text


def filter_jsonl(text: str, keep: set[str]) -> str:
    out: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = DEV_RE.search(line)
        if match is not None and norm(match.group(1)) not in keep:
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def process(path: Path, args: argparse.Namespace, keep: set[str], names: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".jsonl":
        text = filter_jsonl(text, keep)
    return apply_names(mask_text(text, args.pi_mac), names)


def check(root: Path, pi_mac: str) -> int:
    bad = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            for m in MAC_RE.finditer(line):
                if norm(m.group(0)) != norm(pi_mac):
                    print(f"{path}:{lineno}: MAC non masquée {m.group(0)}")
                    bad += 1
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--pi-mac", required=True, help="MAC du Pi, seule conservée en clair")
    parser.add_argument(
        "--keep", action="append", default=[], help="MAC d'un appareil de la séance (.jsonl)"
    )
    parser.add_argument("--name-map", action="append", default=[], metavar="ANCIEN=NOUVEAU")
    parser.add_argument("-o", "--out", type=Path, help="dossier de sortie")
    parser.add_argument("--check", type=Path, help="vérifie un dossier (code 1 si MAC non masquée)")
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()
    if args.check:
        return check(args.check, args.pi_mac)
    if not args.out or not args.files:
        parser.error("-o et au moins un fichier sont requis")
    names = dict(item.split("=", 1) for item in args.name_map)
    keep = {norm(m) for m in args.keep}
    args.out.mkdir(parents=True, exist_ok=True)
    for path in args.files:
        (args.out / path.name).write_text(process(path, args, keep, names), encoding="utf-8")
        print(f"{path} -> {args.out / path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
