# Procédure de Test — Provisionnement du Pi de qualification (issue #3)

**Version** : 0.1.0.x · **Date** : ____ · **Testeur** : QA (ou dev-backend en T1.8)
**Accès** : `ssh -i $SSH_KEY_PATH pi@btmux-qualif.local` · Référence : `docs/install-pi.md`

## Prérequis

- [ ] Pi flashé selon `docs/install-pi.md` (Debian/Raspberry Pi OS Trixie 64 bits), Ethernet branché
- [ ] Dongle USB Bluetooth RTL8761B branché sur rallonge USB, loin des ports USB 3
- [ ] `.claude/agents/environments/qualif.env` renseigné (`SSH_KEY_PATH`, `DEPLOY_HOST`)

## Scénario 1 — Système et réseau

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `ssh pi@btmux-qualif.local hostname` | `btmux-qualif` ; connexion par clé, sans mot de passe | | |
| 2 | `cat /etc/os-release \| grep -E 'VERSION_CODENAME\|PRETTY'` ; `uname -m` | Trixie ; `aarch64` | | |
| 3 | `grep -E 'disable-bt' /boot/firmware/config.txt` | `dtoverlay=disable-bt` présent | | |
| 4 | `nmcli radio wifi` (ou `rfkill list wifi`) | Wi-Fi désactivé ; Ethernet actif | | |
| 5 | `hciconfig -a` / `bluetoothctl list` | **Un seul** contrôleur (le dongle) ; le Bluetooth intégré est absent | | |

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 2 — Paquets et versions (à consigner)

| Étape | Action | Résultat attendu | Valeur relevée | OK ? |
|-------|--------|------------------|----------------|------|
| 1 | `bluetoothctl --version` | BlueZ présent (noter la version) | | |
| 2 | `pipewire --version` | ≥ 1.2 | | |
| 3 | `wireplumber --version` | ≥ 0.5 | | |
| 4 | `python3 --version` | ≥ 3.12 ; `python3 -m venv --help` fonctionne | | |
| 5 | `dpkg -l libspa-0.2-bluetooth pipewire-audio firmware-realtek \| grep ^ii` | Les trois paquets installés | | |
| 6 | `uname -r` | Noyau noté | | |

- [ ] Les valeurs ci-dessus sont reportées dans `docs/install-pi.md` § « Versions installées »

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 3 — Dongle RTL8761B

| Étape | Action | Résultat attendu | Valeur relevée | OK ? |
|-------|--------|------------------|----------------|------|
| 1 | `lsusb \| grep -i -E '0bda\|realtek'` | Dongle détecté | | |
| 2 | `dmesg \| grep rtl_bt` | Firmware `rtl_bt/rtl8761bu_fw.bin` chargé, sans erreur | | |
| 3 | `sudo btmgmt info` | Contrôleur listé, alimenté possible ; noter le nombre de liens SCO si exposé (utile à l'issue #6) | | |
| 4 | `bluetoothctl list` | `Controller <MAC> … [default]` ; **MAC relevée** | | |

- [ ] **MAC du dongle** consignée dans `docs/install-pi.md` (elle identifie l'adaptateur dans la config — jamais `hci0`)
- [ ] Rallonge USB utilisée, dongle éloigné des ports USB 3

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 4 — Audio (PipeWire/WirePlumber) et session utilisateur (décision D2)

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `loginctl show-user pi -p Linger` | `Linger=yes` (`loginctl enable-linger pi`) | | |
| 2 | `systemctl --user -M pi@ is-active pipewire wireplumber` (ou `sudo -u pi XDG_RUNTIME_DIR=/run/user/1000 systemctl --user is-active pipewire wireplumber`) | `active` pour les deux, **sans session ouverte** | | |
| 3 | `sudo -u pi XDG_RUNTIME_DIR=/run/user/1000 wpctl status` | Affiche l'arbre PipeWire sans erreur | | |
| 4 | `sudo -u pi XDG_RUNTIME_DIR=/run/user/1000 pw-cli info 0` | Informations du core PipeWire (version) | | |
| 5 | `sudo systemd-run --uid=pi --pipe -E XDG_RUNTIME_DIR=/run/user/1000 pw-cli info 0` | Réussit : un service système sous `User=pi` atteint PipeWire (risque R3 levé) | | |

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 5 — Chaîne d'accès depuis le poste de dev

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | Depuis le poste : `ssh -i $SSH_KEY_PATH pi@btmux-qualif.local true` | Code 0, sans invite | | |
| 2 | Vérifier que `qualif.env` est ignoré par git (`git check-ignore`) | Fichier ignoré | | |
| 3 | `README.md` | Contient un lien vers `docs/install-pi.md` | | |

**Verdict** : [ ] PASS [ ] FAIL

## Critères de validation

- [ ] Scénarios 1 à 5 PASS (critères d'acceptation de l'issue #3)
- [ ] Versions installées et MAC du dongle consignées dans `docs/install-pi.md`

## Notes QA

