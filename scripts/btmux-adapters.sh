#!/usr/bin/env bash
# Identité persistante des adaptateurs Bluetooth de btmux (#18) : pour chaque entrée de `adapters[]`, retrouve l'index
# `hciN` par la MAC (jamais d'index en dur, pas de règle udev), fixe l'alias (persistant, stocké par BlueZ) et la classe
# d'appareil selon le rôle, et ferme découverte et appairage (c'est btmuxd qui ouvre les fenêtres, #20).
#   - rôle `sources`  -> classe « casque audio » (majeur 4 / mineur 4 ; la classe finale 0x240404 dépend des UUIDs) ;
#   - rôle `headsets` seul -> classe « ordinateur » (majeur 1 / mineur 12 = portable).
# Usage : btmux-adapters.sh [--config /etc/btmux/config.yaml] [--dry-run] [--wait SECONDES]
#   --dry-run : affiche les commandes sans rien modifier (utilisable sans droits root).
#   --wait N  : attend jusqu'à N s (défaut 20) que tous les adaptateurs de la config soient énumérés (USB).
# Idempotent. Sans adaptateur présent : avertissement et code 0 (ne bloque jamais le démarrage). Config invalide : code 2.
# Variables : BTMUX_PYTHON (défaut /opt/btmux/bin/python, repli python3), BTMUX_BTMGMT, BTMUX_BUSCTL,
#   BTMUX_CLASS_SOURCES (« 4 4 »), BTMUX_CLASS_HEADSETS (« 1 12 »).
set -euo pipefail

CONFIG=/etc/btmux/config.yaml DRY=0 WAIT=20
while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONFIG="${2:?chemin}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --wait) WAIT="${2:?secondes}"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "btmux-adapters: option inconnue: $1" >&2; exit 2 ;;
  esac
done
[[ "$WAIT" =~ ^[0-9]+$ ]] || { echo "btmux-adapters: --wait attend un entier" >&2; exit 2; }

PY="${BTMUX_PYTHON:-/opt/btmux/bin/python}"
[ -x "$PY" ] || PY=python3
BTMGMT="${BTMUX_BTMGMT:-btmgmt}"
BUSCTL="${BTMUX_BUSCTL:-busctl}"
CLASS_SOURCES="${BTMUX_CLASS_SOURCES:-4 4}"
CLASS_HEADSETS="${BTMUX_CLASS_HEADSETS:-1 12}"
SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo -n"

log() { echo "btmux-adapters: $*"; }
run() {
  if [ "$DRY" = 1 ]; then echo "DRY-RUN: $*"; else "$@"; fi
}

if ! LIST="$("$PY" -m btmux.config adapters --config "$CONFIG")"; then
  echo "btmux-adapters: configuration invalide ($CONFIG)" >&2
  exit 2
fi

index_of() {   # MAC -> index hciN (vide si absent)
  # shellcheck disable=SC2086
  $SUDO $BTMGMT info 2>/dev/null | awk -v mac="$1" '
    /^hci[0-9]+:/ { idx = substr($1, 4); sub(/:$/, "", idx) }
    tolower($1) == "addr" && toupper($2) == toupper(mac) { print idx; exit }'
}

deadline=$((SECONDS + WAIT))
while :; do
  missing=0
  while IFS=$'\t' read -r mac _ _; do
    [ -n "$mac" ] || continue
    [ -n "$(index_of "$mac")" ] || missing=1
  done <<< "$LIST"
  { [ "$missing" = 0 ] || [ "$DRY" = 1 ] || [ "$SECONDS" -ge "$deadline" ]; } && break
  sleep 1
done

while IFS=$'\t' read -r mac name roles; do
  [ -n "$mac" ] || continue
  idx="$(index_of "$mac")"
  if [ -z "$idx" ]; then
    echo "btmux-adapters: AVERTISSEMENT adaptateur $mac ($name, rôles $roles) introuvable — ignoré" >&2
    [ "$DRY" = 1 ] && echo "DRY-RUN: (adaptateur $mac absent : aucune commande n'est planifiée)"
    continue
  fi
  case ",$roles," in
    *,sources,*) class="$CLASS_SOURCES" ;;
    *) class="$CLASS_HEADSETS" ;;
  esac
  log "$mac -> hci$idx rôles=$roles alias='$name' classe='$class'"
  # shellcheck disable=SC2086
  {
    run $SUDO $BTMGMT -i "$idx" power on
    current="$($BUSCTL get-property org.bluez "/org/bluez/hci$idx" org.bluez.Adapter1 Alias 2>/dev/null | sed -n 's/^s "\(.*\)"$/\1/p' || true)"
    if [ "$current" != "$name" ]; then
      run $SUDO $BUSCTL set-property org.bluez "/org/bluez/hci$idx" org.bluez.Adapter1 Alias s "$name"
    fi
    run $SUDO $BTMGMT -i "$idx" class $class
    run $SUDO $BTMGMT -i "$idx" bondable off
    run $SUDO $BTMGMT -i "$idx" discov no
  }
done <<< "$LIST"
exit 0
