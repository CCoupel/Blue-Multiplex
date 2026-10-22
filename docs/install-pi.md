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

À exécuter **en tant qu'utilisateur de service** (variable `BTMUX_USER` pour un autre utilisateur ; `BTMUX_BT_MODE=internal` pour la variante provisoire du §10, défaut `dongle`). Il échoue
(code ≠ 0) si une anomalie est détectée et les affiche toutes :

```bash
#!/usr/bin/env bash
set -u
fail=0
ok()  { echo "OK    $*"; }
ko()  { echo "ECHEC $*"; fail=1; }
vge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }  # $1 >= $2
mode=${BTMUX_BT_MODE:-dongle}   # dongle (RTL8761B, cible) | internal (Bluetooth intégré du Pi 3, provisoire)
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
if [ "$mode" = internal ]; then
  sudo dmesg 2>/dev/null | grep -q 'hci0: BCM' && ok "firmware BCM chargé (Bluetooth interne)" || ko "pas de trace hci0 BCM (dmesg)"
  grep -q '^dtoverlay=disable-bt' /boot/firmware/config.txt && ko "disable-bt présent (à retirer en mode internal)" || ok "disable-bt absent"
else
  ls /lib/firmware/rtl_bt/ 2>/dev/null | grep -q 8761b && ok "firmware rtl8761b présent" || ko "firmware rtl8761b absent"
  sudo dmesg 2>/dev/null | grep -q rtl_bt && ok "firmware rtl_bt chargé" || ko "pas de trace rtl_bt (dmesg)"
fi
bl=$(timeout 8 bluetoothctl list </dev/null 2>/dev/null)   # timeout : bluetoothctl attend sans contrôleur
n=$(printf '%s\n' "$bl" | grep -c '^Controller'); [ "$n" -eq 1 ] && ok "1 contrôleur: $bl" || ko "$n contrôleur(s) (1 attendu)"
if ip -br link | grep -q '^wlan'; then
  [ "$mode" = internal ] && ok "Wi-Fi présent (toléré en mode internal)" || ko "interface wlan présente (Wi-Fi à désactiver)"
else ok "pas de Wi-Fi"; fi
exit $fail
```

## 9. Versions installées

Relevé du **2026-10-22** sur `pi-qualif` (`ubuntu@192.168.1.94`), en **variante provisoire Bluetooth interne** (§10) :
le dongle RTL8761B n'est pas disponible. Les valeurs de la cible (dongle) restent à relever le jour où il sera branché.

| Élément | Relevé |
|---------|--------|
| Matériel | Raspberry Pi 3 Model B Rev 1.2 (894 Mo de RAM utilisables) |
| OS / noyau | Ubuntu 26.04.1 LTS (`resolute`), aarch64 — noyau 7.0.0-1020-raspi |
| Hostname | `pi-qualif` (via `hostnamectl` ; `preserve_hostname: true` posé pour cloud-init) |
| Utilisateur de service | `ubuntu` (uid 1000), `sudo` sans mot de passe, `Linger=yes` |
| `pipewire`, `pipewire-audio`, `libspa-0.2-bluetooth` | 1.6.2-1ubuntu1.2 |
| `wireplumber` | 0.5.13-1ubuntu1.1 |
| `bluez` | 5.85-4ubuntu0.4 |
| `python3`, `python3-venv` | 3.14.3-0ubuntu2 (`ensurepip` OK) |
| `linux-firmware` / `linux-firmware-raspi` | 20260319.git217ca6e4.1ubuntu / 14-0ubuntu1.1 (`brcm/BCM43430A1.raspberrypi,3-model-b.hcd`, `rtl_bt/rtl8761b*` présents) |
| `avahi-daemon` | 0.8-18ubuntu1.1 (actif) |
| PipeWire / WirePlumber | **services utilisateur** actifs, `/run/user/1000/pipewire-0` présent sans session, aucune unité système |
| Codecs Bluetooth de `libspa-0.2-bluetooth` | sbc, aptx, faststream, g722, ldac, lc3, opus, HFP cvsd/mSBC/LC3 — **pas d'AAC** (pas de `libspa-codec-bluez5-aac.so`) |
| Contrôleur (mode interne) | `hci0`, bus UART, Broadcom BCM43430A1 (puce 43438/43436, firmware 001.002.009 build 1042) |
| **MAC du contrôleur** | **B8:27:EB:1A:2E:D6** (adresse publique appliquée par le noyau après l'init ; l'adresse « par défaut » 43:43:A1:12:1F:AC du firmware n'est pas utilisée) |
| Version Bluetooth | HCI/LMP **4.2** (version 8, révision 0x412, subversion 0x2209) — le firmware annonce 4.2, pas 4.1 |
| Capacités `btmgmt info` | powered, connectable, fast-connectable, discoverable, bondable, link-security, ssp, br/edr, le, advertising, secure-conn, debug-keys, privacy, configuration, static-addr, phy-configuration ; option `public-address` ; rôles central + peripheral ; 5 instances d'advertising |
| SCO | `hciconfig` : SCO MTU 64:1 (un seul paquet de 64 octets en file côté contrôleur) ; **routage par défaut = PCM** (lecture `0x3f 0x1d` → `00 02 00 01 01`, routing 0) ; **routage HCI accepté** (voir §10) ; nombre de liens SCO simultanés non exposé par `btmgmt`, à mesurer lors des spikes (R1) |
| AAC | absent (cf. codecs) |
| `config.txt` | `disable-bt` retiré ; `disable-wifi` non posé (SSH par Wi-Fi) |
| Réseau | `eth0` sans câble ; SSH par Wi-Fi (`wlan0`) — **antenne 2,4 GHz partagée avec le Bluetooth** |
| Dongle RTL8761B | non disponible (à relever : MAC, `btmgmt`, SCO) |

> `dtoverlay=disable-wifi` est à poser **après** branchement de l'Ethernet (sinon le Pi devient injoignable en
> SSH), puis redémarrer.
> `bluetoothctl list` attend indéfiniment quand aucun contrôleur n'existe : le script du §8 utilise `timeout`.

