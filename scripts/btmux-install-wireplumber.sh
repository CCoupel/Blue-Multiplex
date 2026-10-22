#!/bin/sh
# Installe la configuration WirePlumber headless de btmux dans le home de l'utilisateur de service.
# Usage : btmux-install-wireplumber.sh <utilisateur> <fichier.conf>
# N'écrase jamais un fichier existant ; redémarre wireplumber (session utilisateur) seulement si le fichier
# vient d'être créé. Variables (tests) : BTMUX_HOME (home de l'utilisateur), BTMUX_NO_RESTART=1.
set -eu
user="${1:?usage: btmux-install-wireplumber.sh <utilisateur> <fichier.conf>}"
src="${2:?fichier.conf}"
case "$user" in
  *[!a-z0-9_-]* | -* | "" | root) echo "btmux-wireplumber: utilisateur invalide: $user" >&2; exit 2 ;;
esac
[ -f "$src" ] || { echo "btmux-wireplumber: fichier introuvable: $src" >&2; exit 1; }
home="${BTMUX_HOME:-$(getent passwd "$user" | cut -d: -f6)}"
[ -n "$home" ] && [ -d "$home" ] || { echo "btmux-wireplumber: home introuvable pour $user" >&2; exit 1; }
dest_dir="$home/.config/wireplumber/wireplumber.conf.d"
dest="$dest_dir/51-btmux-no-seat.conf"
if [ -e "$dest" ]; then
  echo "btmux-wireplumber: $dest existe déjà, conservé"
  exit 0
fi
if [ "$(id -u)" -eq 0 ] && [ -z "${BTMUX_HOME:-}" ]; then
  # Création sous l'identité de l'utilisateur (propriété correcte des répertoires).
  su -s /bin/sh "$user" -c "mkdir -p '$dest_dir' && cp '$src' '$dest' && chmod 644 '$dest'"
else
  mkdir -p "$dest_dir" && cp "$src" "$dest" && chmod 644 "$dest"
fi
echo "btmux-wireplumber: $dest installé"
if [ "${BTMUX_NO_RESTART:-0}" != 1 ]; then
  uid="$(id -u "$user" 2>/dev/null || echo)"
  if [ -n "$uid" ] && [ -d "/run/user/$uid" ]; then
    if [ "$(id -u)" -eq 0 ]; then
      runuser -u "$user" -- env XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user restart wireplumber \
        || echo "btmux-wireplumber: redémarrage de wireplumber à faire (systemctl --user restart wireplumber)" >&2
    else
      XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user restart wireplumber \
        || echo "btmux-wireplumber: redémarrage de wireplumber à faire" >&2
    fi
  else
    echo "btmux-wireplumber: session utilisateur absente, wireplumber lira la config au prochain démarrage"
  fi
fi
