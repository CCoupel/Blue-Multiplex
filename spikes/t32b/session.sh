#!/usr/bin/env bash
# Orchestration d'une séance bi-adaptateur (T3.2b) : S1 (identité, rôles, exposition, routage) ou S2 (voix #6, latence #8).
# Usage : session.sh s1|s2 [--dry-run] [--window SECONDES]   |   session.sh stop
#   démarre : preflight, watch_hci.sh (1 garde-fou par contrôleur), link_guard.py (plafond de liens), agent.py (fenêtre d'appairage
#   pilotée par out/window.open) ; les PID sont dans out/*.pid (arrêt par `session.sh stop`, jamais de `pkill -f`).
#   --dry-run : affiche ce qui serait lancé, sans rien démarrer (utilisable sans matériel).
# btmuxd résident (LOT-3) : si le daemon est actif, AUCUN agent d'appairage n'est lancé (un seul agent BlueZ : celui de btmuxd) ;
#   la fenêtre d'appairage se pilote par `btmuxctl pairing open sources|headsets [s]` / `pairing close` (--window N l'ouvre sur `sources`).
#   BTMUX_SPIKE_AGENT=1 force l'ancien agent (btmuxd arrêté seulement). link_guard.py reste le seul à bloquer un appareil (le daemon ne bloque pas).
# Provisoire — à valider avec les dongles UB500 (T3.2b).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$HERE/../common"
OUT="${BTMUX_OUT:-$HERE/out}"
mkdir -p "$OUT"
PY="${BTMUX_SPIKE_PYTHON:-$HERE/../.venv/bin/python}"
[ -x "$PY" ] || PY=python3

cmd="${1:?usage: session.sh s1|s2|stop [--dry-run]}"; shift || true
DRY=0 WINDOW=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --window) WINDOW="${2:?secondes}"; shift 2 ;;
    *) echo "option inconnue: $1" >&2; exit 2 ;;
  esac
done

CTL="${BTMUXCTL:-$(command -v btmuxctl || echo /opt/btmux/bin/btmuxctl)}"
DAEMON=0; [ "$(systemctl is-active btmuxd 2>/dev/null)" = active ] && DAEMON=1
[ "${BTMUX_SPIKE_AGENT:-0}" = 1 ] && [ "$DAEMON" = 1 ] && { echo "refus : BTMUX_SPIKE_AGENT=1 alors que btmuxd est actif (deux agents)" >&2; exit 2; }

stop_all() {
  local f pid
  if [ "$DRY" = 0 ] && [ -e "$OUT/window.btmuxctl" ]; then "$CTL" pairing close >/dev/null 2>&1 || true; rm -f "$OUT/window.btmuxctl"; echo "fenêtre d'appairage fermée (btmuxctl)"; fi
  for f in "$OUT"/*.pid; do
    [ -e "$f" ] || continue
    pid="$(cat "$f")"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null || true; echo "arrêté $(basename "$f" .pid) ($pid)"; fi
    rm -f "$f"
  done
  rm -f "$OUT/window.open"
}
launch() {   # nom commande...
  local name="$1"; shift
  if [ "$DRY" = 1 ]; then echo "DRY-RUN: $*  (> $OUT/$name.log)"; return; fi
  nohup "$@" >> "$OUT/$name.log" 2>&1 < /dev/null &
  echo $! > "$OUT/$name.pid"
  echo "démarré $name (pid $!)"
}

case "$cmd" in
  stop) stop_all; exit 0 ;;
  s1|s2) ;;
  *) echo "usage: session.sh s1|s2|stop [--dry-run]" >&2; exit 2 ;;
esac

echo "== Séance $cmd — préflight =="
if [ "$DRY" = 1 ]; then echo "DRY-RUN: $HERE/preflight.sh"; else "$HERE/preflight.sh" || { echo "préflight en échec : séance non démarrée"; exit 1; }; fi
echo "== Garde-fous =="
launch watch_hci "$COMMON/watch_hci.sh" --interval 2
launch link_guard "$PY" "$COMMON/link_guard.py" --cap sources=2 --cap headsets=1
if [ "$DAEMON" = 1 ]; then
  echo "btmuxd actif : pas d'agent d'appairage dans les spikes (fenêtre : $CTL pairing open sources|headsets [s])"
  if [ "$WINDOW" -gt 0 ]; then
    if [ "$DRY" = 1 ]; then echo "DRY-RUN: $CTL pairing open sources $WINDOW"; else "$CTL" pairing open sources "$WINDOW" && touch "$OUT/window.btmuxctl"; fi
  fi
else
  [ "$DRY" = 1 ] || { [ "$WINDOW" -gt 0 ] && touch "$OUT/window.open"; } || true
  launch agent "$PY" "$COMMON/agent.py" --window-file "$OUT/window.open"
fi
case "$cmd" in
  s1)
    cat <<TXT
== S1 : identité, rôles, exposition, routage ==
 1. Fenêtre d'appairage   : $CTL pairing open sources 300   (fermer : $CTL pairing close)
 2. Identité (#12)        : bluetoothctl list ; $COMMON/resolve_adapter.py --role sources|headsets --index
 3. Rôles/profils (#13)   : $COMMON/../t32b/roles_report.sh  (SDP/profils par carte) ; ajuster $COMMON/../../config/wireplumber/roles.conf
 4. Routage (#7)          : $HERE/../07-routing/router.py --sink @hci1:Audio/Sink --a @hci0:Stream/Output/Audio --virtual-b --cycles 10
 5. Clôture               : $0 stop
TXT
    ;;
  s2)
    cat <<TXT
== S2 : voix (#6) et latence double saut (#8) ==
 1. Inventaire téléphonie : $HERE/telephony_inventory.sh
 2. Capacité SCO          : $HERE/sco_capacity.sh 600
 3. Liens de voix         : $HERE/voice_links.py --pc-in SPEC --hs-out SPEC --hs-in SPEC --pc-out SPEC
 4. Bascules A2DP<->HFP   : $HERE/profile_watch.py --match <MAC_PC_avec_underscores> --out out/profile.json
 5. Latence double saut   : $HERE/impulse_track.py … puis $HERE/analyze_latency.py enregistrement.wav (protocole : README)
 6. Dropouts 30 min       : $HERE/xrun_log.py --minutes 30
 7. Clôture               : $0 stop
TXT
    ;;
esac
