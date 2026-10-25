# Procédure de Test — Redémarrage piloté après changement de rôles (#23, D3)

**Version** : indépendante du build (0.2.0.x) · **Date** : ____ · **Testeur** : QA
**Cible** : Pi de qualif (Ubuntu 26.04 arm64), `btmuxd` déployé avec les unités `btmux-adapters.path`, `btmux-adapters-reload.service`, `btmux-adapters-identity.path` et `btmux-adapters-identity.service` · **Tag** : `hardware`
**Équivalent mock** : `tests/integration/api/controllers/` (coupure simulée) ; ici on prouve le comportement réel (systemd, codes de sortie). Pas de systemd en CI.

## Prérequis

- [ ] `/deploy qualif` joué ; `systemctl is-enabled btmux-adapters.path` → `enabled`, `systemctl is-active btmux-adapters.path` → `active` ; idem pour `btmux-adapters-identity.path`
- [ ] `btmuxd` actif, `btmuxctl controllers` liste ≥ 2 contrôleurs (dongles UB500) ; noter `SRC` (rôle sources), `HP` (rôle headsets)
- [ ] Aucun appareil connecté (sauf scénario 3), aucune fenêtre d'appairage ouverte
- [ ] Un terminal avec `journalctl -u btmuxd -u btmux-adapters-reload -u btmux-adapters-identity -f` (les sorties `btmux-adapters:` de l'ExecStartPre apparaissent sous `btmuxd`) ouvert pendant toute la procédure
- [ ] `/var/lib/btmux/` existe, propriétaire = utilisateur de service, mode 0750

## Scénarios

### Scénario 1 — Permutation des rôles : écriture, `.path`, redémarrage, retour

**Validation** : AUTO — **Issues** : #23

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `btmuxctl roles set --sources $HP --headsets $SRC` ; chronométrer | Code 0 ; `roles.pending=true`, `restart_expected=true` | | |
| 2 | `stat -c '%a' /var/lib/btmux/adapters.yaml` ; `cat` du fichier | Mode `640` ; sources = `$HP`, headsets = `$SRC`, schéma identique à `adapters` de config.yaml | | |
| 3 | Journal | `btmux-adapters.path` déclenche `btmux-adapters-reload.service` (simple `systemctl restart`) ; arrêt propre de `btmuxd` (SIGTERM) < 1 s après l'écriture ; **une seule** passe `btmux-adapters:` (ExecStartPre de `btmuxd`, lignes `alias=… classe=…`) ; **pas** de `restart_fallback` ; **un seul** démarrage de `btmuxd` | | |
| 4 | Boucler `btmuxctl state` toutes les secondes | API injoignable pendant la coupure ≈ 15–20 s (dont ≈ 4 s d'ExecStartPre), puis réponse | | |
| 5 | `btmuxctl controllers` après retour | `roles.sources=$HP`, `roles.headsets=$SRC`, `source=state`, `pending=false`, `restart_expected=false` | | |
| 6 | `bluetoothctl list` / `btmuxctl state` | Classe 0x006C0404 et alias du rôle (`btmux`) portés par le nouveau contrôleur sources ; `adapters[]` reflète la permutation | | |
| 7 | Rétablir : `btmuxctl roles set --sources $SRC --headsets $HP` et attendre le retour | Situation initiale rétablie | | |

**Verdict** : [ ] PASS  [ ] FAIL

### Scénario 2 — Écritures refusées pendant `change_pending`

**Validation** : AUTO — **Issues** : #23

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | Lancer le scénario 1 étape 1, puis immédiatement `btmuxctl pairing open sources 60` | Code 1, erreur `change_pending` (409) | | |
| 2 | Immédiatement `btmuxctl roles set …` (autre affectation) | Code 1, `change_pending` | | |
| 3 | *(informatif)* Lectures pendant la fenêtre `change_pending` | **Non observable sur Pi 3 B** : le service est arrêté en < 0,3 s, aucune lecture ne passe dans la fenêtre. Couvert par `tests/integration/api/controllers/` (`test_change_pending_blocks_every_write_but_not_reads` : lectures 200, écritures 409). Ne pas compter cette étape dans le verdict | n/a | n/a |
| 4 | Après le retour du service | Les écritures refusées n'ont laissé aucune fenêtre ouverte ni changement | | |

**Verdict** : [ ] PASS  [ ] FAIL

### Scénario 3 — Appareils connectés : confirmation puis déconnexion

**Validation** : AUTO — **Issues** : #23

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | Connecter une source et un casque (appairés) | `btmuxctl state` : `connected=true` | | |
| 2 | `btmuxctl roles set --sources $HP --headsets $SRC` | Code 1, 409 `devices_connected`, `details` listant les appareils ; fichier d'état inchangé | | |
| 3 | Même commande avec `--confirm` | Code 0 ; les appareils sont déconnectés **avant** l'écriture ; redémarrage comme au scénario 1 | | |
| 4 | Après retour | Aucun appareil connecté sur les rôles affectés ; rétablir l'affectation initiale | | |

**Verdict** : [ ] PASS  [ ] FAIL

### Scénario 4 — Repli code 4 si `btmux-adapters.path` est arrêtée

**Validation** : AUTO — **Issues** : #23

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `sudo systemctl stop btmux-adapters.path` (`mask` impossible : l'unité est un fichier de `/etc/systemd/system`) | Unité `inactive` | | |
| 2 | `btmuxctl roles set --sources $HP --headsets $SRC` | Code 0 (202) ; `pending=true` | | |
| 3 | Attendre ≈ 30 s sans rien faire | Journal `restart_fallback` ; `btmuxd` sort en **code 4** (`systemctl show btmuxd -p ExecMainStatus`) | | |
| 4 | Attendre ≈ 30 s de plus (`RestartSec=30`) | systemd relance `btmuxd` (`RestartForceExitStatus=4`) ; journal : passe `btmux-adapters:` de l'ExecStartPre (`$HP` → `rôles=sources alias=… classe='4 4'`) **avant** le démarrage du daemon ; le service revient avec la nouvelle affectation | | |
| 4b | `bluetoothctl show $HP` et `bluetoothctl show $SRC` (ou `busctl get-property org.bluez /org/bluez/hciN org.bluez.Adapter1 Alias Class`) | `$HP` (nouveau sources) : alias du rôle (`btmux`), classe 0x006C0404 (casque) ; `$SRC` (nouveau headsets) : alias du rôle (`btmux-hp`), classe « ordinateur » ; les deux `Pairable: no`, `Discoverable: no` | | |
| 4c | Depuis le PC Windows (recherche d'appareils pendant une fenêtre `btmuxctl pairing open sources 60`) | btmux apparaît comme **casque** (icône audio), plus comme ordinateur | | |
| 5 | Nettoyage : `sudo systemctl start btmux-adapters.path`, rétablir l'affectation initiale | `is-active` = `active` | | |

**Verdict** : [ ] PASS  [ ] FAIL

### Scénario 5 — Contrôleur sans rôle fermé, `role_unassigned`

**Validation** : AUTO — **Issues** : #23

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `btmuxctl roles set --sources $SRC --headsets none` puis attendre le retour | `roles.headsets=null` ; le contrôleur `$HP` : `role=null`, `pairable=false`, `discoverable=false` ; `btmgmt`/`bluetoothctl show` confirme | | |
| 2 | `btmuxctl pairing open headsets 60` | Code 1, 409 `role_unassigned` | | |
| 3 | Journal au démarrage | Aucun arrêt en code 3 ; démarrage normal malgré un rôle non affecté | | |
| 4 | Rétablir l'affectation initiale | Fenêtre `headsets` à nouveau ouvrable | | |

**Verdict** : [ ] PASS  [ ] FAIL

### Scénario 6 — Hotplug d'un contrôleur : identité réappliquée sans redémarrage

**Validation** : AUTO — **Issues** : #23 — *Émulation* : `echo <usb-id> | sudo tee /sys/bus/usb/drivers/usb/unbind` puis `bind` (`<usb-id>` de `/sys/class/bluetooth/<hciN>/device/..`) ; le débranchement physique est rejoué au GATE 4.

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `btmuxctl pairing open sources 60` (fenêtre sur l'**autre** contrôleur `$SRC`, à rouvrir si elle expire pendant le scénario) ; relever `systemctl show btmuxd -p MainPID` ; ouvrir `GET /api/events` (curl avec jeton) ; lancer en parallèle un sondage `while sleep 1; do curl -fsS -m 2 -H "Authorization: Bearer $T" .../api/health; done` | Premier événement : `state` complet (6 clés) ; sondage 200 ; `pairing.open=true` (sources) | | |
| 2 | `unbind` du dongle `$HP` (rôle affecté) | Événement `controllers` : `present=false` ; `PUT roles` vers ce MAC → 400 `unknown_controller` | | |
| 3 | `bind`, chronométrer jusqu'à la classe rétablie | Événement `controllers` : `present=true` ; le daemon ferme le contrôleur aussitôt (`Pairable/Discoverable no`) | | |
| 4 | Journal ≤ 10 s après `bind` ; `cat /var/lib/btmux/identity.request` | `identity_requested hci=… mac=…` (une fois) ; fichier : `<ISO UTC>\t<hciN>\t<MAC de $HP en majuscules>`, mode 640 ; l'unité exécute `btmux-adapters.sh … --only <MAC de $HP>` (visible dans `systemctl status`/journal) ; `btmux-adapters-identity.service` : `systemctl show -p Result btmux-adapters-identity.service` = `success` | | |
| 5 | `bluetoothctl show $HP` | Classe `0x6c0404` (sources) ou `0x6c010c` (headsets) selon le rôle ; alias du rôle (`btmux` / `btmux-hp`) ; `Pairable: no`, `Discoverable: no` | | |
| 6 | `systemctl show btmuxd -p MainPID` + sondage de l'étape 1 | **Même PID** (aucun redémarrage de `btmuxd`) ; l'API n'a jamais été coupée (aucun échec du sondage) | | |
| 7 | Rejouer étapes 2–3 avec un contrôleur **sans rôle** (ou après `roles set … none`) | Aucune ligne `identity_requested` ; contrôleur fermé (`Pairable/Discoverable no`) | | |
| 8 | Après étape 3, aucune nouvelle ligne `identity_requested` (pas de boucle alias/classe → requête) | Une seule requête par réapparition | | |
| 9 | **Autre contrôleur épargné** : `bluetoothctl show $SRC` + `btmuxctl state` juste après la passe d'identité de `$HP` | `$SRC` : toujours `Pairable: yes`, `Discoverable: yes` (BlueZ), cohérent avec l'API (`pairing.open=true`, `adapter=sources`, `controllers[$SRC].pairable/discoverable=true`) ; la fenêtre n'a pas été refermée par la passe (le journal ne montre aucune fermeture de `$SRC`) | | |
| 10 | **Réémission bornée** : altérer la classe de `$HP` hors rôle (`sudo btmgmt --index <N> class 1 1`) ; attendre ≤ 10 s | Nouvelle ligne `identity_requested` (classe observée ≠ rôle) puis classe du rôle rétablie par la passe | | |
| 11 | Re-altérer la classe de `$HP` **moins d'une minute** après l'étape 10 | **Pas** de nouvelle requête (au plus 1 par contrôleur et par minute) ; la classe reste altérée jusqu'à la minute écoulée, puis une requête est réémise au changement suivant | | |
| 12 | Rétablir : `sudo systemctl start btmux-adapters-identity.service` ou attendre la réémission ; fermer la fenêtre `btmuxctl pairing close` | Classe du rôle sur `$HP`, aucune fenêtre ouverte | | |

**Verdict** : [ ] PASS  [ ] FAIL

### Scénario 7 — L'alias suit le rôle après permutation

**Validation** : AUTO — **Issues** : #23

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `bluetoothctl show $SRC` et `bluetoothctl show $HP` | Avant : `$SRC` alias `btmux`, `$HP` alias `btmux-hp` | | |
| 2 | `btmuxctl roles set --sources $HP --headsets $SRC`, attendre le retour | `adapters[]` permuté | | |
| 3 | `bluetoothctl show` des deux | `$HP` (nouveau sources) : alias `btmux`, classe 0x6c0404 ; `$SRC` (nouveau headsets) : alias `btmux-hp`, classe `0x6c010c` ; l'alias suit le rôle, pas le dongle | | |
| 4 | `grep name /var/lib/btmux/adapters.yaml` | `name` = nom du rôle pour chaque entrée | | |
| 5 | *(mono-adaptateur, si testable)* un contrôleur portant les deux rôles | Alias `btmux` (nom du rôle `sources`) | | |
| 6 | Rétablir l'affectation initiale | Alias d'origine retrouvés | | |

**Verdict** : [ ] PASS  [ ] FAIL

## Critères de Validation

- [ ] Coupure du service ≈ 15–20 s, retour automatique avec la nouvelle affectation, une seule application de l'identité
- [ ] Après repli code 4, alias et classe portés par les nouveaux contrôleurs (ExecStartPre), PC vu en casque
- [ ] Repli code 4 observé quand `.path` est arrêtée
- [ ] Aucune écriture acceptée pendant `change_pending`
- [ ] Aucun contrôleur sans rôle ne reste appairable/découvrable
- [ ] Hotplug d'un contrôleur affecté : identité rétablie ≤ 10 s, `btmuxd` non redémarré (même PID), API jamais coupée
- [ ] Hotplug d'un contrôleur : l'autre contrôleur (fenêtre d'appairage ouverte) n'est pas refermé ; réémission bornée à 1 requête/contrôleur/minute
- [ ] L'alias suit le rôle après permutation (`btmux` sources, `btmux-hp` headsets)

## Notes QA

[observations, durées mesurées]
