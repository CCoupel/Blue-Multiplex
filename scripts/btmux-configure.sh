#!/bin/sh
# Configuration système de btmux, partagée par le postinst du .deb et par scripts/deploy.sh (idempotente) :
# config d'exemple (+ config.yaml si absente), policy D-Bus de l'utilisateur de service, jeton d'API 0600 (généré s'il manque),
# drop-in d'utilisateur, config WirePlumber headless, scripts d'aide sous /usr/lib/btmux, unités (déploiement), systemd.
# Usage : btmux-configure.sh --user UTILISATEUR --share DIR [--units DIR] [--no-restart]
#   --share : dossier des fichiers de données (config.example.yaml, btmux.conf.in, 51-btmux-no-seat.conf, roles.conf),
#             à plat ou avec un sous-dossier wireplumber/ ;
#   --units : copie btmuxd.service et btmux-adapters.service dans /etc/systemd/system (déploiement ; le .deb les installe lui-même).
# Variables (tests) : BTMUX_ROOT (préfixe de tous les chemins système ; désactive chown et systemctl), BTMUX_UID, BTMUX_HOME.
set -eu

ROOT="${BTMUX_ROOT:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="" SHARE="" UNITS="" RESTART=1
while [ $# -gt 0 ]; do
  case "$1" in
    --user) USER_NAME="${2:?utilisateur}"; shift 2 ;;
    --share) SHARE="${2:?dossier}"; shift 2 ;;
    --units) UNITS="${2:?dossier}"; shift 2 ;;
    --no-restart) RESTART=0; shift ;;
    *) echo "btmux-configure: option inconnue: $1" >&2; exit 2 ;;
  esac
done
[ -n "$USER_NAME" ] && [ -n "$SHARE" ] || { echo "usage: btmux-configure.sh --user U --share DIR" >&2; exit 2; }
case "$USER_NAME" in *[!a-z0-9_-]* | -* | root) echo "btmux-configure: utilisateur invalide: $USER_NAME" >&2; exit 2 ;; esac

share_file() {   # nom -> chemin (à plat ou sous wireplumber/)
  for p in "$SHARE/$1" "$SHARE/wireplumber/$1"; do [ -f "$p" ] && { echo "$p"; return; }; done
  echo "btmux-configure: fichier introuvable dans $SHARE: $1" >&2; exit 1
}

# --- scripts d'aide sous /usr/lib/btmux (déploiement : copiés depuis ce dossier) -----------------------------
LIB="$ROOT/usr/lib/btmux"
if [ "$HERE" != "$LIB" ]; then
  mkdir -p "$LIB"
  for f in btmux-set-user.sh btmux-install-wireplumber.sh btmux-adapters.sh btmux-configure.sh; do
    [ -f "$HERE/$f" ] && install -m 755 "$HERE/$f" "$LIB/$f"
  done
fi

# --- configuration d'exemple et config.yaml ---------------------------------------------------------------
mkdir -p "$ROOT/etc/btmux"
install -m 644 "$(share_file config.example.yaml)" "$ROOT/etc/btmux/config.example.yaml"
if [ ! -f "$ROOT/etc/btmux/config.yaml" ]; then
  install -m 644 "$ROOT/etc/btmux/config.example.yaml" "$ROOT/etc/btmux/config.yaml"
  echo "btmux: /etc/btmux/config.yaml créé depuis l'exemple (adapter les MAC des adaptateurs)"
fi

# --- unités (déploiement) --------------------------------------------------------------------------------
if [ -n "$UNITS" ]; then
  mkdir -p "$ROOT/etc/systemd/system"
  for u in btmuxd.service btmux-adapters.service; do install -m 644 "$UNITS/$u" "$ROOT/etc/systemd/system/$u"; done
fi

# --- policy D-Bus de l'utilisateur de service -------------------------------------------------------------
mkdir -p "$ROOT/etc/dbus-1/system.d"
TEMPLATE="$(share_file btmux.conf.in)" || exit 1   # le `exit` de share_file ne sort que du sous-shell
POLICY="$ROOT/etc/dbus-1/system.d/btmux.conf"
POLICY_TMP="$(mktemp "$ROOT/etc/dbus-1/system.d/.btmux.conf.XXXXXX")"
trap 'rm -f "$POLICY_TMP"' EXIT
if ! sed "s/@BTMUX_USER@/$USER_NAME/g" "$TEMPLATE" > "$POLICY_TMP" || [ ! -s "$POLICY_TMP" ]; then
  echo "btmux-configure: rendu de la policy D-Bus vide ou en échec ($TEMPLATE) — $POLICY inchangé" >&2
  exit 1
fi
chmod 644 "$POLICY_TMP"
mv -f "$POLICY_TMP" "$POLICY"

# --- jeton d'API (0600, propriétaire = utilisateur de service), jamais régénéré s'il existe -------------------
TOKEN="$ROOT/etc/btmux/token"
if [ ! -s "$TOKEN" ]; then
  (umask 077; head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$TOKEN")
  echo "btmux: jeton d'API généré ($TOKEN)"
fi
chmod 600 "$TOKEN"
[ -n "$ROOT" ] || chown "$USER_NAME:$(id -gn "$USER_NAME")" "$TOKEN"

# --- drop-in d'utilisateur, WirePlumber headless, roles.conf (gabarit) ----------------------------------------
if [ -n "$ROOT" ]; then
  BTMUX_DROPIN_DIR="$ROOT/etc/systemd/system/btmuxd.service.d" sh "$HERE/btmux-set-user.sh" "$USER_NAME"
else
  sh "$HERE/btmux-set-user.sh" "$USER_NAME"
fi
BTMUX_NO_RESTART="${BTMUX_NO_RESTART:-$([ -n "$ROOT" ] && echo 1 || echo 0)}" \
  sh "$HERE/btmux-install-wireplumber.sh" "$USER_NAME" "$(share_file 51-btmux-no-seat.conf)" || true
mkdir -p "$ROOT/usr/share/btmux/wireplumber"
[ "$(cd "$(dirname "$(share_file roles.conf)")" && pwd)" = "$(cd "$ROOT/usr/share/btmux/wireplumber" && pwd)" ] || \
  install -m 644 "$(share_file roles.conf)" "$ROOT/usr/share/btmux/wireplumber/roles.conf"

# --- systemd -----------------------------------------------------------------------------------------------
if [ -z "$ROOT" ]; then
  systemctl daemon-reload
  systemctl enable btmux-adapters.service btmuxd.service >/dev/null 2>&1 || true
  systemctl reload dbus.service >/dev/null 2>&1 || true
  if [ "$RESTART" = 1 ]; then
    systemctl restart btmux-adapters.service || true
    systemctl restart btmuxd.service || true
  fi
fi
