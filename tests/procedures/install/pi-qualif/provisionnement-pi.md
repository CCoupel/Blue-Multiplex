# Procédure de Test — Provisionnement du Pi de qualification (issue #3)

**Version** : 0.1.0.x · **Date** : ____ · **Testeur** : QA (ou dev-backend en T1.8)
**Cible** : Ubuntu Server 26.04 LTS arm64 (codename `resolute`) · Référence : `docs/install-pi.md`
**Accès** : `ssh -i $SSH_KEY_PATH <utilisateur>@btmux-qualif.local` — `<utilisateur>` = `BTMUX_USER` (défaut `ubuntu`, UID 1000)

## Prérequis

- [ ] Pi flashé avec Raspberry Pi Imager (Ubuntu Server 26.04 LTS 64 bits) ; personnalisation **cloud-init** : hostname `btmux-qualif`, utilisateur, clé SSH publique, mot de passe SSH désactivé, pas de Wi-Fi ; Ethernet branché
- [ ] **Variante Bluetooth** choisie et notée (`BTMUX_BT_MODE`, défaut `dongle`) :
  - `dongle` (cible) : dongle USB RTL8761B branché sur rallonge USB, loin des ports USB 3 ; `dtoverlay=disable-bt` posé
  - `dongle-bi` (cible v0.2.0, `docs/install-pi.md` §6) : **deux** dongles TP-Link UB500 (RTL8761BU, `2357:0604`), `BTMUX_BT_MODE=dongle` ; jouer le **scénario 7**
  - `internal` (provisoire, Pi 3, `docs/install-pi.md` §10) : Bluetooth intégré (`hci0`, UART, Broadcom BCM43430A1) ; **pas** de `disable-bt`
  - Les étapes marquées *(dongle)* / *(internal)* ne s'appliquent qu'à leur variante ; les résultats `internal` sont indicatifs, pas la cible
- [ ] `.claude/agents/environments/qualif.env` renseigné (`SSH_KEY_PATH`, `DEPLOY_HOST`, éventuellement `BTMUX_USER`)
- [ ] Notation : `$U` = utilisateur de service, `$UID_U` = `id -u $U`

## Scénario 1 — Système et réseau

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `ssh $U@btmux-qualif.local hostname` | `btmux-qualif` ; connexion par clé, sans mot de passe (cloud-init) | | |
| 2 | `. /etc/os-release; echo $VERSION_CODENAME $VERSION_ID; uname -m` | `resolute 26.04` ; `aarch64` | | |
| 3 | `cloud-init status` | `status: done` | | |
| 4 | `grep -E 'disable-(bt\|wifi)' /boot/firmware/config.txt` | *(dongle)* `dtoverlay=disable-bt` et `dtoverlay=disable-wifi` présents (section `[all]`) — *(internal)* `disable-bt` **absent** ; `disable-wifi` facultatif | | |
| 5 | `ls /etc/netplan/ ; grep -l wifis /etc/netplan/* \|\| echo aucun` | *(dongle)* Aucun bloc `wifis:` ; `ip -br link` sans interface `wlan*` ; Ethernet actif — *(internal)* Wi-Fi toléré (SSH possible par Wi-Fi) mais coexistence 2,4 GHz à consigner | | |
| 6 | `systemctl is-active avahi-daemon` ; depuis le poste : `ping btmux-qualif.local` | `active` ; le nom `.local` se résout | | |
| 7 | `timeout 8 bluetoothctl list </dev/null` (le `timeout` est obligatoire : `bluetoothctl list` attend indéfiniment sans contrôleur) | **Un seul** contrôleur — *(dongle)* le dongle, le Bluetooth intégré est absent — *(internal)* `hci0` intégré | | |

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 2 — Paquets et versions (à consigner)

