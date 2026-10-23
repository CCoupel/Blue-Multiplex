#!/usr/bin/env bash
# Inventaire de l'API téléphonie (#6) : ce que BlueZ / PipeWire exposent pour HFP (indicateurs d'appel, AT, objets D-Bus).
# Lecture seule. Usage : telephony_inventory.sh [fichier] (défaut out/telephony-inventory.txt). MAC à masquer avant commit.
# Provisoire — à valider avec les dongles UB500 (T3.2b).
set -uo pipefail
OUT="${1:-$(dirname "$0")/out/telephony-inventory.txt}"
mkdir -p "$(dirname "$OUT")"
{
  echo "# $(date -u +%FT%TZ) inventaire téléphonie"
  echo "## busctl tree org.bluez"; busctl tree org.bluez 2>&1 | head -80
  echo "## interfaces org.bluez présentes (noms)"; busctl tree org.bluez 2>/dev/null | grep -o '/org/bluez[^ ]*' | head -40 | while read -r o; do
    busctl introspect org.bluez "$o" 2>/dev/null | awk '$2=="interface"{print $1}'; done | sort -u
  echo "## services d'appel ? (oFono / hsphfpd / Telephony)"; busctl list --no-pager 2>/dev/null | grep -iE "ofono|hfp|hsp|telephony" || echo "(aucun service oFono/hsphfpd sur le bus système)"
  echo "## objets PipeWire liés à HFP"; pw-dump 2>/dev/null | python3 -c '
import json, sys
for o in json.load(sys.stdin):
    p = (o.get("info") or {}).get("props") or {}
    keys = {k: v for k, v in p.items() if "bluez5" in k or "hfp" in k.lower() or "call" in k.lower() or "codec" in k.lower()}
    if keys:
        print(o["type"].split(":")[-1], o["id"], p.get("node.name") or p.get("device.name"), keys)
'
  echo "## pistes à explorer : indicateurs (CIND/CIEV), AT (ATA, AT+CHUP) via le canal RFCOMM — voir btmon (HFP) et le backend natif"
} > "$OUT" 2>&1
echo "inventaire écrit dans $OUT"
