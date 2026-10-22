#!/usr/bin/env bash
# Pose l'identité "casque btmux" sur l'adaptateur (nom + classe 0x240404) et gère la fenêtre d'appairage.
# Usage : set_identity.sh [--window SECONDES] [--close] [--name NOM]
#   (sans option) : identité + fenêtre découvrable/appairable de 180 s
#   --window N    : durée de la fenêtre (s) ; --close : ferme la fenêtre (non découvrable, non appairable)
# Env : BTMUX_ADAPTER_MAC. Nécessite sudo sans mot de passe pour btmgmt.
# Provisoire — à revalider avec dongle RTL8761B.
. "$(dirname "$0")/common.sh"

WINDOW=180 NAME=btmux CLOSE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --window) WINDOW="${2:?durée}"; shift 2 ;;
    --name) NAME="${2:?nom}"; shift 2 ;;
    --close) CLOSE=1; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "option inconnue: $1" >&2; exit 2 ;;
  esac
done
[[ "$WINDOW" =~ ^[0-9]+$ ]] || { echo "--window attend un entier" >&2; exit 2; }
[[ "$NAME" =~ ^[A-Za-z0-9._\ -]{1,32}$ ]] || { echo "nom invalide" >&2; exit 2; }

idx="$(adapter_index)"
log "adaptateur $BTMUX_ADAPTER_MAC = hci$idx"
bt() { sudo -n btmgmt -i "$idx" "$@"; }

if [ "$CLOSE" = 1 ]; then
  bt discov no >/dev/null; bt bondable off >/dev/null
  log "fenêtre fermée"; exit 0
fi

# Nom et classe : 0x240404 = Audio (service) + Rendering, majeur Audio/Video (4), mineur Wearable Headset (raw 0x04).
bt name "$NAME" >/dev/null
bt class 4 4 >/dev/null
bt bondable on >/dev/null
bt connectable on >/dev/null
bt ssp on >/dev/null 2>&1 || true
# Fenêtre temporisée : le noyau referme lui-même la découvrabilité au bout de $WINDOW s.
bt discov yes "$WINDOW" >/dev/null
log "fenêtre d'appairage ouverte pour ${WINDOW}s (fermeture auto de la découvrabilité)"

# bluetoothd gère aussi un Alias : l'aligner pour que le nom annoncé soit bien $NAME.
if ! timeout 8 bluetoothctl show </dev/null | grep -q "Alias: $NAME\$"; then
  timeout 8 bluetoothctl system-alias "$NAME" </dev/null >/dev/null || true
fi
timeout 8 bluetoothctl show </dev/null | grep -E 'Name|Alias|Class|Powered|Discoverable|Pairable' || true
