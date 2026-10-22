# Installation du Pi de qualification (`btmux-qualif`)

> Procédure de provisionnement du Pi de **qualification** (v0.1.0, mono-adaptateur). Statut : rédigée, **pas encore
> vérifiée** sur matériel — la vérification a lieu en phase 1.C (issue #3) ; la section « Versions installées » est
> complétée à ce moment-là.

## 1. Matériel

- Raspberry Pi 4 ou 5, alimentation officielle, carte SD ≥ 16 Go, câble Ethernet.
- 1 dongle USB Bluetooth Realtek RTL8761B (ex. TP-Link UB500) sur une **rallonge USB**, éloigné des ports USB 3.
- v0.1.0 : un seul adaptateur ; le second dongle n'arrive qu'en v0.2.0.

## 2. Image et système

1. Flasher **Raspberry Pi OS Lite 64 bits, base Debian Trixie** (Raspberry Pi Imager). Bookworm est exclu
   (PipeWire trop ancien).
2. Dans les options de l'Imager : hostname `btmux-qualif`, utilisateur `pi`, clé SSH publique, **pas de Wi-Fi**,
   locale/fuseau au choix.
3. Désactiver le Bluetooth intégré et le Wi-Fi dans `/boot/firmware/config.txt` :

   ```
   dtoverlay=disable-bt
   dtoverlay=disable-wifi
   ```

   puis `sudo systemctl disable --now hciuart.service` (si présent) et redémarrer. Le Pi doit être joignable en
   Ethernet : `ssh pi@btmux-qualif.local`.

## 3. Paquets

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y bluez pipewire pipewire-audio wireplumber libspa-0.2-bluetooth \
    python3 python3-venv firmware-realtek bluez-tools alsa-utils
```

Versions exigées : `pipewire >= 1.2`, `wireplumber >= 0.5`, `python3 >= 3.12` (vérifiées par le script du §7).

## 4. Session PipeWire pour le service système (décision D2)

`btmuxd` tourne comme **unité système** sous l'utilisateur `pi`, avec accès à la session PipeWire de `pi` :

- `User=pi` et `Environment=XDG_RUNTIME_DIR=/run/user/1000` dans `systemd/btmuxd.service` (T1.6) ;
- la session utilisateur doit exister sans login : `sudo loginctl enable-linger pi`.

Vérifier : `loginctl show-user pi -p Linger` → `Linger=yes` et `ls /run/user/1000/pipewire-0` existe après reboot.
Si l'UID de `pi` n'est pas 1000 (`id -u pi`), adapter `XDG_RUNTIME_DIR`.

## 5. Dongle RTL8761B

```bash
lsusb | grep -i -E "0bda|realtek"          # le dongle est vu sur le bus USB
dmesg | grep rtl_bt                         # firmware rtl8761bu_fw chargé, sans erreur
sudo btmgmt info                            # un contrôleur, version Bluetooth 5.x
bluetoothctl list                           # "Controller <MAC> ... [default]"
```

Relever l'**adresse MAC** du contrôleur : elle va dans `adapters[0].mac` de `/etc/btmux/config.yaml`
(l'identification se fait par MAC, jamais par `hci0`).

## 6. Vérifications PipeWire / BlueZ

```bash
systemctl is-active bluetooth               # active
wpctl status                                # PipeWire + WirePlumber répondent
pw-cli info 0 | grep -E "version|name"      # version PipeWire
```

## 7. Script de vérification

Le script ci-dessous (également fourni dans la procédure manuelle) échoue (code ≠ 0) à la première anomalie :

```bash
#!/usr/bin/env bash
set -u
fail=0
ok()  { echo "OK    $*"; }
ko()  { echo "ECHEC $*"; fail=1; }
vge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }  # $1 >= $2

. /etc/os-release; [ "${VERSION_CODENAME:-}" = trixie ] && ok "Debian trixie" || ko "OS: ${VERSION_CODENAME:-?} (trixie requis)"
[ "$(uname -m)" = aarch64 ] && ok "64 bits" || ko "architecture $(uname -m)"
pw=$(pw-cli --version 2>/dev/null | awk '/libpipewire/{print $2}'); vge "${pw:-0}" 1.2 && ok "pipewire $pw" || ko "pipewire ${pw:-absent} (>= 1.2)"
wp=$(wireplumber --version 2>/dev/null | awk '/libwireplumber/{print $NF}'); vge "${wp:-0}" 0.5 && ok "wireplumber $wp" || ko "wireplumber ${wp:-absent} (>= 0.5)"
py=$(python3 -c 'import platform;print(platform.python_version())'); vge "$py" 3.12 && ok "python $py" || ko "python $py (>= 3.12)"
systemctl is-active --quiet bluetooth && ok "bluetooth.service actif" || ko "bluetooth.service inactif"
[ "$(loginctl show-user pi -p Linger --value 2>/dev/null)" = yes ] && ok "linger pi" || ko "linger pi absent"
[ -S /run/user/1000/pipewire-0 ] && ok "socket PipeWire pi" || ko "socket /run/user/1000/pipewire-0 absente"
dmesg 2>/dev/null | grep -q rtl_bt && ok "firmware rtl_bt chargé" || ko "pas de trace rtl_bt (dmesg)"
n=$(bluetoothctl list | grep -c '^Controller'); [ "$n" -eq 1 ] && ok "1 contrôleur: $(bluetoothctl list)" || ko "$n contrôleur(s) (1 attendu)"
ip -br link | grep -q '^wlan0' && ko "wlan0 présent (Wi-Fi à désactiver)" || ok "pas de Wi-Fi"
exit $fail
```

## 8. Versions installées

_À compléter en phase 1.C (T1.8) après exécution du script sur le Pi : OS, noyau, bluez, pipewire, wireplumber,
python, firmware dongle, MAC du contrôleur._
