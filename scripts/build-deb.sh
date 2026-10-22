#!/usr/bin/env bash
# Construit le paquet Debian btmux_<X.Y.Z>_all.deb a partir de la wheel de dist/ (livrable PROD, contrat C4).
# Paquet "all" : contient la wheel, les unites systemd et la config d'exemple ; le postinst cree
# le venv /opt/btmux sur le Pi et y installe la wheel (les dependances sont resolues sur le Pi).
# Usage : scripts/build-deb.sh <X.Y.Z>
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:?usage: build-deb.sh <X.Y.Z>}"
# Wheel du tag CI (btmux-X.Y.Z-...) ou de dev (btmux-X.Y.Z.a-...) ; la plus recente si plusieurs.
WHEELS=()
for f in dist/btmux-"$VERSION"-py3-none-any.whl dist/btmux-"$VERSION".[0-9]*-py3-none-any.whl; do
  [ -f "$f" ] && WHEELS+=("$f")
done
[ "${#WHEELS[@]}" -gt 0 ] || { echo "wheel dist/btmux-${VERSION}[.a]-py3-none-any.whl introuvable" >&2; exit 1; }
[ -f "dist/btmux-$VERSION-py3-none-any.whl" ] && WHEELS=("dist/btmux-$VERSION-py3-none-any.whl")  # la wheel du tag prime
WHEEL=$(printf '%s\n' "${WHEELS[@]}" | sort -V | tail -1)
# Staging dans le projet par defaut ; BUILD_TMPDIR permet un FS Linux natif (dpkg-deb exige des modes
# 755 que drvfs/WSL sous /mnt/c ne sait pas porter).
BUILD_TMPDIR="${BUILD_TMPDIR:-_work/tmp}"
mkdir -p "$BUILD_TMPDIR"
STAGE=$(mktemp -d -p "$BUILD_TMPDIR" btmux-deb.XXXXXX); trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"   # dpkg-deb refuse 777 (mktemp sur drvfs/WSL)

install -d -m 755 "$STAGE/DEBIAN" "$STAGE/usr/share/btmux" "$STAGE/lib/systemd/system" "$STAGE/etc/btmux"
install -m 644 "$WHEEL" "$STAGE/usr/share/btmux/"
[ -d systemd ] && install -m 644 systemd/*.service "$STAGE/lib/systemd/system/"
[ -f config/config.example.yaml ] && install -m 644 config/config.example.yaml "$STAGE/etc/btmux/config.example.yaml"

cat > "$STAGE/DEBIAN/control" <<CTRL
Package: btmux
Version: $VERSION
Section: sound
Priority: optional
Architecture: all
Depends: python3 (>= 3.12), python3-venv, bluez, pipewire (>= 1.2), wireplumber (>= 0.5)
Maintainer: CCoupel <cyril@coupel.net>
Homepage: https://github.com/CCoupel/Blue-Multiplex
Description: Bluetooth audio multiplexer for Raspberry Pi
 Sources (PCs, phones) see the Pi as a headset (A2DP sink + HFP HF); headsets see it as
 a source (A2DP source + HFP AG). Source switching is done in software via PipeWire.
CTRL

cat > "$STAGE/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
python3 -m venv --upgrade-deps /opt/btmux
/opt/btmux/bin/pip install --quiet --upgrade /usr/share/btmux/btmux-*.whl
systemctl daemon-reload
if [ -f /etc/btmux/config.yaml ]; then systemctl restart btmuxd.service || true; fi
POST
chmod 755 "$STAGE/DEBIAN/postinst"

mkdir -p dist
dpkg-deb --build --root-owner-group "$STAGE" "dist/btmux_${VERSION}_all.deb"
echo "dist/btmux_${VERSION}_all.deb"
