#!/usr/bin/env bash
# Rapport « rôles / profils » (#13) : pour chaque contrôleur, ses UUIDs annoncés et les profils des cartes PipeWire.
# Lecture seule. Usage : roles_report.sh [fichier de sortie]. Provisoire — à valider avec les dongles UB500 (T3.2b).
set -uo pipefail
OUT="${1:-/dev/stdout}"
{
  echo "# $(date -u +%FT%TZ) rôles / profils"
  for h in $(hciconfig 2>/dev/null | awk -F: '/^hci/ {print $1}'); do
    echo "## $h"
    hciconfig -a "$h" 2>/dev/null | grep -E "Bus|BD Address|Class|HCI Version"
    echo "# UUIDs annoncés (bluetoothctl show, contrôleur par défaut uniquement)"
  done
  timeout 8 bluetoothctl list </dev/null
  echo "## cartes PipeWire (profil actif / profils disponibles)"
  pw-dump 2>/dev/null | python3 -c '
import json, sys
for o in json.load(sys.stdin):
    p = (o.get("info") or {}).get("props") or {}
    if o["type"].endswith("Device") and "bluez" in p.get("device.name", ""):
        prm = o["info"].get("params", {})
        print(p.get("device.name"), p.get("api.bluez5.path"), "profil", [x.get("name") for x in prm.get("Profile", [])],
              "dispo", [x.get("name") for x in prm.get("EnumProfile", [])])
'
} > "$OUT"
