#!/usr/bin/env bash
# Garde-fou de séance par contrôleur HCI (dongles USB btusb) : surveille dmesg et agit contrôleur par contrôleur.
# Usage : watch_hci.sh [--interval S] [--hci hciN]... [--rearm-pause S]     (sans --hci : tous les contrôleurs présents)
# Seuils, évalués séparément pour chaque hciN :
#   - dur  : toute NOUVELLE ligne `command … tx timeout`, `Opcode … failed: -110`, `link tx timeout`, `killing stalled connection`
#            de ce hciN, ou erreur USB de son port (`usb P: USB disconnect|reset|… `, `btusb P: … error|failed|timeout`) ;
#   - doux : >= 3 `Frame reassembly failed` / `Received unexpected HCI Event` / `ACL packet for unknown connection` en 30 s.
# Au déclenchement pour un hciN : journalise, arrête router.py (PID de out/router.pid, SIGINT), déconnecte les appareils ACL de CE
# contrôleur seulement, puis se ré-arme et continue. Relançable à tout moment ; jamais de `pkill -f`. Arrêt : `kill <pid>`.
# Variables (tests) : BTMUX_DMESG (défaut `sudo -n dmesg`), BTMUX_SYSFS (défaut /sys), BTMUX_HCITOOL (défaut hcitool),
#   BTMUX_BTCTL (défaut bluetoothctl), BTMUX_OUT (défaut ./out), BTMUX_REARM_PAUSE (défaut 31 s).
# Provisoire — à valider avec les dongles UB500 (T3.2b).
set -euo pipefail

INTERVAL=2 PAUSE="${BTMUX_REARM_PAUSE:-31}" HCIS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --interval) INTERVAL="${2:?secondes}"; shift 2 ;;
    --hci) HCIS+=("${2:?hciN}"); shift 2 ;;
    --rearm-pause) PAUSE="${2:?secondes}"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "watch_hci: option inconnue: $1" >&2; exit 2 ;;
  esac
done
DMESG="${BTMUX_DMESG:-sudo -n dmesg}"
SYSFS="${BTMUX_SYSFS:-/sys}"
HCITOOL="${BTMUX_HCITOOL:-hcitool}"
BTCTL="${BTMUX_BTCTL:-bluetoothctl}"
OUT_DIR="${BTMUX_OUT:-$(dirname "$0")/out}"

dm() { $DMESG "$@"; }
if [ "${#HCIS[@]}" -eq 0 ]; then
  for d in "$SYSFS"/class/bluetooth/hci*; do [ -e "$d" ] && HCIS+=("$(basename "$d")"); done
fi
[ "${#HCIS[@]}" -gt 0 ] || { echo "watch_hci: aucun contrôleur HCI trouvé" >&2; exit 1; }

usb_port() {   # hciN -> port USB (ex. 1-1.2), vide si le contrôleur n'est pas USB
  readlink -f "$SYSFS/class/bluetooth/$1/device" 2>/dev/null | grep -oE '[0-9]+-[0-9]+(\.[0-9]+)*' | tail -1 || true
}
hard_count() {   # hciN port
  local hci="$1" port="$2" n
  n="$(dm | grep -cE "$hci: (command 0x[0-9a-fA-F]+ tx timeout|Opcode 0x[0-9a-fA-F]+ failed: -110|link tx timeout|killing stalled connection)" || true)"
  if [ -n "$port" ]; then
    n=$((n + $(dm | grep -cE "(usb $port: (USB disconnect|reset |device descriptor read|device not accepting address|can't set config)|btusb $port.*(error|failed|timeout))" || true)))
  fi
  echo "$n"
}
soft_recent() {   # hciN -> nombre de lignes « douces » dans les 30 dernières secondes
  local since
  since="$(date -u -d '-30 sec' +%Y-%m-%dT%H:%M:%S)"
  dm --time-format iso | awk -v t="$since" -v h="$1:" \
    'index($0, h) && /Frame reassembly failed|Received unexpected HCI Event|ACL packet for unknown connection/ && substr($1, 1, 19) >= t' | wc -l
}
stop_router() {
  local pidfile="$OUT_DIR/router.pid" pid
  [ -f "$pidfile" ] || return 0
  pid="$(cat "$pidfile")"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && ps -o args= -p "$pid" | grep -q 'router\.py'; then
    kill -INT "$pid" || true
  fi
}
disconnect_hci() {
  local hci="$1" mac
  for mac in $("$HCITOOL" -i "$hci" con 2>/dev/null | awk '/ACL/ {print $3}'); do
    timeout 10 "$BTCTL" disconnect "$mac" </dev/null || true
  done
}

declare -A PORT BASE
for h in "${HCIS[@]}"; do
  PORT[$h]="$(usb_port "$h")"
  BASE[$h]="$(hard_count "$h" "${PORT[$h]}")"
  echo "$(date -u +%FT%TZ) watch_hci : $h port USB='${PORT[$h]}' base dur=${BASE[$h]} (seuils : 1 dur, ou 3 doux/30 s)"
done
while sleep "$INTERVAL"; do
  for h in "${HCIS[@]}"; do
    reason=""
    now="$(hard_count "$h" "${PORT[$h]}")"
    [ "$now" -gt "${BASE[$h]}" ] && reason="erreur dure"
    [ -z "$reason" ] && [ "$(soft_recent "$h")" -ge 3 ] && reason=">= 3 erreurs de trame en 30 s"
    if [ -n "$reason" ]; then
      echo "$(date -u +%FT%TZ) ALERTE $h ($reason) — ARRÊT DE LA SÉANCE sur ce contrôleur"
      dm | grep -E "$h:|usb ${PORT[$h]:-no-port}" | tail -6 || true
      stop_router
      disconnect_hci "$h"
      BASE[$h]="$(hard_count "$h" "${PORT[$h]}")"
      echo "$(date -u +%FT%TZ) watch_hci ré-armé pour $h : base dur=${BASE[$h]}"
      sleep "$PAUSE"
    fi
  done
done