## 10. Variante provisoire : Bluetooth interne (Pi 3)

Tant que le dongle RTL8761B n'est pas disponible, les spikes peuvent utiliser le Bluetooth intégré du Pi 3 Model B
(Broadcom/Cypress 43438 sur UART). **Ce n'est pas la cible** : résultats de latence, de qualité et de nombre de liens
SCO à confirmer avec le dongle.

Mise en place (Ubuntu 26.04 arm64) :

1. Dans `/boot/firmware/config.txt`, **ne pas** poser `dtoverlay=disable-bt` (le retirer s'il existe), puis redémarrer.
2. Aucun paquet supplémentaire : le noyau (`hci_uart_bcm`) attache la puce via le device tree et charge
   `brcm/BCM43430A1.raspberrypi,3-model-b.hcd` (paquet `linux-firmware-raspi`, déjà installé). Pas de `hciattach`,
   de `pi-bluetooth` ni de `hciuart.service`.
3. Vérifier : `dmesg | grep 'hci0: BCM'`, `sudo btmgmt info` (1 contrôleur), `systemctl is-active bluetooth`, puis le
   script du §8 avec `BTMUX_BT_MODE=internal`.
4. Dans `/etc/btmux/config.yaml`, `adapters[0].mac` = `B8:27:EB:1A:2E:D6` (MAC relevée au §9).

**Retour au dongle** : remettre `dtoverlay=disable-bt` dans `config.txt`, brancher le dongle, redémarrer, relever la
nouvelle MAC et mettre à jour `adapters[0].mac` (script avec `BTMUX_BT_MODE=dongle`).

Limites connues du Bluetooth interne :

- **HCI sur UART** (≤ 3 Mbit/s en pratique) : le débit A2DP (SBC ~345 kbit/s) passe, mais la marge est faible dès que
  l'audio double saut + voix sont actifs.
- **Antenne partagée avec le Wi-Fi 2,4 GHz** (actif ici, pas d'Ethernet) : coexistence dégradée, coupures possibles ;
  les mesures de latence/qualité seront pessimistes. Brancher l'Ethernet et poser `disable-wifi` améliore le cas.
- **Voix (SCO)** : le routage par défaut du firmware est le **PCM** (broches physiques), pas HCI. L'essai du
  2026-10-22 (`hcitool cmd 0x3f 0x1c 01 00 00 00 00` puis relecture `0x3f 0x1d`) montre que le contrôleur **accepte le
  routage « Transport/HCI »** (relecture `01 00 00 00 00`) ; la valeur d'origine (`00 02 00 01 01`) a été restaurée
  ensuite. Le réglage est volatile (perdu au reset du contrôleur/redémarrage) : btmuxd devra l'appliquer à chaque
  démarrage s'il retient cette voie. Le passage effectif d'audio SCO par HCI (HFP) n'a **pas** été testé : il
  nécessite un appareil appairé (spikes #8/#9).
- **Un seul contrôleur** : en mono-adaptateur, le même `hci0` fait casque pour les sources et source pour les casques
  (limite connue de la v0.1.0, indépendante de la variante).
- **Bluetooth 4.2** (et non 5.x) : pas de LE 2M ni d'extensions BT 5 ; sans effet sur A2DP/HFP classiques.
- **RAM** : 894 Mo (510 Mo disponibles au repos).

Impact sur les spikes #5 à #10 : A2DP sink/source, AVRCP, HFP (rôles HF/AG) restent testables ; les mesures de
latence (< 300 ms) et de bascule sont indicatives ; le nombre de liens SCO simultanés (R1) est à mesurer, la valeur du
Pi 3 ne vaut pas pour le RTL8761B.
