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
| 4 | Journal ≤ 10 s après `bind` ; `cat /var/lib/btmux/identity.request` | `identity_requested hci=… mac=…` (une fois) ; fichier : une ligne par MAC en attente `<ISO UTC>\t<hciN>\t<MAC en majuscules>` (MAC de `$HP`), mode 640, régulier (la MAC, 3e champ, fait foi) ; l'unité exécute `btmux-adapters.sh … --wait 5 --requests /var/lib/btmux/identity.request` (visible dans `systemctl status`) et le journal de la passe indique « contrôleur <MAC de $HP> seul » (les autres contrôleurs ne sont pas touchés) ; `btmux-adapters-identity.service` : `systemctl show -p Result btmux-adapters-identity.service` = `success` | | |
| 5 | `bluetoothctl show $HP` | Classe `0x6c0404` (sources) ou `0x6c010c` (headsets) selon le rôle ; alias du rôle (`btmux` / `btmux-hp`) ; `Pairable: no`, `Discoverable: no` | | |
| 6 | `systemctl show btmuxd -p MainPID` + sondage de l'étape 1 | **Même PID** (aucun redémarrage de `btmuxd`) ; l'API n'a jamais été coupée (aucun échec du sondage) | | |
| 7 | Rejouer étapes 2–3 avec un contrôleur **sans rôle** (ou après `roles set … none`) | Aucune ligne `identity_requested` ; contrôleur fermé (`Pairable/Discoverable no`) | | |
| 8 | Après étape 3, aucune nouvelle ligne `identity_requested` (pas de boucle alias/classe → requête) | Une seule requête par réapparition | | |
| 9 | **Autre contrôleur épargné** : `bluetoothctl show $SRC` + `btmuxctl state` juste après la passe d'identité de `$HP` | `$SRC` : toujours `Pairable: yes`, `Discoverable: yes` (BlueZ), cohérent avec l'API (`pairing.open=true`, `adapter=sources`, `controllers[$SRC].pairable/discoverable=true`) ; la fenêtre n'a pas été refermée par la passe (le journal ne montre aucune fermeture de `$SRC`) | | |
| 10 | **Double apparition sans perte** : `unbind` des **deux** dongles (`$SRC` et `$HP`, tous deux affectés), puis `bind` du premier, **≈ 3 s plus tard** `bind` du second (cas réel Pi 3 B : la 2e requête arrive pendant la passe de la 1re) ; `cat /var/lib/btmux/identity.request` après chaque `bind` ; noter l'heure de chaque `bind` et de chaque `identity_requested` | Les deux MAC figurent dans le fichier (jusqu'à acquittement)  (une par MAC, réécriture atomique de l'ensemble, débounce ≤ 1 s) ; deux `identity_requested` ; **la 2e MAC est traitée dans la foulée de la 1re (relecture du fichier en fin de passe, 3 relectures au plus par exécution, MAC déjà traitées ignorées), ≤ ~10 s après son écriture** — pas de rattrapage à +60 s : alias + classe de la 2e posés avant l'échéance de vérification ; le service lit **toutes** les lignes (`--requests`) et traite chaque MAC (dédoublonnée) en **une seule passe** : journal « contrôleurs <MAC1>, <MAC2> seuls » ; ≤ 10 s plus tard les deux contrôleurs ont alias + classe de leur rôle ; unité `Result=success` | | |
| 11 | **Vérification différée à +60 s** : relever la classe des deux contrôleurs juste après l'étape 10, puis attendre 60 s | Classe correcte observée ⇒ requête acquittée ; **`identity.request` vidé** : dès l'acquittement (classe correcte observée, généralement avant +60 s) le daemon réécrit le fichier sans la MAC acquittée ; `wc -c /var/lib/btmux/identity.request` = 0 une fois toutes les MAC acquittées ; la réécriture déclenche `.path` mais le script sort en **code 0 sans passe** (journal : rien à faire, `Result=success`, pas de boucle) ; un abandon (`identity_giving_up`, étape 11c) retire aussi la MAC du fichier ; **aucune** réémission à +60 s | | |
| 11b | **Échec de passe → nouvel essai à +60 s** : `sudo systemctl stop btmux-adapters-identity.path` ; `unbind`/`bind` de `$HP` ; attendre 70 s ; `sudo systemctl start btmux-adapters-identity.path` | La classe n'est pas rétablie (pas de passe) ; à +60 s le daemon constate `Class` ≠ rôle et **réémet** une requête (2e `identity_requested`) ; une fois `.path` redémarrée la passe rétablit la classe et la MAC est acquittée | | |
| 11c | **Abandon après 3 tentatives** : `.path` arrêtée, `unbind`/`bind` de `$HP`, attendre ≈ 3 min 10 s | 3 `identity_requested` au plus (apparition + 2 réémissions à +60 s), puis ERROR `identity_giving_up hci= mac= attempts=3` ; **plus aucune** requête ensuite, même si la classe reste fausse (jusqu'à la prochaine apparition) ; `btmuxd` toujours actif, API répond | | |
| 11d | **Rien pendant `roles.pending`** : avec `.path` arrêtée, `unbind`/`bind` de `$HP` puis immédiatement `btmuxctl roles set …` (permutation) | Aucune ligne `identity_requested` ni réémission pendant `pending` (requête et vérification suspendues) ; l'identité des nouveaux rôles vient de l'`ExecStartPre` au redémarrage | | |
| 11e | **Service root durci** : `.path` redémarrée ; `sudo cp /var/lib/btmux/identity.request /tmp/ir.bak`, remplacer `identity.request` par un lien symbolique vers un fichier quelconque ; déclencher (`touch`) ; puis écrire une ligne invalide + une ligne valide | Lien symbolique : avertissement, rien traité, code 0 (`Result=success`) ; ligne invalide : « N ligne(s) invalide(s) ignorée(s) (MAC invalide) » **sans reproduire son contenu**, la ligne valide est traitée ; l'unité n'échoue jamais (`systemctl show -p Result,NRestarts` ; `SuccessExitStatus=2` tolère le code 2 d'une configuration invalide) ; restaurer ensuite un fichier régulier 0640 `BTMUX_USER` | | |
| 12 | Rétablir : `sudo systemctl start btmux-adapters-identity.path` et `btmux-adapters-identity.service`, `unbind`/`bind` si une classe reste fausse ; fermer la fenêtre `btmuxctl pairing close` | Classe du rôle sur `$HP`, aucune fenêtre ouverte | | |

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
- [ ] Deux contrôleurs réapparus à ≈ 3 s d'écart : le second est traité ≤ ~10 s après son écriture (sans attendre +60 s) ; `identity.request` vide après acquittement
- [ ] Hotplug d'un contrôleur : l'autre contrôleur (fenêtre d'appairage ouverte) n'est pas refermé ; double apparition sans perte de requête, vérification à +60 s, 3 tentatives max puis `identity_giving_up`, rien pendant `roles.pending`, service root jamais en échec
- [ ] L'alias suit le rôle après permutation (`btmux` sources, `btmux-hp` headsets)

## Notes QA

[observations, durées mesurées]
