#!/usr/bin/env bash
# Fonctions partagées des scripts du spike #5. À sourcer (. common.sh).
# Provisoire — à revalider avec dongle RTL8761B (Bluetooth interne du Pi 3).
set -euo pipefail
SPIKE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BTMUX_ADAPTER_MAC="${BTMUX_ADAPTER_MAC:-B8:27:EB:1A:2E:D6}"
OUT_DIR="${BTMUX_SPIKE_OUT:-$SPIKE_DIR/out}"
PYTHON="$(cd "$SPIKE_DIR/.." && pwd)/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3

# Index hciN de l'adaptateur portant BTMUX_ADAPTER_MAC (via D-Bus, jamais hci0 en dur).
adapter_index() { "$PYTHON" "$SPIKE_DIR/../common/resolve_adapter.py" --mac "$BTMUX_ADAPTER_MAC" --index; }
log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*"; }
