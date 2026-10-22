#!/usr/bin/env bash
# Installe la wheel btmux sur le Pi de l'environnement donne (BORE : aucun build, aucune publication).
# Usage : scripts/deploy.sh <env> <wheel>      ex. scripts/deploy.sh qualif build/qualif_v0.1.0/btmux-0.1.0.1-py3-none-any.whl
# Lit .claude/agents/environments/<env>.env : SSH_KEY_PATH, DEPLOY_HOST (user@host).
# Idempotent : relancable a l'identique. Ne remplace jamais /etc/btmux/config.yaml s'il existe.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_NAME="${1:?usage: deploy.sh <env> <wheel>}"
WHEEL="${2:?usage: deploy.sh <env> <wheel>}"
ENV_FILE=".claude/agents/environments/${ENV_NAME}.env"

[ -f "$WHEEL" ] || { echo "deploy: wheel introuvable: $WHEEL" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "deploy: $ENV_FILE absent (modele: ${ENV_NAME}.env.example)" >&2; exit 1; }
[ -f systemd/btmuxd.service ] && [ -f config/config.example.yaml ] \
  || { echo "deploy: systemd/btmuxd.service ou config/config.example.yaml absent" >&2; exit 1; }

# shellcheck disable=SC1090
# tr -d '\r' : tolere un .env ecrit avec des fins de ligne CRLF (edite sous Windows)
set -a; . <(tr -d '\r' < "$ENV_FILE"); set +a
: "${SSH_KEY_PATH:?SSH_KEY_PATH absent de $ENV_FILE}" "${DEPLOY_HOST:?DEPLOY_HOST absent de $ENV_FILE}"

SSH_OPTS=(-i "$SSH_KEY_PATH" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
WHEEL_NAME="$(basename "$WHEEL")"

echo "== deploy $ENV_NAME -> $DEPLOY_HOST ($WHEEL_NAME)"
REMOTE_DIR=$(ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" "mktemp -d /tmp/btmux-deploy.XXXXXX")
scp "${SSH_OPTS[@]}" -q "$WHEEL" systemd/btmuxd.service config/config.example.yaml "$DEPLOY_HOST:$REMOTE_DIR/"

# Script distant : lu depuis stdin (aucun fichier intermediaire), argument = nom de la wheel.
ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" bash -s -- "$REMOTE_DIR" "$WHEEL_NAME" <<'REMOTE'
set -euo pipefail
dir="$1"; wheel="$2"
trap 'rm -rf "$dir"' EXIT
# Prerequis cote Pi : python >= 3.12 (requires-python) et python3-venv (ensurepip)
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
  || { echo "deploy: python3 >= 3.12 requis, trouve $(python3 --version 2>&1)" >&2; exit 1; }
if ! dpkg -s python3-venv >/dev/null 2>&1; then
  echo "deploy: installation de python3-venv"
  sudo apt-get install -y python3-venv || { sudo apt-get update && sudo apt-get install -y python3-venv; }
fi
# Venv a moitie cree par un echec precedent (pas de pip) : on le recree
if [ -e /opt/btmux ] && [ ! -x /opt/btmux/bin/pip ]; then
  echo "deploy: /opt/btmux incomplet, recreation"
  sudo rm -rf /opt/btmux
fi
sudo python3 -m venv --upgrade-deps /opt/btmux
sudo /opt/btmux/bin/pip install --quiet --upgrade "$dir/$wheel"   # wheel + dependances
sudo /opt/btmux/bin/pip install --quiet --force-reinstall --no-deps "$dir/$wheel"   # redeploiement meme version effectif
sudo install -d -m 755 /etc/btmux
sudo install -m 644 "$dir/config.example.yaml" /etc/btmux/config.example.yaml
if [ ! -f /etc/btmux/config.yaml ]; then
  sudo install -m 644 /etc/btmux/config.example.yaml /etc/btmux/config.yaml
  echo "deploy: /etc/btmux/config.yaml cree depuis l'exemple (a adapter : MAC du controleur)"
fi
sudo install -m 644 "$dir/btmuxd.service" /etc/systemd/system/btmuxd.service
sudo systemctl daemon-reload
sudo systemctl enable btmuxd.service
sudo systemctl restart btmuxd.service
sleep 2
if ! systemctl is-active --quiet btmuxd.service; then
  echo "deploy: btmuxd.service inactif ($(systemctl show -p Result --value btmuxd.service))" >&2
  journalctl -u btmuxd.service -n 20 --no-pager >&2 || true
  exit 1
fi
echo "deploy: btmuxd.service actif"
/opt/btmux/bin/btmuxd --version
REMOTE
echo "== deploy $ENV_NAME termine"