| Étape | Action | Résultat attendu | Valeur relevée | OK ? |
|-------|--------|------------------|----------------|------|
| 1 | `dpkg-query -W -f='${Version}\n' pipewire` | ≥ 1.2 (attendu ~1.6.2 sur resolute) | | |
| 2 | `dpkg-query -W -f='${Version}\n' wireplumber` | ≥ 0.5 (attendu ~0.5.13) | | |
| 3 | `dpkg-query -W -f='${Version}\n' bluez` | Présent (attendu ~5.85) | | |
| 4 | `python3 --version` ; `python3 -c 'import ensurepip'` | ≥ 3.12 (attendu 3.14.x) ; `ensurepip` disponible (`python3-venv`) | | |
| 5 | `dpkg -l libspa-0.2-bluetooth pipewire-audio linux-firmware bluez-tools alsa-utils avahi-daemon \| grep -c ^ii` | `6` (tous installés) | | |
| 6 | `uname -r` | Noyau noté | | |
| 7 | Exécuter le script de vérification de `docs/install-pi.md` §8 en tant que `$U`, avec `BTMUX_BT_MODE=<variante>` | Code 0, aucune ligne `ECHEC` (18 contrôles `OK` constatés en `internal` ; en `dongle` : mêmes contrôles + firmware rtl8761b, Wi-Fi absent) | | |

- [ ] Les valeurs ci-dessus sont reportées dans `docs/install-pi.md` §9 « Versions installées »

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 3 — Contrôleur Bluetooth : exécuter **une** variante (3-dongle ou 3-internal)

### Variante `dongle` — RTL8761B et firmware (`linux-firmware`) — cible

