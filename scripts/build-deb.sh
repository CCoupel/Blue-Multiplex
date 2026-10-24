#!/usr/bin/env bash
# Construit le paquet Debian btmux_<X.Y.Z>_all.deb à partir de la wheel et du lockfile de dist/ (livrable PROD, contrat C4).
# Paquet « all » déterministe : il contient la wheel, le lockfile runtime haché (dist/requirements.lock.txt, produit par scripts/ci.sh),
# les unités systemd, la config d'exemple et les scripts d'installation ; le postinst crée le venv /opt/btmux et y installe
# les dépendances avec `--require-hashes`, puis la wheel sans index.
# Usage : scripts/build-deb.sh <X.Y.Z>     (BUILD_TMPDIR : dossier de staging, défaut _work/tmp ; FS Linux requis par dpkg-deb ;
#                                          BTMUX_DIST : dossier des artefacts, défaut dist — tests)
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:?usage: build-deb.sh <X.Y.Z>}"
DIST="${BTMUX_DIST:-dist}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "build-deb: version attendue X.Y.Z, reçu '$VERSION'" >&2; exit 2; }

# Wheel du tag CI (btmux-X.Y.Z-…) ou de dev (btmux-X.Y.Z.N-…) ; motifs stricts (0.1.1 ne correspond pas à 0.1.10).
shopt -s nullglob
WHEELS=()
compgen -G "$DIST/btmux-$VERSION-py3-none-any.whl" > /dev/null && WHEELS+=("$DIST"/btmux-"$VERSION"-py3-none-any.whl)
compgen -G "$DIST/btmux-$VERSION.[0-9]*-py3-none-any.whl" > /dev/null && WHEELS+=("$DIST"/btmux-"$VERSION".[0-9]*-py3-none-any.whl)
shopt -u nullglob
[ "${#WHEELS[@]}" -gt 0 ] || { echo "build-deb: wheel $DIST/btmux-${VERSION}[.N]-py3-none-any.whl introuvable" >&2; exit 1; }
if compgen -G "$DIST/btmux-$VERSION-py3-none-any.whl" > /dev/null; then
  WHEEL="$DIST/btmux-$VERSION-py3-none-any.whl"   # la wheel du tag prime
else
  WHEEL="$(printf '%s\n' "${WHEELS[@]}" | sort -V | tail -1)"
fi
LOCK="$DIST/requirements.lock.txt"
[ -s "$LOCK" ] || { echo "build-deb: $LOCK absent (lancer scripts/ci.sh : uv export --no-dev --frozen --hashes)" >&2; exit 1; }
grep -q -- '--hash=sha256:' "$LOCK" || { echo "build-deb: $LOCK sans hash" >&2; exit 1; }

# Staging dans le projet par défaut ; BUILD_TMPDIR permet un FS Linux natif (dpkg-deb exige des modes 755 que drvfs/WSL ne porte pas).
BUILD_TMPDIR="${BUILD_TMPDIR:-_work/tmp}"
mkdir -p "$BUILD_TMPDIR"
STAGE=$(mktemp -d -p "$BUILD_TMPDIR" btmux-deb.XXXXXX); trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"

install -d -m 755 "$STAGE/DEBIAN" "$STAGE/usr/share/btmux/wireplumber" "$STAGE/usr/lib/btmux" \
  "$STAGE/lib/systemd/system" "$STAGE/etc/btmux" "$STAGE/etc/dbus-1/system.d"
install -m 644 "$WHEEL" "$STAGE/usr/share/btmux/"
install -m 644 "$LOCK" "$STAGE/usr/share/btmux/requirements.lock.txt"
install -m 644 systemd/btmuxd.service systemd/btmux-adapters.service systemd/btmux-adapters.path \
  systemd/btmux-adapters-reload.service systemd/btmux-adapters-identity.path systemd/btmux-adapters-identity.service \
  "$STAGE/lib/systemd/system/"
install -m 644 config/config.example.yaml "$STAGE/usr/share/btmux/config.example.yaml"
install -m 644 config/config.example.yaml "$STAGE/etc/btmux/config.example.yaml"
install -m 644 config/dbus/btmux.conf.in "$STAGE/usr/share/btmux/btmux.conf.in"
install -m 644 config/dbus/btmux.conf.default "$STAGE/etc/dbus-1/system.d/btmux.conf"   # utilisateur « ubuntu » ; réécrit par le postinst
install -m 644 config/wireplumber/51-btmux-no-seat.conf config/wireplumber/roles.conf "$STAGE/usr/share/btmux/wireplumber/"
for f in btmux-set-user.sh btmux-install-wireplumber.sh btmux-adapters.sh btmux-configure.sh; do
  install -m 755 "scripts/$f" "$STAGE/usr/lib/btmux/$f"
