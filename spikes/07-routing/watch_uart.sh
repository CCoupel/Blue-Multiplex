#!/usr/bin/env bash
# Garde-fou de séance : surveille dmesg (Bluetooth interne du Pi 3, UART saturable).
# Usage : watch_uart.sh [intervalle_s]  — à lancer en arrière-plan avant toute connexion BT du spike #7.
# Seuils d'arrêt (décision du 2026-10-23) :
#   - toute NOUVELLE erreur `tx timeout` / `killing stalled connection` depuis le démarrage ;
#   - OU >= 3 `Frame reassembly failed` dans les 30 dernières secondes.
# Au déclenchement : journalise, déconnecte les appareils BT connectés, arrête router.py/pw-play et sort (code 3).
# Une erreur de trame isolée (ex. à l'établissement du 2e lien) est seulement consignée.
# (Boucle de surveillance : dmesg est un tampon, pas une source d'événements exploitable ici.)
# Provisoire — à revalider avec dongle RTL8761B.
set -euo pipefail
INTERVAL="${1:-2}"
hard() { sudo -n dmesg | grep -cE 'tx timeout|killing stalled connection' || true; }
frames30() {
  local since
  since="$(date -u -d '-30 sec' +%Y-%m-%dT%H:%M:%S)"
  sudo -n dmesg --time-format iso | awk -v t="$since" '/Frame reassembly/ && substr($1, 1, 19) >= t' | wc -l
}
base_hard="$(hard)"
base_frames="$(sudo -n dmesg | grep -c 'Frame reassembly' || true)"
echo "$(date -u +%FT%TZ) watch_uart : base tx-timeout/stalled=$base_hard, frame-reassembly=$base_frames (seuils : 1 timeout, ou 3 frames/30 s)"
last_frames="$base_frames"
while sleep "$INTERVAL"; do
  now_hard="$(hard)"
  now_frames="$(sudo -n dmesg | grep -c 'Frame reassembly' || true)"
  if [ "$now_frames" -gt "$last_frames" ]; then
    echo "$(date -u +%FT%TZ) info : $((now_frames - last_frames)) Frame reassembly failed (total $now_frames)"
    last_frames="$now_frames"
  fi
  reason=""
  [ "$now_hard" -gt "$base_hard" ] && reason="tx timeout / stalled connection"
  [ -z "$reason" ] && [ "$(frames30)" -ge 3 ] && reason=">= 3 Frame reassembly en 30 s"
  if [ -n "$reason" ]; then
    echo "$(date -u +%FT%TZ) ALERTE UART ($reason) — ARRÊT DE LA SÉANCE"
    sudo -n dmesg | grep -E 'hci0' | tail -6
    pkill -x pw-play || true
    pkill -f 'router.py' || true
    for mac in $(timeout 8 bluetoothctl devices Connected </dev/null | awk '{print $2}'); do
      timeout 10 bluetoothctl disconnect "$mac" </dev/null || true
    done
    exit 3
  fi
done
