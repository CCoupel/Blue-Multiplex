#!/usr/bin/env bash
# Fonctions partagées des scripts du spike #5. À sourcer (. common.sh).
# Provisoire — à revalider avec dongle RTL8761B (Bluetooth interne du Pi 3).
#
# LIMITE : les appels `bluetoothctl`/`btmgmt` sans cible visent le contrôleur *par défaut*. Les scripts de ce
# dossier ne sont valables qu'avec UN SEUL contrôleur Bluetooth ; avec plusieurs, `warn_multi_controller` avertit
# (il faudrait alors `bluetoothctl select <MAC>`). `btmgmt` est, lui, ciblé par index via BTMUX_ADAPTER_MAC.
set -euo pipefail
SPIKE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "${BTMUX_ADAPTER_MAC:-}" ]; then
  echo "AVERTISSEMENT: BTMUX_ADAPTER_MAC non défini, MAC par défaut de pi-qualif (B8:27:EB:1A:2E:D6)" >&2
fi
export BTMUX_ADAPTER_MAC="${BTMUX_ADAPTER_MAC:-B8:27:EB:1A:2E:D6}"
OUT_DIR="${BTMUX_SPIKE_OUT:-$SPIKE_DIR/out}"
PYTHON="$(cd "$SPIKE_DIR/.." && pwd)/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3

# Index hciN de l'adaptateur portant BTMUX_ADAPTER_MAC (via D-Bus, jamais hci0 en dur).
adapter_index() { "$PYTHON" "$SPIKE_DIR/../common/resolve_adapter.py" --mac "$BTMUX_ADAPTER_MAC" --index; }
log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*"; }

# Avertit si plusieurs contrôleurs sont présents (bluetoothctl vise alors le contrôleur par défaut).
warn_multi_controller() {
  local n
  n=$(timeout 8 bluetoothctl list </dev/null | grep -c '^Controller' || true)
  if [ "${n:-0}" -gt 1 ]; then
    echo "AVERTISSEMENT: $n contrôleurs Bluetooth ; bluetoothctl vise le contrôleur par défaut, pas forcément $BTMUX_ADAPTER_MAC" >&2
  fi
}
