# Installation du Pi btmux (qualif puis prod)

> Procédure de provisionnement du Pi (v0.1.0, mono-adaptateur). **OS cible : Ubuntu Server 26.04 LTS (arm64)**,
> image officielle Raspberry Pi. Statut : rédigée, **pas encore vérifiée** sur matériel — la vérification a lieu
> en phase 1.C (issue #3) ; la section « Versions installées » est complétée à ce moment-là.
> Le même Pi sert de qualif puis de prod.

## 1. Matériel

- Raspberry Pi 4 (préféré) ; Pi 3 ou Pi 5 possibles. Alimentation officielle, carte SD ≥ 16 Go, câble Ethernet.
- 1 dongle USB Bluetooth Realtek RTL8761B (ex. TP-Link UB500) sur une **rallonge USB**, éloigné des ports USB 3.
- v0.1.0 : un seul adaptateur ; le second dongle n'arrive qu'en v0.2.0.

## 2. Paquets disponibles dans Ubuntu 26.04 (« resolute », arm64)

Versions relevées dans l'archive Ubuntu (Launchpad, 2026-10-22) — toutes satisfont les exigences de btmux :

| Paquet | Exigé | Disponible (resolute) |
|--------|-------|-----------------------|
| `pipewire` / `libspa-0.2-bluetooth` | ≥ 1.2 | 1.6.2-1ubuntu1 (1.6.2-1ubuntu1.2 en updates) |
| `wireplumber` | ≥ 0.5 | 0.5.13-1ubuntu1 (.1 en updates) |
| `bluez` | présent | 5.85-4 (5.85-4ubuntu0.4 en updates/security) |
| `python3` / `python3-venv` | ≥ 3.12 | 3.14.3-0ubuntu2 (python3.14 3.14.4-1ubuntu0.2) |
| `linux-firmware` | `rtl_bt/rtl8761b*` | 20260319.git217ca6e4.1ubuntu |

Les dépendances Python de btmux (`dbus-fast`, `pydantic-core`, `pyyaml`) publient des wheels `cp314` aarch64 sur PyPI
(pas de compilation sur le Pi). La présence effective des fichiers `rtl_bt/rtl8761bu_*` dans `linux-firmware` est
vérifiée au §6 (non vérifiable sans le matériel).

## 3. Image et système

1. Dans Raspberry Pi Imager : **Ubuntu Server 26.04 LTS (64-bit)**. Dans les options de personnalisation
   (cloud-init) : hostname `btmux-qualif`, utilisateur (le script de ce document suppose `ubuntu`, UID 1000, mais tout
   utilisateur convient), **clé SSH publique**, authentification par mot de passe désactivée, **pas de Wi-Fi**.
2. Désactiver le Bluetooth intégré et le Wi-Fi dans `/boot/firmware/config.txt` (section `[all]`) :

   ```
   dtoverlay=disable-bt
   dtoverlay=disable-wifi
   ```

3. Vérifier qu'aucun Wi-Fi n'est configuré : `ls /etc/netplan/` ne doit pas contenir de bloc `wifis:`
   (sinon le retirer, puis `sudo netplan apply`). Seul Ethernet reste actif.
4. Redémarrer ; le Pi doit être joignable : `ssh <utilisateur>@btmux-qualif.local` (nécessite `avahi-daemon`, installé
   au §4 — sinon utiliser l'adresse IP du routeur pour la première connexion).

## 4. Paquets

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y bluez pipewire pipewire-audio wireplumber libspa-0.2-bluetooth \
    python3-venv linux-firmware bluez-tools alsa-utils avahi-daemon
```

## 5. Session PipeWire pour le service système (décision D2)

`btmuxd` tourne comme **unité système** sous un utilisateur normal, qui accède à sa propre session PipeWire :

- l'utilisateur de service est paramétrable : `BTMUX_USER` (variable de `qualif.env`, défaut = partie utilisateur de
  `DEPLOY_HOST`, sinon `ubuntu`). `scripts/deploy.sh` et le `postinst` du `.deb` génèrent le drop-in
  `/etc/systemd/system/btmuxd.service.d/user.conf` (`User=`, `XDG_RUNTIME_DIR=/run/user/<uid>`, `After=user@<uid>.service`)
  via `scripts/btmux-set-user.sh` (installé en `/usr/lib/btmux/set-user.sh` par le paquet) ;
- la session utilisateur doit exister sans login : `sudo loginctl enable-linger <utilisateur>` ;
- PipeWire/WirePlumber tournent en **services utilisateur** (jamais `--system`). Ubuntu les active à l'installation ;
  sinon : `systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service`.

Vérifier (après reboot, sans session ouverte) : `loginctl show-user <utilisateur> -p Linger` → `Linger=yes` et
`ls /run/user/$(id -u <utilisateur>)/pipewire-0`.

## 6. Dongle RTL8761B

```bash
lsusb | grep -i -E "0bda|realtek"          # le dongle est vu sur le bus USB
dmesg | grep rtl_bt                         # firmware rtl8761bu_fw chargé, sans erreur
ls /lib/firmware/rtl_bt/ | grep 8761b       # firmware présent (paquet linux-firmware)
sudo btmgmt info                            # un contrôleur, version Bluetooth 5.x
bluetoothctl list                           # "Controller <MAC> ... [default]"
```

Relever l'**adresse MAC** du contrôleur : elle va dans `adapters[0].mac` de `/etc/btmux/config.yaml`
(l'identification se fait par MAC, jamais par `hci0`).

## 7. Vérifications PipeWire / BlueZ

```bash
systemctl is-active bluetooth               # active
wpctl status                                # PipeWire + WirePlumber répondent
pw-cli info 0 | grep -E "version|name"      # version PipeWire
```

## 8. Script de vérification

À exécuter **en tant qu'utilisateur de service** (variable `BTMUX_USER` pour un autre utilisateur). Il échoue
(code ≠ 0) si une anomalie est détectée et les affiche toutes :

```bash
#!/usr/bin/env bash
set -u
fail=0
ok()  { echo "OK    $*"; }
ko()  { echo "ECHEC $*"; fail=1; }
vge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }  # $1 >= $2
svc=${BTMUX_USER:-$(id -un)}; uid=$(id -u "$svc" 2>/dev/null || echo 0)
pkgver() { dpkg-query -W -f='${Version}' "$1" 2>/dev/null; }

. /etc/os-release; [ "${VERSION_CODENAME:-}" = resolute ] && ok "Ubuntu 26.04 (resolute)" || ko "OS: ${VERSION_CODENAME:-?} (resolute requis)"
[ "$(uname -m)" = aarch64 ] && ok "64 bits" || ko "architecture $(uname -m)"
[ "$uid" -ne 0 ] && ok "utilisateur de service $svc (uid $uid)" || ko "utilisateur $svc introuvable"
pw=$(pkgver pipewire); vge "${pw:-0}" 1.2 && ok "pipewire $pw" || ko "pipewire ${pw:-absent} (>= 1.2)"
wp=$(pkgver wireplumber); vge "${wp:-0}" 0.5 && ok "wireplumber $wp" || ko "wireplumber ${wp:-absent} (>= 0.5)"
for p in libspa-0.2-bluetooth bluez linux-firmware python3-venv; do
  v=$(pkgver "$p"); [ -n "$v" ] && ok "$p $v" || ko "$p absent"
done
python3 -c 'import ensurepip' 2>/dev/null && ok "ensurepip" || ko "ensurepip indisponible (python3-venv)"
py=$(python3 -c 'import platform;print(platform.python_version())'); vge "$py" 3.12 && ok "python $py" || ko "python $py (>= 3.12)"
systemctl is-active --quiet bluetooth && ok "bluetooth.service actif" || ko "bluetooth.service inactif"
[ "$(loginctl show-user "$svc" -p Linger --value 2>/dev/null)" = yes ] && ok "linger $svc" || ko "linger $svc absent"
[ -S "/run/user/$uid/pipewire-0" ] && ok "socket PipeWire $svc" || ko "socket /run/user/$uid/pipewire-0 absente"
ls /lib/firmware/rtl_bt/ 2>/dev/null | grep -q 8761b && ok "firmware rtl8761b présent" || ko "firmware rtl8761b absent"
sudo dmesg 2>/dev/null | grep -q rtl_bt && ok "firmware rtl_bt chargé" || ko "pas de trace rtl_bt (dmesg)"
n=$(bluetoothctl list | grep -c '^Controller'); [ "$n" -eq 1 ] && ok "1 contrôleur: $(bluetoothctl list)" || ko "$n contrôleur(s) (1 attendu)"
ip -br link | grep -q '^wlan' && ko "interface wlan présente (Wi-Fi à désactiver)" || ok "pas de Wi-Fi"
exit $fail
```

## 9. Versions installées

Relevé du **2026-10-22** sur `pi-qualif` (lecture seule, `ubuntu@192.168.1.94`) — état **après flash et premier
démarrage uniquement** ; les étapes §3 (config.txt, Ethernet), §4 (paquets), §5 (linger) et §6 (dongle) n'ont pas
encore été faites. Les lignes « à relever » sont à compléter après ces étapes (rejouer le script du §8).

| Élément | Relevé |
|---------|--------|
| Matériel | Raspberry Pi 3 Model B Rev 1.2 |
| OS | Ubuntu 26.04.1 LTS (`resolute`), aarch64 |
| Noyau | 7.0.0-1020-raspi (#20-Ubuntu, 2026-09-11) |
| Hostname | `pi-qualif.local` (le hostname lui-même contient `.local` ; préférer `pi-qualif`) |
| Utilisateur de service | `ubuntu` (uid 1000), `sudo` sans mot de passe (`sudo -n true` OK), accès apt et PyPI OK |
| python3 | 3.14.3-0ubuntu2 (interpréteur 3.14.4) ; `python3-venv` **absent** (`ensurepip` indisponible) |
| linux-firmware | 20260319.git217ca6e4.1ubuntu — `rtl_bt/rtl8761b{,u}_{fw,config}.bin.zst` présents |
| bluez, pipewire, wireplumber, libspa-0.2-bluetooth, avahi-daemon | à relever (absents avant §4) |
| Dongle RTL8761B | à relever (non branché : `lsusb` sans Realtek) ; Bluetooth intégré actif (BCM43430A1, hci0 UART) tant que `disable-bt` n'est pas posé |
| MAC du contrôleur | à relever (§6) |
| Capacités `btmgmt info` / liens SCO | à relever |
| AAC (`pw-dump \| grep -i aac`) | à relever |
| Linger / socket PipeWire | `Linger=no`, pas de `/run/user/1000/pipewire-0` (avant §4 et §5) |
| Réseau | `eth0` sans câble ; SSH passe par **Wi-Fi** (`wlan0`) |

> Attention : brancher l'Ethernet **avant** de poser `dtoverlay=disable-wifi`, sinon le Pi devient injoignable en SSH.
