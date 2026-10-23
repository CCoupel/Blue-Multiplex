#!/usr/bin/env bash
# Relève ce que l'adaptateur expose : enregistrements SDP locaux et UUIDs (ce que Windows peut voir).
# Usage : dump_sdp.sh [--btmon SECONDES]
#   sdptool browse local (si présent, déprécié -> R6) + bluetoothctl show ; avec --btmon, capture passive
#   btmon pendant N secondes (à lancer pendant l'appairage d'une source) -> out/btmon-<date>.{snoop,txt}
# Provisoire — à revalider avec dongle RTL8761B.
. "$(dirname "$0")/common.sh"
warn_multi_controller
BTMON_S=0
[ "${1:-}" = "--btmon" ] && BTMON_S="${2:?secondes}"
mkdir -p "$OUT_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"

log "bluetoothctl show -> $OUT_DIR/show-$stamp.txt"
timeout 8 bluetoothctl show </dev/null | tee "$OUT_DIR/show-$stamp.txt" | grep -E 'Name|Class|UUID'

if command -v sdptool >/dev/null; then
  log "sdptool browse local -> $OUT_DIR/sdp-$stamp.txt"
  # sdptool lit le socket SDP local : nécessite bluetoothd --compat, sinon échec (R6) -> repli ci-dessus.
  if sudo -n timeout 15 sdptool browse local >"$OUT_DIR/sdp-$stamp.txt" 2>&1; then
    grep -E '^Service Name|Service RecHandle|UUID 128|Profile Descriptor' "$OUT_DIR/sdp-$stamp.txt" | head -60
  else
    log "sdptool inutilisable (R6) : $(head -1 "$OUT_DIR/sdp-$stamp.txt")"
  fi
else
  log "sdptool absent (R6) : repli sur la liste d'UUIDs de bluetoothctl show"
fi

if [ "$BTMON_S" -gt 0 ]; then
  log "btmon passif ${BTMON_S}s (appairer la source maintenant)"
  sudo -n timeout "$BTMON_S" btmon -w "$OUT_DIR/btmon-$stamp.snoop" >/dev/null 2>&1 || true
  sudo -n btmon -r "$OUT_DIR/btmon-$stamp.snoop" >"$OUT_DIR/btmon-$stamp.txt" 2>&1 || true
  log "capture : $OUT_DIR/btmon-$stamp.snoop (+ .txt décodé) — SDP : grep -i 'SDP' "
fi
