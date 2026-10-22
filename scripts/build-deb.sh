#!/usr/bin/env bash
# Construit le paquet Debian btmux_<X.Y.Z>_all.deb a partir de la wheel de dist/ (livrable PROD, contrat C4).
# Paquet "all" : contient la wheel, les unites systemd et la config d'exemple ; le postinst cree
# le venv /opt/btmux sur le Pi et y installe la wheel (les dependances sont resolues sur le Pi).
# Usage : scripts/build-deb.sh <X.Y.Z>
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:?usage: build-deb.sh <X.Y.Z>}"
WHEEL=$(ls dist/btmux-"$VERSION"-py3-none-any.whl)
STAGE=$(mktemp -d -p "${TMPDIR:-/tmp}" btmux-deb.XXXXXX); trap 'rm -rf "$STAGE"' EXIT

install -d "$STAGE/DEBIAN" "$STAGE/usr/share/btmux" "$STAGE/lib/systemd/system" "$STAGE/etc/btmux"
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