| Étape | Action | Résultat attendu | Valeur relevée | OK ? |
|-------|--------|------------------|----------------|------|
| 1 | `lsusb \| grep -i -E '0bda\|realtek'` | Dongle détecté | | |
| 2 | `ls /lib/firmware/rtl_bt/ \| grep 8761b` | **Fichiers `rtl8761b*` présents** (au moins `rtl8761bu_fw.bin`, et `rtl8761bu_config.bin` si fourni) dans `linux-firmware` ; sinon FAIL bloquant | | |
| 3 | `dpkg -S /lib/firmware/rtl_bt/rtl8761bu_fw.bin` | Appartient au paquet `linux-firmware` | | |
| 4 | `sudo dmesg \| grep rtl_bt` | Firmware chargé sans erreur (`rtl8761bu_fw`) | | |
| 5 | `sudo btmgmt info` | Contrôleur listé, Bluetooth 5.x ; noter le nombre de liens SCO si exposé (utile à l'issue #6) | | |
| 6 | `timeout 8 bluetoothctl list </dev/null` | `Controller <MAC> … [default]` ; **MAC relevée** | | |

- [ ] **MAC du dongle** consignée dans `docs/install-pi.md` §9 (elle identifie l'adaptateur dans la config — jamais `hci0`)
- [ ] Rallonge USB utilisée, dongle éloigné des ports USB 3

**Verdict dongle** : [ ] PASS [ ] FAIL [ ] N/A

### Variante `internal` — Bluetooth intégré du Pi 3 (provisoire, `docs/install-pi.md` §10)

| Étape | Action | Résultat attendu | Valeur relevée | OK ? |
|-------|--------|------------------|----------------|------|
| 1 | `grep '^dtoverlay=disable-bt' /boot/firmware/config.txt \|\| echo absent` | `absent` (sinon le retirer et redémarrer) | | |
| 2 | `ls /lib/firmware/brcm/ \| grep BCM43430A1.raspberrypi,3-model-b.hcd` ; `dpkg -S` de ce fichier | Fichier présent (paquet `linux-firmware-raspi`) | | |
| 3 | `sudo dmesg \| grep 'hci0: BCM'` | Firmware BCM chargé sans erreur (noter la version, ex. 001.002.009) | | |
| 4 | `sudo btmgmt info` | **Un** contrôleur `hci0`, bus UART, Broadcom BCM43430A1, Bluetooth 4.2 | | |
| 5 | `timeout 8 bluetoothctl list </dev/null` ; `systemctl is-active bluetooth` | `Controller <MAC> … [default]` (MAC du Pi, préfixe `B8:27:EB` sur Pi 3) ; `active` | | |
| 6 | `hciconfig -a hci0 \| grep -i sco` | SCO MTU relevé (ex. 64:1) ; nombre de liens SCO simultanés non exposé : à mesurer aux spikes (R1) | | |
| 7 | Routage SCO : `sudo hcitool cmd 0x3f 0x1d` (lecture seule) | Réponse notée (défaut constaté : `00 02 00 01 01` = PCM, routing 0). **Ne pas modifier** sauf essai documenté ; si `0x3f 0x1c 01 00 00 00 00` est essayé, relire `0x3f 0x1d` (attendu `01 00 00 00 00` = HCI) puis **restaurer la valeur d'origine** ; réglage volatil | | |
| 8 | Reporter `adapters[0].mac` = MAC relevée dans `/etc/btmux/config.yaml` ; `btmuxd --config /etc/btmux/config.yaml --check-config` | `config OK: …`, code 0 | | |

- [ ] MAC, firmware et SCO consignés dans `docs/install-pi.md` §9, **marqués « variante provisoire »**
- [ ] Limites reconnues (non bloquantes) : HCI sur UART, antenne partagée avec le Wi-Fi 2,4 GHz, BT 4.2, RAM ~894 Mo, SCO par HCI non testé ; mesures latence/qualité à reconfirmer avec le dongle
- [ ] **Retour au dongle** (quand disponible) : remettre `dtoverlay=disable-bt`, brancher le dongle, redémarrer, relever la nouvelle MAC, mettre à jour `adapters[0].mac`, rejouer la variante `dongle`

**Verdict internal** : [ ] PASS [ ] FAIL [ ] N/A

## Scénario 4 — Session PipeWire pour le service système (décision D2)

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `loginctl show-user $U -p Linger` | `Linger=yes` (`sudo loginctl enable-linger $U`) | | |
| 2 | **Redémarrer le Pi**, ne pas ouvrir de session, puis `ls /run/user/$UID_U/pipewire-0` | Socket présente sans login | | |
| 3 | `sudo -u $U XDG_RUNTIME_DIR=/run/user/$UID_U systemctl --user is-active pipewire wireplumber` | `active` pour les deux (services **utilisateur**, jamais `--system`) ; sinon appliquer `systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service` et le consigner | | |
| 4 | `sudo -u $U XDG_RUNTIME_DIR=/run/user/$UID_U wpctl status` | Arbre PipeWire sans erreur | | |
| 5 | `sudo systemd-run --uid=$U --pipe -E XDG_RUNTIME_DIR=/run/user/$UID_U pw-cli info 0` | Réussit : un service système sous `User=$U` atteint PipeWire (risque R3 levé) | | |
| 6 | `systemctl is-active bluetooth` | `active` | | |

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 5 — Drop-in d'utilisateur de service (`btmux-set-user.sh`)

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | Sans installation préalable : `BTMUX_DROPIN_DIR=$(mktemp -d -p _work/tmp) BTMUX_UID=1000 scripts/btmux-set-user.sh $U` (essai à blanc ; `BTMUX_UID` évite que le script résolve l'utilisateur via `id -u`, donc fonctionne sur le poste où `$U` n'existe pas ; `mkdir -p _work/tmp` au préalable, supprimer le dossier ensuite) | Affiche `btmux-set-user: btmuxd.service -> User=$U (uid …)` ; `user.conf` contient `User=$U`, `XDG_RUNTIME_DIR=/run/user/1000`, `After=`/`Wants=` `user@1000.service` | | |
| 2 | `scripts/btmux-set-user.sh 'Bad User'` | Code 2, message « nom d'utilisateur invalide » | | |
| 3 | Après un déploiement (procédure `deb-deploy`) : `systemctl cat btmuxd` | Unité livrée + drop-in `/etc/systemd/system/btmuxd.service.d/user.conf` généré pour `$U` | | |

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 6 — Chaîne d'accès depuis le poste de dev

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `ssh -i $SSH_KEY_PATH $U@btmux-qualif.local true` | Code 0, sans invite | | |
| 2 | `git check-ignore .claude/agents/environments/qualif.env` | Fichier ignoré | | |
| 3 | `README.md` | Contient un lien vers `docs/install-pi.md` | | |

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 7 — Variante `dongle-bi` : deux dongles UB500 (`docs/install-pi.md` §6, issue #18)

À jouer à la réception des dongles, **avant** toute séance radio (`revalidation-ub500/`). `$U` = utilisateur de service.

### 7a. Checklist de réception (matériel)

| Étape | Action | Résultat attendu | Valeur relevée | OK ? |
|-------|--------|------------------|----------------|------|
| 1 | Inspection : 2 × TP-Link UB500, chacun sur une **rallonge USB** (≥ 20 cm), loin des ports USB 3 et de l'antenne Wi-Fi ; étiqueter A / B | Conforme ; étiquettes posées | | |
| 2 | Les **deux dongles sur le même hub USB 2.0** du Pi ; noter la topologie | Hub unique noté (limite à rappeler dans les mesures du double saut #8) | | |
| 3 | Ethernet branché ; Wi-Fi désactivé (`dtoverlay=disable-wifi`) | `ip -br link` sans `wlan*` | | |
| 4 | `lsusb \| grep -c 2357:0604` | `2` | | |
| 5 | `lsusb -t` | Les deux sous le même hub USB 2.0, `Driver=btusb` | | |
| 6 | `dmesg \| grep -E 'rtl_bt\|rtl8761'` | Firmware `rtl8761bu_fw` chargé **pour chaque** dongle, aucune erreur `btusb`/`hci` | | |
| 7 | `ls /lib/firmware/rtl_bt/ \| grep 8761bu` | `rtl8761bu_fw.bin(.zst)` et `rtl8761bu_config.bin(.zst)` présents (`linux-firmware`) | | |
| 8 | `bluetoothctl list` (avec `timeout 8 … </dev/null`) ; `sudo btmgmt info` | **2** contrôleurs ; 2 index ; Bluetooth 5.x | | |
| 9 | `hciconfig -a \| grep -E '^hci\|Bus\|BD Address'` | 2 × `Bus: USB`, **aucun** `Bus: UART` | | |

### 7b. Bascule du Bluetooth interne vers les dongles

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `grep '^dtoverlay=disable-bt' /boot/firmware/config.txt` | **Présent** ; aucun reste de la variante `internal` (§10) | | |
| 2 | Redémarrer avec les deux dongles branchés | Pi joignable, 2 contrôleurs USB après reboot | | |
| 3 | Script de vérification §8 : `BTMUX_BT_MODE=dongle bash verif.sh` | Code 0 : 2 contrôleurs USB, 0 UART, `disable-bt` posé, aucune ligne `ECHEC` | | |
| 4 | `sudo /usr/lib/btmux/btmux-adapters.sh --config /etc/btmux/config.yaml --dry-run` | Pour chaque adaptateur : `<MAC> -> hciN`, alias, classe, `discov no` / `bondable off` ; **aucune** commande exécutée ; code 0 | | |
| 5 | `sudo systemctl enable --now btmux-adapters.service ; systemctl is-active btmux-adapters` | Service `oneshot` terminé en succès (`active (exited)`) | | |
| 6 | Après `sudo reboot` : `bluetoothctl show \| grep -E 'Alias\|Class'` pour chaque contrôleur | Alias et classe **persistants** (re-posés au boot par le service, identiques) | | |
| 7 | Débrancher un dongle, relancer `btmux-adapters.sh --dry-run` | Avertissement pour l'adaptateur absent, code 0 (ne bloque jamais le démarrage) ; rebrancher | | |
| 8 | `/etc/btmux/config.yaml` en forme bi (`sources` / `headsets`) puis `btmuxd --config … --check-config` | `config OK: …`, code 0 | | |

### 7c. Tableau MAC ↔ rôle ↔ port USB (à reporter dans `docs/install-pi.md` §6.4)

Port USB : `readlink -f /sys/class/bluetooth/hciN/device` (chemin `…/1-1.2/1-1.2:1.0` → port `1-1.2`).

| Rôle (`roles`) | Nom annoncé | Index actuel | MAC | Port USB | Rallonge (A/B) |
|----------------|-------------|--------------|-----|----------|----------------|
| `sources` (`hci-src`) | | | | | |
| `headsets` (`hci-hp`) | | | | | |

- [ ] Tableau complété et reporté ; `adapters[].mac` de la config = MAC relevées (jamais `hciN`)
- [ ] Permutation des deux dongles (échange des ports) + reboot : les rôles suivent les **MAC**, pas les index

**Verdict 7** : [ ] PASS [ ] FAIL [ ] N/A (variante non jouée)

## Critères de validation

- [ ] Scénarios 1 à 6 PASS (critères d'acceptation de l'issue #3)
- [ ] Versions installées et MAC du dongle consignées dans `docs/install-pi.md` §9
- [ ] Scénario 3 : au moins une variante PASS ; la cible `dongle` reste à valider avant la clôture du milestone (la variante `internal` seule ne suffit pas à lever les réserves de la cible)
- [ ] Variante `dongle-bi` : scénarios 3 (variante dongle) et 7 PASS pour la cible v0.2.0
- [ ] Variante `dongle` : présence des fichiers `rtl8761b*` dans `linux-firmware` confirmée (ou écart remonté au teamleader)

## Notes QA

