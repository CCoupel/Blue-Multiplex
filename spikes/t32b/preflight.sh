#!/usr/bin/env bash
# Vérifications avant une séance bi-adaptateur (S1/S2) — lecture seule, aucune connexion BT.
# Usage : preflight.sh [--config /etc/btmux/config.yaml]     Code 0 = prêt ; 1 = au moins un contrôle en échec.
# Provisoire — à valider avec les dongles UB500 (T3.2b).
set -uo pipefail
CONFIG=/etc/btmux/config.yaml
[ "${1:-}" = "--config" ] && CONFIG="${2:?chemin}"
EXPECT_HOST="${BTMUX_EXPECT_HOST:-pi-qualif}"
fail=0
ok() { echo "OK    $*"; }
ko() { echo "ECHEC $*"; fail=1; }
warn() { echo "AVERT $*"; }

[ "$(hostname)" = "$EXPECT_HOST" ] && ok "hostname $EXPECT_HOST" || ko "hostname $(hostname) (attendu $EXPECT_HOST)"
ip -4 -br addr 2>/dev/null | grep -q '192\.168\.1\.176' && ko "adresse 192.168.1.176 (machine interdite)" || ok "pas la machine interdite"
n=$(lsusb 2>/dev/null | grep -c '2357:0604' || true); [ "$n" -eq 2 ] && ok "2 dongles UB500" || ko "dongles UB500 : $n (2 attendus)"
hc="$(timeout 8 hciconfig -a 2>/dev/null || true)"
[ "$(printf '%s\n' "$hc" | grep -c 'Bus: USB')" -eq 2 ] && ok "2 contrôleurs sur le bus USB" || ko "contrôleurs USB != 2"
[ "$(printf '%s\n' "$hc" | grep -c 'Bus: UART')" -eq 0 ] && ok "0 contrôleur UART" || ko "contrôleur UART présent (Bluetooth interne actif)"
grep -q '^dtoverlay=disable-bt' /boot/firmware/config.txt 2>/dev/null && ok "disable-bt posé" || ko "disable-bt absent"
[ "$(hcitool con 2>/dev/null | grep -c ACL || true)" -eq 0 ] && ok "0 lien ACL au départ" || ko "des liens ACL existent déjà"
[ "$(sudo -n dmesg 2>/dev/null | grep -cE 'tx timeout|Frame reassembly|killing stalled' || true)" -eq 0 ] && ok "dmesg sans erreur HCI" || warn "dmesg contient déjà des erreurs HCI (noter la base)"
[ -f "$CONFIG" ] && ok "config $CONFIG" || ko "config $CONFIG absente"
if [ -x /usr/lib/btmux/btmux-adapters.sh ] || [ -x "$(dirname "$0")/../../scripts/btmux-adapters.sh" ]; then
  script=/usr/lib/btmux/btmux-adapters.sh; [ -x "$script" ] || script="$(dirname "$0")/../../scripts/btmux-adapters.sh"
  plan="$("$script" --config "$CONFIG" --dry-run --wait 0 2>&1 || true)"
  [ "$(printf '%s\n' "$plan" | grep -c -- ' -> hci')" -eq 2 ] && ok "les 2 MAC de la config sont présentes" || ko "adaptateurs de la config introuvables : $plan"
else ko "btmux-adapters.sh introuvable"; fi
[ "$(cat /sys/class/net/eth0/carrier 2>/dev/null || echo 0)" = 1 ] && ok "Ethernet branché" || warn "Ethernet sans porteuse (mesures : Ethernet + disable-wifi recommandés)"
ip -br link 2>/dev/null | grep -q '^wlan' && warn "interface wlan présente (disable-wifi non posé)" || ok "pas de Wi-Fi"
systemctl --user is-active --quiet wireplumber 2>/dev/null && ok "wireplumber actif" || ko "wireplumber inactif"
exit $fail
