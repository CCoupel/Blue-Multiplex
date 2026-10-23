#!/usr/bin/env bash
# Garde-fou de séance : surveille dmesg et signale (et sort avec le code 3) à la première erreur UART HCI.
# Usage : watch_uart.sh [intervalle_s]  — à lancer en arrière-plan avant toute connexion BT du spike #7.
# Le Pi 3 en Bluetooth interne a déjà figé deux fois (UART saturé) : au premier signal, arrêter le routeur,
# déconnecter les appareils (`bluetoothctl disconnect`), consigner, redémarrer le Pi si `hci0` ne répond plus.
# (Boucle de surveillance : la source n'émet pas d'événement exploitable ici, dmesg est un tampon.)
# Provisoire — à revalider avec dongle RTL8761B.
set -euo pipefail
INTERVAL="${1:-3}"
count() { sudo -n dmesg | grep -cE 'Frame reassembly|tx timeout|killing stalled connection' || true; }
base="$(count)"
echo "$(date -u +%FT%TZ) watch_uart : base=$base erreurs, intervalle ${INTERVAL}s"
while sleep "$INTERVAL"; do
  now="$(count)"
  if [ "$now" -gt "$base" ]; then
    echo "$(date -u +%FT%TZ) ALERTE UART : $((now - base)) nouvelle(s) erreur(s) HCI — ARRÊTER LA SÉANCE"
    sudo -n dmesg | grep -E 'hci0' | tail -5
    exit 3
  fi
done
