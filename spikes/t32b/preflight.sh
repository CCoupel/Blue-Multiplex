#!/usr/bin/env bash
# Vérifications avant une séance bi-adaptateur (S1/S2) — lecture seule, aucune connexion BT.
# Usage : preflight.sh [--config /etc/btmux/config.yaml]     Code 0 = prêt ; 1 = au moins un contrôle en échec.
# btmuxd résident (LOT-3) : le préflight vérifie que le daemon tourne et que l'API voit les 2 contrôleurs ; les liens ACL déjà
# présents (appareil connecté en usage normal) sont signalés (AVERT) et à NOTER, pas bloquants.
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
[ "$(hostname)" = "piClock" ] && ko "machine interdite (piClock)" || ok "pas la machine interdite"
n=$(lsusb 2>/dev/null | grep -c '2357:0604' || true); [ "$n" -eq 2 ] && ok "2 dongles UB500" || ko "dongles UB500 : $n (2 attendus)"
hc="$(timeout 8 hciconfig -a 2>/dev/null || true)"
[ "$(printf '%s\n' "$hc" | grep -c 'Bus: USB')" -eq 2 ] && ok "2 contrôleurs sur le bus USB" || ko "contrôleurs USB != 2"
[ "$(printf '%s\n' "$hc" | grep -c 'Bus: UART')" -eq 0 ] && ok "0 contrôleur UART" || ko "contrôleur UART présent (Bluetooth interne actif)"
grep -q '^dtoverlay=disable-bt' /boot/firmware/config.txt 2>/dev/null && ok "disable-bt posé" || ko "disable-bt absent"
acl="$(hcitool con 2>/dev/null | grep -c ACL || true)"
[ "$acl" -eq 0 ] && ok "0 lien ACL au départ" || warn "$acl lien(s) ACL déjà actif(s) (appareil en usage : le noter, ne pas le déconnecter sans le consigner)"
[ "$(sudo -n dmesg 2>/dev/null | grep -cE 'tx timeout|Frame reassembly|killing stalled' || true)" -eq 0 ] && ok "dmesg sans erreur HCI" || warn "dmesg contient déjà des erreurs HCI (noter la base)"
[ -f "$CONFIG" ] && ok "config $CONFIG" || ko "config $CONFIG absente"
if [ -x /usr/lib/btmux/btmux-adapters.sh ] || [ -x "$(dirname "$0")/../../scripts/btmux-adapters.sh" ]; then
  script=/usr/lib/btmux/btmux-adapters.sh; [ -x "$script" ] || script="$(dirname "$0")/../../scripts/btmux-adapters.sh"
  plan="$("$script" --config "$CONFIG" --dry-run --wait 0 2>&1 || true)"
  [ "$(printf '%s\n' "$plan" | grep -c -- ' -> hci')" -eq 2 ] && ok "les 2 MAC de la config sont présentes" || ko "adaptateurs de la config introuvables : $plan"
else ko "btmux-adapters.sh introuvable"; fi
[ "$(cat /sys/class/net/eth0/carrier 2>/dev/null || echo 0)" = 1 ] && ok "Ethernet branché" || warn "Ethernet sans porteuse (D2 : Wi-Fi conservé, à consigner)"
ip -br link 2>/dev/null | grep -q '^wlan' && warn "Wi-Fi actif (décision D2 LOT-3 : consigné dans les rapports, mesures 2,4 GHz pessimistes)" || ok "pas de Wi-Fi"
systemctl --user is-active --quiet wireplumber 2>/dev/null && ok "wireplumber actif" || ko "wireplumber inactif"
# btmuxd résident + API : 2 contrôleurs présents (jamais d'agent d'appairage concurrent dans les spikes)
if [ "$(systemctl is-active btmuxd 2>/dev/null)" = active ]; then
  ok "btmuxd actif"
  ctl="${BTMUXCTL:-$(command -v btmuxctl || echo /opt/btmux/bin/btmuxctl)}"
  json="$("$ctl" controllers 2>&1 || true)"
  summary="$(printf '%s' "$json" | python3 -c 'import json,sys
d=json.load(sys.stdin); c=d["controllers"]
print(len([x for x in c if x.get("present")]), d["roles"].get("pending"))' 2>/dev/null || true)"
  [ "${summary%% *}" = 2 ] && ok "API : 2 contrôleurs présents" || ko "API /api/controllers : contrôleurs présents != 2 (${summary:-réponse illisible})"
  [ "${summary##* }" = False ] && ok "aucun changement de rôles en attente" || warn "changement de rôles en attente (${summary##* })"
else ko "btmuxd inactif (les spikes coexistent avec le daemon résident)"; fi
# Sous-tension : vcgencmd si disponible, sinon hwmon rpi_volt (Pi 4 Ubuntu : /dev/vcio absent)
if thr="$(vcgencmd get_throttled 2>/dev/null)" && [ -n "$thr" ]; then
  [ "${thr#*=}" = 0x0 ] && ok "get_throttled 0x0" || ko "sous-tension/bridage : $thr"
else
  alarm=""; for h in /sys/class/hwmon/hwmon*; do [ "$(cat "$h/name" 2>/dev/null)" = rpi_volt ] && alarm="$(cat "$h"/in0_lcrit_alarm 2>/dev/null)"; done
  case "$alarm" in 0) ok "hwmon rpi_volt : pas de sous-tension" ;; "") warn "ni vcgencmd ni hwmon rpi_volt : sous-tension non vérifiable" ;; *) ko "hwmon rpi_volt : sous-tension (alarm=$alarm)" ;; esac
  [ "$(sudo -n dmesg 2>/dev/null | grep -ciE 'under-voltage|undervoltage' || true)" -eq 0 ] && ok "dmesg sans sous-tension" || ko "dmesg : sous-tension détectée"
fi
exit $fail
