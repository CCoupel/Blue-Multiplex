#!/usr/bin/env bash
# Garde-fou de séance : surveille dmesg (Bluetooth interne du Pi 3, UART saturable).
# Usage : watch_uart.sh [intervalle_s]  — à lancer en arrière-plan avant toute connexion BT du spike #7.
# Seuils d'arrêt (décision du 2026-10-23) :
#   - toute NOUVELLE erreur `tx timeout` / `killing stalled connection` depuis l'armement ;
#   - OU >= 3 `Frame reassembly failed` dans les 30 dernières secondes.
# Au déclenchement : journalise, arrête router.py (PID lu dans out/router.pid, SIGINT : il détruit ses sources
# virtuelles), arrête les `pw-play` (nom exact), déconnecte les appareils BT connectés, puis **se ré-arme** (nouvelles bases)
# et continue de surveiller. Arrêt du garde-fou : `kill <pid>`.
# Une erreur de trame isolée (ex. à l'établissement du 2e lien) est seulement consignée.
# Variables (tests) : BTMUX_DMESG (défaut `sudo -n dmesg`), BTMUX_BTCTL (défaut `bluetoothctl`), BTMUX_OUT (défaut ./out),
# BTMUX_REARM_PAUSE (défaut 31 s).
# (Boucle de surveillance : dmesg est un tampon, pas une source d'événements exploitable ici.)
# Provisoire — à revalider avec dongle RTL8761B.
set -euo pipefail
INTERVAL="${1:-2}"
DMESG="${BTMUX_DMESG:-sudo -n dmesg}"
BTCTL="${BTMUX_BTCTL:-bluetoothctl}"
OUT_DIR="${BTMUX_OUT:-$(dirname "$0")/out}"

dm() { $DMESG "$@"; }
hard() { dm | grep -cE 'tx timeout|killing stalled connection' || true; }
frames_total() { dm | grep -c 'Frame reassembly' || true; }
frames30() {
  local since
  since="$(date -u -d '-30 sec' +%Y-%m-%dT%H:%M:%S)"
  dm --time-format iso | awk -v t="$since" '/Frame reassembly/ && substr($1, 1, 19) >= t' | wc -l
}
stop_router() {
  local pidfile="$OUT_DIR/router.pid" pid
  [ -f "$pidfile" ] || return 0
  pid="$(cat "$pidfile")"
  # Cible uniquement le PID enregistré, et seulement si c'est bien router.py (jamais de `pkill -f`).
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && ps -o args= -p "$pid" | grep -q 'router\.py'; then
    kill -INT "$pid" || true
  fi
}

base_hard="$(hard)"
last_frames="$(frames_total)"
echo "$(date -u +%FT%TZ) watch_uart : base tx-timeout/stalled=$base_hard, frame-reassembly=$last_frames (seuils : 1 timeout, ou 3 frames/30 s ; ré-armement automatique)"
while sleep "$INTERVAL"; do
  now_hard="$(hard)"
  now_frames="$(frames_total)"
  if [ "$now_frames" -gt "$last_frames" ]; then
    echo "$(date -u +%FT%TZ) info : $((now_frames - last_frames)) Frame reassembly failed (total $now_frames)"
    last_frames="$now_frames"
  fi
  reason=""
  [ "$now_hard" -gt "$base_hard" ] && reason="tx timeout / stalled connection"
  [ -z "$reason" ] && [ "$(frames30)" -ge 3 ] && reason=">= 3 Frame reassembly en 30 s"
  if [ -n "$reason" ]; then
    echo "$(date -u +%FT%TZ) ALERTE UART ($reason) — ARRÊT DE LA SÉANCE"
    dm | grep -E 'hci0' | tail -6 || true
    stop_router
    pkill -x pw-play || true
    for mac in $(timeout 8 $BTCTL devices Connected </dev/null | awk '{print $2}'); do
      timeout 10 $BTCTL disconnect "$mac" </dev/null || true
    done
    base_hard="$(hard)"
    last_frames="$(frames_total)"
    echo "$(date -u +%FT%TZ) watch_uart ré-armé : base tx-timeout/stalled=$base_hard, frame-reassembly=$last_frames"
    sleep "${BTMUX_REARM_PAUSE:-31}"  # laisse sortir de la fenêtre glissante de 30 s avant de réévaluer
  fi
done
