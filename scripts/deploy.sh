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
set -a; . "$ENV_FILE"; set +a
: "${SSH_KEY_PATH:?SSH_KEY_PATH absent de $ENV_FILE}" "${DEPLOY_HOST:?DEPLOY_HOST absent de $ENV_FILE}"

SSH_OPTS=(-i "$SSH_KEY_PATH" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
WHEEL_NAME="$(basename "$WHEEL")"
REMOTE_DIR="/tmp/btmux-deploy"

echo "== deploy $ENV_NAME -> $DEPLOY_HOST ($WHEEL_NAME)"
ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" "rm -rf $REMOTE_DIR && mkdir -p $REMOTE_DIR"
scp "${SSH_OPTS[@]}" -q "$WHEEL" systemd/btmuxd.service config/config.example.yaml "$DEPLOY_HOST:$REMOTE_DIR/"

# Script distant : lu depuis stdin (aucun fichier intermediaire), argument = nom de la wheel.
ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" bash -s -- "$REMOTE_DIR" "$WHEEL_NAME" <<'REMOTE'
set -euo pipefail
dir="$1"; wheel="$2"
sudo python3 -m venv --upgrade-deps /opt/btmux
sudo /opt/btmux/bin/pip install --quiet --upgrade "$dir/$wheel"
sudo install -d -m 755 /etc/btmux
sudo install -m 644 "$dir/config.example.yaml" /etc/btmux/config.example.yaml
if [ ! -f /etc/btmux/config.yaml ]; then
  sudo install -m 644 /etc/btmux/config.example.yaml /etc/btmux/config.yaml
  echo "deploy: /etc/btmux/config.yaml cree depuis l'exemple (a adapter : MAC du controleur)"
fi
sudo install -m 644 "$dir/btmuxd.service" /etc/systemd/system/btmuxd.service
sudo systemctl daemon-reload
sudo systemctl enable btmuxd.service >/dev/null 2>&1
sudo systemctl restart btmuxd.service
sleep 2
if systemctl is-active --quiet btmuxd.service; then
  echo "deploy: btmuxd.service actif"
else
  # v0.1.0 : le daemon valide la config puis sort 0 (non implemente) ; ce n'est pas une erreur.
  echo "deploy: btmuxd.service inactif ($(systemctl show -p Result --value btmuxd.service))" >&2
fi
/opt/btmux/bin/btmuxd --version
rm -rf "$dir"
REMOTE
echo "== deploy $ENV_NAME termine"
