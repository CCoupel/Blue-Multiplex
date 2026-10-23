#!/usr/bin/env bash
# À lancer APRÈS un redémarrage du Pi : les appairages sont-ils conservés (Paired/Trusted) et les sources
# se reconnectent-elles seules ? Usage : reboot_check.sh [--wait SECONDES]   (défaut 120)
# Sortie : tableau par appareil appairé + délai de reconnexion ; copie dans out/reboot-<date>.txt.
# Provisoire — à revalider avec dongle RTL8761B.
. "$(dirname "$0")/common.sh"
warn_multi_controller
WAIT=120
[ "${1:-}" = "--wait" ] && WAIT="${2:?secondes}"
[[ "$WAIT" =~ ^[0-9]+$ ]] || { echo "--wait attend un entier" >&2; exit 2; }
mkdir -p "$OUT_DIR"
exec > >(tee "$OUT_DIR/reboot-$(date +%Y%m%d-%H%M%S).txt") 2>&1

log "uptime: $(uptime -p) — adaptateur $BTMUX_ADAPTER_MAC = hci$(adapter_index)"
timeout 8 bluetoothctl show </dev/null | grep -E 'Name|Alias|Class|Powered|Discoverable|Pairable'
info() { timeout 8 bluetoothctl info "$1" </dev/null 2>&1; }
field() { info "$1" | awk -F': ' -v k="$2" '$1 ~ "^[[:space:]]*"k"$" {print $2}'; }

mapfile -t macs < <(timeout 8 bluetoothctl devices Paired </dev/null | awk '/^Device/ {print $2}')
if [ "${#macs[@]}" -eq 0 ]; then
  log "ECHEC : aucun appareil appairé conservé après le redémarrage"; exit 1
fi
declare -A seen
start=$SECONDS
printf '%-19s %-22s %-7s %-8s %s\n' MAC NOM PAIRED TRUSTED CONNECTED_APRES
while :; do
  pending=0
  for m in "${macs[@]}"; do
    [ -n "${seen[$m]:-}" ] && continue
    if [ "$(field "$m" Connected)" = yes ]; then seen[$m]=$((SECONDS - start)); else pending=1; fi
  done
  { [ "$pending" = 0 ] || [ $((SECONDS - start)) -ge "$WAIT" ]; } && break
  sleep 3
done
rc=0
for m in "${macs[@]}"; do
  name="$(field "$m" Name)"
  if [ -n "${seen[$m]:-}" ]; then after="${seen[$m]}s"; else after="non reconnecté (${WAIT}s)"; rc=1; fi
  printf '%-19s %-22s %-7s %-8s %s\n' "$m" "${name:0:22}" "$(field "$m" Paired)" "$(field "$m" Trusted)" "$after"
done
exit $rc
