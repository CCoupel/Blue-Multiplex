#!/bin/sh
# Configure l'utilisateur de service de btmuxd via un drop-in systemd (l'unite livree reste inchangee).
# Usage : btmux-set-user.sh <utilisateur>
# Variables (tests) : BTMUX_DROPIN_DIR (defaut /etc/systemd/system/btmuxd.service.d), BTMUX_UID (defaut id -u).
# Le service tourne sous cet utilisateur pour atteindre sa session PipeWire (decision D2) :
# linger requis (loginctl enable-linger <utilisateur>).
set -eu
user="${1:?usage: btmux-set-user.sh <utilisateur>}"
case "$user" in
  *[!a-z0-9_-]* | -* | "") echo "btmux-set-user: nom d'utilisateur invalide: $user" >&2; exit 2 ;;
esac
uid="${BTMUX_UID:-$(id -u "$user")}" || { echo "btmux-set-user: utilisateur inconnu: $user" >&2; exit 1; }
case "$uid" in
  0 | "" | *[!0-9]*) echo "btmux-set-user: uid $uid refuse (root ou invalide) pour $user" >&2; exit 2 ;;
esac
dir="${BTMUX_DROPIN_DIR:-/etc/systemd/system/btmuxd.service.d}"
mkdir -p "$dir"
cat > "$dir/user.conf" <<CONF
# Genere par btmux-set-user.sh — ne pas editer (relancer le script).
[Unit]
After=
After=bluetooth.service user@$uid.service dbus.service
Wants=
Wants=bluetooth.service user@$uid.service

[Service]
User=$user
Environment=
Environment=XDG_RUNTIME_DIR=/run/user/$uid
CONF
echo "btmux-set-user: btmuxd.service -> User=$user (uid $uid)"
