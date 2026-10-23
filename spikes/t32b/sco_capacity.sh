#!/usr/bin/env bash
# Capacité SCO/eSCO (#6) : échantillonne `hcitool con` de chaque contrôleur et retient le maximum de liens synchrones simultanés.
# Usage : sco_capacity.sh [durée_s] (défaut 300) — pendant que l'utilisateur ouvre/ferme des appels. Sortie : out/sco-capacity.txt.
# Provisoire — à valider avec les dongles UB500 (T3.2b).
set -uo pipefail
DUR="${1:-300}"
OUT="$(dirname "$0")/out/sco-capacity.txt"
mkdir -p "$(dirname "$OUT")"
declare -A MAX
end=$((SECONDS + DUR))
{
  echo "# $(date -u +%FT%TZ) échantillonnage 1 s pendant ${DUR}s"
  while [ "$SECONDS" -lt "$end" ]; do
    for h in $(hciconfig 2>/dev/null | awk -F: '/^hci/ {print $1}'); do
      n=$(hcitool -i "$h" con 2>/dev/null | grep -cE 'SCO|eSCO' || true)
      [ "${n:-0}" -gt "${MAX[$h]:-0}" ] && { MAX[$h]=$n; echo "$(date -u +%T) $h : $n lien(s) synchrone(s) simultané(s) (nouveau max)"; }
    done
    sleep 1
  done
  for h in "${!MAX[@]}"; do echo "MAX $h = ${MAX[$h]}"; done
} | tee "$OUT"