done

cat > "$STAGE/DEBIAN/control" <<CTRL
Package: btmux
Version: $VERSION
Section: sound
Priority: optional
Architecture: all
Depends: python3 (>= 3.12), python3-venv, bluez, dbus, pipewire (>= 1.2), wireplumber (>= 0.5), linux-firmware
Maintainer: CCoupel <cyril@coupel.net>
Homepage: https://github.com/CCoupel/Blue-Multiplex
Description: Bluetooth audio multiplexer for Raspberry Pi
 Sources (PCs, phones) see the Pi as a headset (A2DP sink + HFP HF); headsets see it as
 a source (A2DP source + HFP AG). Source switching is done in software via PipeWire.
CTRL

cat > "$STAGE/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
case "$1" in
configure)
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' || { echo "btmux: python3 >= 3.12 requis" >&2; exit 1; }
  # Environnement Python déterministe : venv standard (pip non mis à niveau), dépendances hachées, puis wheel sans index.
  [ -x /opt/btmux/bin/pip ] || { rm -rf /opt/btmux; python3 -m venv /opt/btmux; }
  /opt/btmux/bin/pip install --quiet --only-binary=:all: --require-hashes --no-deps -r /usr/share/btmux/requirements.lock.txt
  /opt/btmux/bin/pip install --quiet --no-index --no-deps --force-reinstall /usr/share/btmux/btmux-*.whl
  # Utilisateur de service : $BTMUX_USER, sinon l'utilisateur qui a lancé sudo, sinon « ubuntu ».
  # Un drop-in déjà présent (choix de l'administrateur) n'est pas écrasé sans BTMUX_USER explicite.
  svc_user="${BTMUX_USER:-}"
  if [ -z "$svc_user" ] && [ -f /etc/systemd/system/btmuxd.service.d/user.conf ]; then
    svc_user="$(sed -n 's/^User=//p' /etc/systemd/system/btmuxd.service.d/user.conf | head -1)"
  fi
  if [ -z "$svc_user" ]; then svc_user="${SUDO_USER:-ubuntu}"; [ "$svc_user" = root ] && svc_user=ubuntu; fi
  if id "$svc_user" >/dev/null 2>&1; then
    /usr/lib/btmux/btmux-configure.sh --user "$svc_user" --share /usr/share/btmux
  else
    echo "btmux: utilisateur '$svc_user' inconnu — relancer: /usr/lib/btmux/btmux-configure.sh --user <utilisateur> --share /usr/share/btmux" >&2
  fi
  ;;
abort-upgrade|abort-remove|abort-deconfigure) ;;
esac
exit 0
POST

cat > "$STAGE/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
case "$1" in
remove|upgrade|deconfigure)
  # Surveillance du fichier d'état arrêtée d'abord (aucun redémarrage piloté pendant la mise à jour, #23),
  # puis arrêt propre (SIGTERM, code 0) ; config.yaml, jeton et fichier d'état sont conservés.
  systemctl stop btmux-adapters.path btmux-adapters-identity.path >/dev/null 2>&1 || true
  systemctl stop btmuxd.service btmux-adapters.service btmux-adapters-reload.service \
    btmux-adapters-identity.service >/dev/null 2>&1 || true
  [ "$1" = remove ] && systemctl disable btmuxd.service btmux-adapters.service btmux-adapters.path \
    btmux-adapters-identity.path >/dev/null 2>&1 || true
  ;;
esac
exit 0
PRERM

cat > "$STAGE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
case "$1" in
remove|purge|upgrade|disappear)
  systemctl daemon-reload >/dev/null 2>&1 || true
  ;;
esac
case "$1" in
purge)
  # Retire l'environnement Python et l'état généré (dont l'affectation des rôles /var/lib/btmux, #23) ;
  # /etc/btmux/config.yaml (configuration de l'utilisateur) est CONSERVÉ.
  rm -rf /opt/btmux /etc/systemd/system/btmuxd.service.d /etc/dbus-1/system.d/btmux.conf /etc/btmux/token /var/lib/btmux
  rm -f /etc/btmux/config.example.yaml
  systemctl reload dbus.service >/dev/null 2>&1 || true
  ;;
esac
exit 0
POSTRM
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"

mkdir -p "$DIST"
dpkg-deb --build --root-owner-group "$STAGE" "$DIST/btmux_${VERSION}_all.deb"
echo "$DIST/btmux_${VERSION}_all.deb"
