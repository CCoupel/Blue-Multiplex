#!/usr/bin/env bash
# Identité persistante des adaptateurs Bluetooth de btmux (#18) : pour chaque entrée de `adapters[]`, retrouve l'index
# `hciN` par la MAC (jamais d'index en dur, pas de règle udev), fixe l'alias (persistant, stocké par BlueZ) et la classe
# d'appareil selon le rôle, et ferme découverte et appairage (c'est btmuxd qui ouvre les fenêtres, #20).
# Tout autre contrôleur présent (sans rôle : Bluetooth interne, dongle non affecté — #23) est seulement fermé
# (bondable off, discov no) : ni alias ni classe ne sont touchés.
#   - rôle `sources`  -> classe « casque audio » (majeur 4 / mineur 4 ; la classe finale 0x240404 dépend des UUIDs) ;
#   - rôle `headsets` seul -> classe « ordinateur » (majeur 1 / mineur 12 = portable).
# Usage : btmux-adapters.sh [--config /etc/btmux/config.yaml] [--state FICHIER] [--dry-run] [--wait SECONDES] [--reset]
#   --state   : fichier d'état des rôles (#23, ex. /var/lib/btmux/adapters.yaml) ; s'il existe et est valide, sa liste
#               prime sur celle de la config (transmis à `btmux.config adapters --state`). Absent : défaut de btmux.config.
#   --dry-run : affiche les commandes sans rien modifier (utilisable sans droits root).
#   --reset   : ne fait que refermer appairage et découverte (bondable off, discov no) de tous les contrôleurs
#               présents — ExecStopPost de btmuxd.
#   --wait N  : attend jusqu'à N s (défaut 20) que tous les adaptateurs de la config soient énumérés (USB).
# Idempotent. Sans adaptateur présent : avertissement et code 0 (ne bloque jamais le démarrage). Config invalide : code 2.
# Variables : BTMUX_PYTHON (défaut /opt/btmux/bin/python, repli python3), BTMUX_BTMGMT, BTMUX_BUSCTL,
#   BTMUX_CLASS_SOURCES (« 4 4 »), BTMUX_CLASS_HEADSETS (« 1 12 »).
set -euo pipefail

CONFIG=/etc/btmux/config.yaml STATE="" DRY=0 WAIT=20 RESET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONFIG="${2:?chemin}"; shift 2 ;;
    --state) STATE="${2:?chemin}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --reset) RESET=1; shift ;;
    --wait) WAIT="${2:?secondes}"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
FAILED=0
run() {
  if [ "$DRY" = 1 ]; then echo "DRY-RUN: $*"; elif ! "$@"; then FAILED=1; echo "btmux-adapters: AVERTISSEMENT commande en échec: $*" >&2; fi
}
# btmgmt se bloque quand stdin est /dev/null (contexte systemd) : on lui donne un tube fermé après une ligne, et un plafond.
# shellcheck disable=SC2086
mgmt() { printf '\n' | timeout 10 $SUDO $BTMGMT "$@"; }

rc=0
ARGS=(adapters --config "$CONFIG")
[ -z "$STATE" ] || ARGS+=(--state "$STATE")
LIST="$("$PY" -I -P -m btmux.config "${ARGS[@]}")" || rc=$?
if [ "$rc" -ne 0 ]; then
  if [ "$rc" -eq 2 ]; then
    echo "btmux-adapters: configuration invalide ($CONFIG${STATE:+, état $STATE})" >&2
  else
    echo "btmux-adapters: impossible d'exécuter 'btmux.config' avec $PY (code $rc) — venv /opt/btmux absent ou btmux non installé ? (BTMUX_PYTHON)" >&2
  fi
  exit 2
fi

MGMT_ERR=0
index_of() {   # MAC -> index hciN (vide si absent ou si btmgmt échoue : MGMT_ERR=1)
  local out
  if ! out="$(mgmt info 2>/dev/null)"; then MGMT_ERR=1; return 0; fi
  printf '%s\n' "$out" | awk -v mac="$1" '
    /^hci[0-9]+:/ { idx = substr($1, 4); sub(/:$/, "", idx) }
    tolower($1) == "addr" && toupper($2) == toupper(mac) { print idx; exit }'
}

all_indices() {   # tous les contrôleurs présents : une ligne « index<TAB>MAC » (vide si btmgmt échoue)
  local out
  out="$(mgmt info 2>/dev/null)" || return 0
  printf '%s\n' "$out" | awk '
    /^hci[0-9]+:/ { idx = substr($1, 4); sub(/:$/, "", idx) }
    tolower($1) == "addr" && idx != "" { print idx "\t" toupper($2); idx = "" }'
}

# btmgmt inutilisable (absent, sudo refusé, socket mgmt) : message explicite, code 0 (contrat : ne bloque pas le démarrage)
index_of 00:00:00:00:00:00 >/dev/null
if [ "$MGMT_ERR" = 1 ] && [ "$DRY" != 1 ]; then
  echo "btmux-adapters: AVERTISSEMENT '$BTMGMT info' a échoué (absent, droits ou socket mgmt) — aucun adaptateur configurable" >&2
  exit 0
fi

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

ASSIGNED=" "   # index des contrôleurs listés (affectés à un rôle), séparés par des espaces
while IFS=$'\t' read -r mac name roles; do
  [ -n "$mac" ] || continue
  idx="$(index_of "$mac")"
  if [ -z "$idx" ]; then
    echo "btmux-adapters: AVERTISSEMENT adaptateur $mac ($name, rôles $roles) introuvable — ignoré" >&2
    [ "$DRY" = 1 ] && echo "DRY-RUN: (adaptateur $mac absent : aucune commande n'est planifiée)"
    continue
  fi
  ASSIGNED="$ASSIGNED$idx "
  if [ "$RESET" = 1 ]; then
    log "$mac -> hci$idx fermeture de l'appairage et de la découverte"
    run mgmt -i "$idx" bondable off
    run mgmt -i "$idx" discov no
    continue
  fi
  case ",$roles," in
    *,sources,*) class="$CLASS_SOURCES" ;;
    *) class="$CLASS_HEADSETS" ;;
  esac
  log "$mac -> hci$idx rôles=$roles alias='$name' classe='$class'"
  # shellcheck disable=SC2086
  {
    run mgmt -i "$idx" power on
    current="$($BUSCTL get-property org.bluez "/org/bluez/hci$idx" org.bluez.Adapter1 Alias 2>/dev/null | sed -n 's/^s "\(.*\)"$/\1/p' || true)"
    if [ "$current" != "$name" ]; then
      run $SUDO $BUSCTL set-property org.bluez "/org/bluez/hci$idx" org.bluez.Adapter1 Alias s "$name"
    fi
    run mgmt -i "$idx" class $class
    run mgmt -i "$idx" bondable off
    run mgmt -i "$idx" discov no
  }
done <<< "$LIST"

# Contrôleurs sans rôle (#23) : fermés, classe et alias intacts.
while IFS=$'\t' read -r idx mac; do
  [ -n "$idx" ] || continue
  case "$ASSIGNED" in *" $idx "*) continue ;; esac
  log "$mac -> hci$idx sans rôle : fermeture de l'appairage et de la découverte"
  run mgmt -i "$idx" bondable off
  run mgmt -i "$idx" discov no
done <<< "$(all_indices)"
exit 0
