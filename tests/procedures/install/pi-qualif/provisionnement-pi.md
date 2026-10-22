# Procédure de Test — Provisionnement du Pi de qualification (issue #3)

**Version** : 0.1.0.x · **Date** : ____ · **Testeur** : QA (ou dev-backend en T1.8)
**Cible** : Ubuntu Server 26.04 LTS arm64 (codename `resolute`) · Référence : `docs/install-pi.md`
**Accès** : `ssh -i $SSH_KEY_PATH <utilisateur>@btmux-qualif.local` — `<utilisateur>` = `BTMUX_USER` (défaut `ubuntu`, UID 1000)

## Prérequis

- [ ] Pi flashé avec Raspberry Pi Imager (Ubuntu Server 26.04 LTS 64 bits) ; personnalisation **cloud-init** : hostname `btmux-qualif`, utilisateur, clé SSH publique, mot de passe SSH désactivé, pas de Wi-Fi ; Ethernet branché
- [ ] Dongle USB Bluetooth RTL8761B branché sur rallonge USB, loin des ports USB 3
- [ ] `.claude/agents/environments/qualif.env` renseigné (`SSH_KEY_PATH`, `DEPLOY_HOST`, éventuellement `BTMUX_USER`)
- [ ] Notation : `$U` = utilisateur de service, `$UID_U` = `id -u $U`

## Scénario 1 — Système et réseau

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `ssh $U@btmux-qualif.local hostname` | `btmux-qualif` ; connexion par clé, sans mot de passe (cloud-init) | | |
| 2 | `. /etc/os-release; echo $VERSION_CODENAME $VERSION_ID; uname -m` | `resolute 26.04` ; `aarch64` | | |
| 3 | `cloud-init status` | `status: done` | | |
| 4 | `grep -E 'disable-(bt\|wifi)' /boot/firmware/config.txt` | `dtoverlay=disable-bt` et `dtoverlay=disable-wifi` présents (section `[all]`) | | |
| 5 | `ls /etc/netplan/ ; grep -l wifis /etc/netplan/* \|\| echo aucun` | Aucun bloc `wifis:` ; `ip -br link` sans interface `wlan*` ; Ethernet actif | | |
| 6 | `systemctl is-active avahi-daemon` ; depuis le poste : `ping btmux-qualif.local` | `active` ; le nom `.local` se résout | | |
| 7 | `bluetoothctl list` | **Un seul** contrôleur (le dongle) ; le Bluetooth intégré est absent | | |

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
| 7 | Exécuter le script de vérification de `docs/install-pi.md` §8 (en tant que `$U`) | Code 0, aucune ligne `ECHEC` | | |

- [ ] Les valeurs ci-dessus sont reportées dans `docs/install-pi.md` §9 « Versions installées »

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 3 — Dongle RTL8761B et firmware (`linux-firmware`)

| Étape | Action | Résultat attendu | Valeur relevée | OK ? |
|-------|--------|------------------|----------------|------|
| 1 | `lsusb \| grep -i -E '0bda\|realtek'` | Dongle détecté | | |
| 2 | `ls /lib/firmware/rtl_bt/ \| grep 8761b` | **Fichiers `rtl8761b*` présents** (au moins `rtl8761bu_fw.bin`, et `rtl8761bu_config.bin` si fourni) dans `linux-firmware` ; sinon FAIL bloquant (point non vérifié en amont) | | |
| 3 | `dpkg -S /lib/firmware/rtl_bt/rtl8761bu_fw.bin` | Appartient au paquet `linux-firmware` | | |
| 4 | `sudo dmesg \| grep rtl_bt` | Firmware chargé sans erreur (`rtl8761bu_fw`) | | |
| 5 | `sudo btmgmt info` | Contrôleur listé, Bluetooth 5.x ; noter le nombre de liens SCO si exposé (utile à l'issue #6) | | |
| 6 | `bluetoothctl list` | `Controller <MAC> … [default]` ; **MAC relevée** | | |

- [ ] **MAC du dongle** consignée dans `docs/install-pi.md` §9 (elle identifie l'adaptateur dans la config — jamais `hci0`)
- [ ] Rallonge USB utilisée, dongle éloigné des ports USB 3

**Verdict** : [ ] PASS [ ] FAIL

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
| 1 | Sans installation préalable : `scripts/btmux-set-user.sh $U` avec `BTMUX_DROPIN_DIR=$(mktemp -d)` (essai à blanc, depuis le poste ou le Pi) | Affiche `btmux-set-user: btmuxd.service -> User=$U (uid …)` ; `user.conf` contient `User=$U`, `XDG_RUNTIME_DIR=/run/user/<uid>`, `After=`/`Wants=` `user@<uid>.service` | | |
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

## Critères de validation

- [ ] Scénarios 1 à 6 PASS (critères d'acceptation de l'issue #3)
- [ ] Versions installées et MAC du dongle consignées dans `docs/install-pi.md` §9
- [ ] Présence des fichiers `rtl8761b*` dans `linux-firmware` confirmée (ou écart remonté au teamleader)

## Notes QA

