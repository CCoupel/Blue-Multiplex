# Installation du Pi btmux (qualif puis prod)

> Procédure de provisionnement du Pi (v0.1.0 mono-adaptateur ; **v0.2.0 : deux dongles UB500**, §6). **OS cible : Ubuntu Server 26.04 LTS (arm64)**,
> image officielle Raspberry Pi. Statut : rédigée, **pas encore vérifiée** sur matériel — la vérification a lieu
> en phase 1.C (issue #3) ; la section « Versions installées » est complétée à ce moment-là.
> Le même Pi sert de qualif puis de prod.

## 1. Matériel

- **Raspberry Pi 4 Model B** : Pi de qualif (`pi-qualif`) depuis le 2026-10-26 (nouvelle alimentation officielle). Pi 5 possible ;
  Pi 3 B uniquement pour la variante provisoire historique (§10). Alimentation officielle, carte SD ≥ 16 Go, câble Ethernet.
- **2 dongles USB Bluetooth TP-Link UB500** (puce Realtek RTL8761BU, USB `2357:0604`), chacun sur une **rallonge USB**, éloignés des
  ports USB 3 (cible v0.2.0, §6). La v0.1.0 n'en utilisait qu'un (ou le Bluetooth interne du Pi 3, §10).

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
   (cloud-init) : hostname `pi-qualif`, utilisateur (le script de ce document suppose `ubuntu`, UID 1000, mais tout
   utilisateur convient), **clé SSH publique**, authentification par mot de passe désactivée, **pas de Wi-Fi**.
2. Désactiver le Bluetooth intégré et le Wi-Fi dans `/boot/firmware/config.txt` (section `[all]`) :

   ```
   dtoverlay=disable-bt
   dtoverlay=disable-wifi
   ```

3. Vérifier qu'aucun Wi-Fi n'est configuré : `ls /etc/netplan/` ne doit pas contenir de bloc `wifis:`
   (sinon le retirer, puis `sudo netplan apply`). Seul Ethernet reste actif.
4. Redémarrer ; le Pi doit être joignable : `ssh <utilisateur>@pi-qualif.local` (nécessite `avahi-daemon`, installé
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
  via `scripts/btmux-set-user.sh` (installé en `/usr/lib/btmux/btmux-set-user.sh` par le paquet) ;
- la session utilisateur doit exister sans login : `sudo loginctl enable-linger <utilisateur>` ;
- PipeWire/WirePlumber tournent en **services utilisateur** (jamais `--system`). Ubuntu les active à l'installation ;
  sinon : `systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service`.

Vérifier (après reboot, sans session ouverte) : `loginctl show-user <utilisateur> -p Linger` → `Linger=yes` et
`ls /run/user/$(id -u <utilisateur>)/pipewire-0`.

### 5 ter. API HTTP : HTTP clair sur le LAN

`btmuxd` écoute par défaut sur `0.0.0.0:8088` en **HTTP non chiffré** (jeton Bearer statique dans `/etc/btmux/token`, mode
0600 obligatoire : un jeton lisible par le groupe ou les autres verrouille l'API). Le journal porte alors
`api_listening_cleartext` (avertissement). HTTPS est prévu en #22 (v0.3.0) ; en attendant, réserver l'API à un LAN de confiance
ou la limiter au local avec `api.listen: "127.0.0.1:8088"` (accès distant par tunnel SSH).

**Port 8088** : si un pare-feu est actif (`sudo ufw status`), n'autoriser `8088/tcp` que depuis le LAN de confiance. Le
changement de `api.listen` se fait dans `/etc/btmux/config.yaml`, puis `sudo systemctl restart btmuxd`.

**Smoke de l'API** (sans jeton : la route de vivacité est publique) :

```bash
curl -s http://127.0.0.1:8088/api/health        # 200 : {"version": "0.2.0.x", "adapters": N}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8088/   # 200 : Web UI
```

Un `401` sur `/api/state` sans jeton est attendu ; avec `Authorization: Bearer $(sudo cat /etc/btmux/token)`, il doit répondre 200.

### 5 bis. WirePlumber en mode headless : désactiver `seat-monitoring` (obligatoire)

Sur un serveur sans session graphique (aucun *seat* logind, cas de `btmuxd` sous un utilisateur avec linger),
WirePlumber n'active pas son moniteur Bluetooth : BlueZ ne reçoit alors **aucun point de terminaison A2DP/HFP** et
n'annonce que AVRCP — le Pi n'apparaît pas comme casque. Constaté sur `pi-qualif` (spike #5, 2026-10-22).

Le fichier est livré dans le dépôt : `config/wireplumber/51-btmux-no-seat.conf` ; `scripts/deploy.sh` et le `postinst`
du `.deb` l'installent dans le home de l'utilisateur de service, **sans écraser un fichier existant**. Installation
manuelle (en tant qu'utilisateur de service) :

```bash
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
cat > ~/.config/wireplumber/wireplumber.conf.d/51-btmux-no-seat.conf <<'CONF'
wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}
CONF
systemctl --user restart wireplumber
```

**Mise à jour** : le fichier déjà présent n'est **jamais écrasé** (ni par `deploy.sh`, ni par le `postinst`, ni lors d'une
mise à jour du paquet). Si une version ultérieure de btmux modifie ce fichier, comparer manuellement avec
`/usr/share/btmux/wireplumber/51-btmux-no-seat.conf` (ou `config/wireplumber/` dans le dépôt) et reporter les changements.
Si `BTMUX_USER` diffère de l'utilisateur SSH de déploiement, le fichier est créé par root avec le propriétaire de
`BTMUX_USER` (`install -o`), la source restant dans un répertoire temporaire privé.

Vérifier : `bluetoothctl show | grep UUID` doit lister **Audio Sink (110b)**, **Audio Source (110a)**, **Handsfree
Audio Gateway (111f)** et **Handsfree (111e)** en plus de AVRCP. Retour arrière : supprimer le fichier et
redémarrer `wireplumber`.

> **Alias non persistant (spike #7, 2026-10-23)** : `btmgmt name btmux` ne survit pas au reboot ; après redémarrage,
> le téléphone voyait encore « pi-qualif ». Le correctif (`bluetoothctl system-alias` ou `Name=` dans `main.conf`) est
> prévu en v0.2.0 (#18). En attendant, le nom peut être reposé à la main après reboot (`bluetoothctl system-alias btmux`,
non vérifié sur le Pi).

## 6. Deux dongles UB500 (cible bi-adaptateur)

Deux dongles **TP-Link UB500** (Realtek RTL8761BU, USB `2357:0604`) : `hci-src` (rôle `sources`, vu comme un casque par les PC et
téléphones) et `hci-hp` (rôle `headsets`, vu comme une source par les casques). Les noms `hci-src`/`hci-hp` désignent des rôles,
jamais des index `hciN` (qui changent) : l'identification se fait par **adresse MAC** (`adapters[].mac`).

### 6.1 Branchement

- Chaque dongle sur une **rallonge USB** (≈ 20 cm ou plus), éloigné des ports USB 3 et de l'antenne Wi-Fi.
- **Les deux dongles sur le même hub USB 2.0 du Pi** : sur Pi 4, les ports USB 2.0 du hub interne (bus 001, 480 Mbit/s) ;
  le bus USB 3 (5000 Mbit/s) reste vide. Les UB500 sont des périphériques USB 1.1 (12 Mbit/s) : le débit du hub n'est pas le
  facteur limitant. C'est la configuration des mesures du double saut (#8) : noter dans les relevés qu'ils partagent un seul
  hub USB 2.0 (480 Mbit/s partagés), ce qui est une limite à rappeler dans les résultats. Pi 3 : les ports partagent un unique
  contrôleur avec l'Ethernet (variante historique).
- Ethernet branché ; Wi-Fi désactivé (`dtoverlay=disable-wifi`) pour les mesures. **Au 2026-10-26, pi-qualif n'a pas
  `disable-wifi`** : `wlan0` reste actif (SSH par Wi-Fi), à consigner dans les relevés (§9.1).

### 6.2 Checklist de réception (avant tout appairage)

```bash
lsusb | grep -c 2357:0604                   # 2
lsusb -t                                    # les deux sous le même hub USB 2.0 (Driver=btusb)
dmesg | grep -E "rtl_bt|rtl8761"            # firmware rtl8761bu_fw chargé pour chaque dongle, sans erreur
ls /lib/firmware/rtl_bt/ | grep 8761bu      # rtl8761bu_fw.bin(.zst), rtl8761bu_config.bin(.zst)
bluetoothctl list                           # 2 contrôleurs : "Controller <MAC> ... "
sudo btmgmt info                            # 2 index, version Bluetooth 5.x
hciconfig -a | grep -E "^hci|Bus|BD Address" # 2 × « Bus: USB », aucun « Bus: UART »
# Sous-tension : vcgencmd est indisponible sur Ubuntu 26.04 (/dev/vcio absent) → capteur hwmon rpi_volt
for d in /sys/class/hwmon/hwmon*; do [ "$(cat "$d/name" 2>/dev/null)" = rpi_volt ] && echo "in0_lcrit_alarm : $(cat "$d/in0_lcrit_alarm")"; done   # 0 attendu
dmesg | grep -ci "under-voltage"            # 0 attendu
```

- [x] 2 dongles détectés (`2357:0604`), firmware `rtl8761bu` chargé pour les deux, 0 erreur USB (-110 / -71) — relevé V-0 du 2026-10-26 (§9.1).
- [x] 2 contrôleurs BlueZ, **tous deux sur le bus USB, aucun sur UART** (`dtoverlay=disable-bt` présent).
- [x] Pas de sous-tension : `in0_lcrit_alarm` = 0, aucune occurrence under-voltage dans `dmesg` (relevé du 2026-10-26).
- [ ] Rallonges en place, dongles éloignés de l'USB 3 : **à confirmer physiquement** (le système ne lit pas le connecteur USB 2/3 utilisé). Hub USB 2.0 unique noté (§6.1, §9.1).
- [x] MAC des deux contrôleurs relevées (tableau 6.4) et reportées dans `adapters[].mac`.

### 6.3 Bascule du Bluetooth interne vers les dongles

1. `/boot/firmware/config.txt` : **`dtoverlay=disable-bt`** présent (plus aucun usage radio du Bluetooth interne) ; retirer toute
   configuration de la variante du §10.
2. Brancher les deux dongles, **redémarrer** le Pi.
3. Lancer le script du §8 avec **`BTMUX_BT_MODE=dongle`** : il exige 2 contrôleurs USB, 0 UART, `disable-bt` posé.
4. Installer l'identité persistante des adaptateurs (service `btmux-adapters`, livré par le paquet / `scripts/deploy.sh`) :
   `sudo /usr/lib/btmux/btmux-adapters.sh --dry-run` d'abord, puis `sudo systemctl enable --now btmux-adapters.service`.

### 6.4 Tableau MAC ↔ rôle ↔ port USB (à compléter à la réception)

Port USB d'un contrôleur : `readlink -f /sys/class/bluetooth/hciN/device` (chemin `…/1-1.2/1-1.2:1.0` → port `1-1.2`).

| Rôle (`roles`) | Nom annoncé | Index actuel | MAC du contrôleur | Port USB | Rallonge |
|----------------|-------------|--------------|-------------------|----------|----------|
| `sources` (`hci-src`) | `btmux` | hci1 | `18:69:45:42:9D:E2` | `1-1.2` (hub USB 2 du Pi 4) | non relevée (connecteur non lisible) |
| `headsets` (`hci-hp`) | `btmux-hp` | hci0 | `18:69:45:42:B5:54` | `1-1.1` (hub USB 2 du Pi 4) | non relevée (connecteur non lisible) |

Relevé V-0 du 2026-10-26 sur `pi-qualif` (Pi 4). Les index `hciN` peuvent changer au reboot : la colonne « Index actuel » est
indicative, la correspondance se fait par MAC.

### 6.5 Rebrancher un dongle : un à la fois (#23)

- **Consigne** : brancher (ou rebrancher) **un dongle à la fois** et attendre **≈ 10 s** que son identité soit posée
  (nom `btmux` / `btmux-hp`, classe) avant de brancher le suivant.
- Si deux dongles apparaissent à quelques secondes d'écart, le second peut recevoir son identité **≈ 60–70 s plus tard**
  au lieu de quelques secondes. Rien n'est perdu : la correction est automatique, il suffit d'attendre.
- **Cas non maîtrisable** : une réinitialisation USB (par exemple une sous-tension) qui fait réapparaître les deux dongles
  d'un coup → rattrapage automatique en **≈ 60–70 s**. Utiliser une alimentation suffisante pour l'éviter.

## 7. Vérifications PipeWire / BlueZ

```bash
systemctl is-active bluetooth               # active
wpctl status                                # PipeWire + WirePlumber répondent
pw-cli info 0 | grep -E "version|name"      # version PipeWire
```

## 8. Script de vérification

À exécuter **en tant qu'utilisateur de service** (variable `BTMUX_USER` pour un autre utilisateur ; `BTMUX_BT_MODE=internal` pour la variante provisoire du §10 ; défaut `dongle` = deux UB500, §6). Il échoue
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
  grep -q '^dtoverlay=disable-bt' /boot/firmware/config.txt && ok "disable-bt posé" || ko "disable-bt absent (Bluetooth interne actif)"
  [ "$(lsusb 2>/dev/null | grep -c 2357:0604)" -eq 2 ] && ok "2 dongles UB500 (2357:0604)" || ko "dongles UB500 : $(lsusb 2>/dev/null | grep -c 2357:0604) (2 attendus)"
  ls /lib/firmware/rtl_bt/ 2>/dev/null | grep -q 8761bu && ok "firmware rtl8761bu présent" || ko "firmware rtl8761bu absent"
  [ "$(sudo dmesg 2>/dev/null | grep -c 'rtl_bt/rtl8761bu_fw')" -ge 1 ] && ok "firmware rtl_bt chargé" || ko "pas de trace rtl_bt (dmesg)"
  hc=$(timeout 8 hciconfig -a 2>/dev/null)
  [ "$(printf '%s\n' "$hc" | grep -c 'Bus: USB')" -eq 2 ] && ok "2 contrôleurs sur le bus USB" || ko "contrôleurs USB : $(printf '%s\n' "$hc" | grep -c 'Bus: USB') (2 attendus)"
  [ "$(printf '%s\n' "$hc" | grep -c 'Bus: UART')" -eq 0 ] && ok "0 contrôleur UART" || ko "contrôleur UART présent (Bluetooth interne actif)"
fi
bl=$(timeout 8 bluetoothctl list </dev/null 2>/dev/null)   # timeout : bluetoothctl attend sans contrôleur
want=1; [ "$mode" = dongle ] && want=2   # 2 contrôleurs USB en bi-adaptateur
n=$(printf '%s\n' "$bl" | grep -c '^Controller'); [ "$n" -eq "$want" ] && ok "$want contrôleur(s): $bl" || ko "$n contrôleur(s) ($want attendu(s))"
timeout 8 bluetoothctl show </dev/null 2>/dev/null | grep -q 0000110b- && ok "profil A2DP sink exposé (WirePlumber headless OK)" || ko "pas d'UUID Audio Sink : voir §5 bis (seat-monitoring)"
if ip -br link | grep -q '^wlan'; then
  [ "$mode" = internal ] && ok "Wi-Fi présent (toléré en mode internal)" || ko "interface wlan présente (Wi-Fi à désactiver)"
else ok "pas de Wi-Fi"; fi
exit $fail
```

## 9. Versions installées

### 9.1 Cible dongle — Raspberry Pi 4 Model B (relevé du 2026-10-26)

Relevé lecture seule V-0 sur `pi-qualif` (`ubuntu@<IP-du-Pi>`), avec les deux dongles UB500 (cible v0.2.0, §6).

| Élément | Relevé |
|---------|--------|
| Matériel | Raspberry Pi 4 Model B Rev 1.1 |
| OS / noyau | Ubuntu 26.04.1 LTS, noyau 7.0.0-1020-raspi |
| Dongles `2357:0604` | 2 (attendu 2) — ports : `1-1.1` (hci0, `headsets`) et `1-1.2` (hci1, `sources`), hub USB 2 du Pi 4 (bus 001, 480M) ; bus USB 3 (002) vide |
| Contrôleurs | hci0 `18:69:45:42:B5:54` « btmux-hp » classe 0x6C010C (headsets) ; hci1 `18:69:45:42:9D:E2` « btmux » classe 0x6C0404 (sources) ; UP RUNNING, Realtek, **HCI/LMP 5.1**, SCO MTU 255:12 |
| Firmware | `rtl8761bu` 0xdfc6d922, chargé sans erreur pour hci0 et hci1 |
| Bus | 2 × USB, **0 contrôleur UART** ; `dtoverlay=disable-bt` présent |
| `dtoverlay=disable-wifi` | **absent** : `wlan0` UP (192.168.1.51/24), `eth0` DOWN (pas de câble) — Wi-Fi actif, à consigner |
| Sous-tension | `vcgencmd get_throttled` indisponible (`/dev/vcio` absent) ; équivalent : hwmon `rpi_volt` `in0_lcrit_alarm` = 0 ; 0 occurrence under-voltage dans `dmesg` (§6.2) |
| Erreurs USB | 0 erreur -110 / -71 dans `dmesg` ; 2 ré-énumérations de dongles après boot (hci0 puis hci1), sans erreur |
| Services | `btmuxd` actif ; `GET /api/controllers` : 2 contrôleurs présents, `roles` sources = `9D:E2`, headsets = `B5:54`, `pending=false` ; 1 appareil connecté sur `sources`, 0 sur `headsets` |

Seules les MAC des dongles et du Pi sont citées ; aucune MAC d'appareil tiers n'a été relevée.

### 9.2 Historique — Raspberry Pi 3 B, variante Bluetooth interne (relevé du 2026-10-22)

Relevé du **2026-10-22** sur `pi-qualif`, alors en **variante provisoire Bluetooth interne** (§10) : le dongle RTL8761B
n'était pas encore disponible. Ce relevé ne vaut plus pour la cible (Pi 4, dongles) ; conservé pour l'historique.

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
| Dongle RTL8761B | non disponible (à relever : MAC, `btmgmt`, SCO). Clés USB testées le 2026-10-22 : ANT+ USBStick2 (0fcf:1008), manette Xbox 360 (045e:028e), Wi-Fi RTL8192EU (2357:0109, « BT=0 ») — **aucune n'est un adaptateur Bluetooth** (pas de `btusb`, un seul contrôleur) |

> `dtoverlay=disable-wifi` est à poser **après** branchement de l'Ethernet (sinon le Pi devient injoignable en
> SSH), puis redémarrer.
> `bluetoothctl list` attend indéfiniment quand aucun contrôleur n'existe : le script du §8 utilise `timeout`.

## 10. Variante provisoire historique : Bluetooth interne (Pi 3)

> **Historique** : cette variante a servi avant la réception des dongles. Elle n'est plus utilisée sur `pi-qualif`
> (Pi 4, deux UB500 depuis le 2026-10-26). Conservée pour référence.

Tant que le dongle RTL8761B n'était pas disponible, les spikes ont pu utiliser le Bluetooth intégré du Pi 3 Model B
(Broadcom/Cypress 43438 sur UART). **Ce n'était pas la cible** : résultats de latence, de qualité et de nombre de liens
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
- **Classe d'appareil annoncée** : avec les quatre rôles (A2DP sink+source, HFP HF+AG) la classe réelle est
  **0x006C0404** (majeur Audio/Video, mineur Wearable Headset), et non 0x240404 : les bits de service *Capturing*
  (0x080000) et *Telephony* (0x400000) sont ajoutés par le noyau à cause des profils HFP (AG et HF), `btmgmt class`
  ne fixant que majeur/mineur. Relevé le 2026-10-22 ; l'effet sur la vue de Windows est l'objet du spike #5 (risque R4,
  variante à rôles restreints préparée dans `spikes/05-exposure/50-btmux-roles.conf`).
- **Un seul contrôleur** : en mono-adaptateur, le même `hci0` fait casque pour les sources et source pour les casques
  (limite connue de la v0.1.0, indépendante de la variante).
- **Bluetooth 4.2** (et non 5.x) : pas de LE 2M ni d'extensions BT 5 ; sans effet sur A2DP/HFP classiques.
- **RAM** : 894 Mo (510 Mo disponibles au repos).

Impact sur les spikes #5 à #10 : A2DP sink/source, AVRCP, HFP (rôles HF/AG) restent testables ; les mesures de
latence (< 300 ms) et de bascule sont indicatives ; le nombre de liens SCO simultanés (R1) est à mesurer, la valeur du
Pi 3 ne vaut pas pour le RTL8761B.

## 11. Preuves de spikes avant commit (dépôt public)

Les sorties brutes des spikes (`spikes/*/out/`, `*.snoop`) ne sont jamais commitées (`.gitignore`). Toute preuve copiée
sous `docs/spikes/` passe **avant commit** par `spikes/common/mask_evidence.py` (adresses MAC des appareils tiers
remplacées, scans de voisinage et noms personnels retirés, MAC du Pi conservée) :

```bash
python spikes/common/mask_evidence.py --pi-mac <MAC du Pi> --check docs/spikes   # code 0 attendu
```

Critère d'acceptation (point 5.11) : [procédure QA du spike #5](../tests/procedures/spikes/05-exposure/exposition-mono-adaptateur.md).

## 12. Mise à jour vers le paquet 0.2.0

Un `.deb` 0.2.0 installé sur un Pi en 0.1.0 :

- **Environnement Python** : le venv `/opt/btmux` est réutilisé s'il est complet (`pip` présent), sinon recréé. Les
  dépendances sont installées depuis le lockfile haché (`--require-hashes --only-binary=:all:`), puis la wheel est
  installée sans index (`--no-index`). Le réseau n'est requis que pour une dépendance absente du venv.
- **Configuration** : `/etc/btmux/config.yaml` n'est **jamais réécrit** (il est créé depuis l'exemple seulement s'il est
  absent). Une configuration mono-adaptateur v0.1.0 reste valide ; ajouter le second adaptateur est une modification manuelle.
- **Jeton d'API** : `/etc/btmux/token` est conservé ; il n'est généré que s'il manque.
- **Utilisateur de service** : déterminé comme à l'installation (`BTMUX_USER`, drop-in existant, sinon `sudo`, sinon `ubuntu`).
- **Redémarrage des services** : `btmux-adapters` et `btmuxd` sont redémarrés à l'installation (sauf `--no-restart`),
  puis la policy D-Bus est rechargée ; un fichier WirePlumber déjà présent n'est pas modifié (§5 bis).
