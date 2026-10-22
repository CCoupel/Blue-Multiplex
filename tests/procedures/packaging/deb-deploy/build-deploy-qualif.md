# Procédure de Test — Packaging `.deb` et déploiement QUALIF (issue #2)

**Version** : 0.1.0.x · **Date** : ____ · **Testeur** : QA
**Cible** : Ubuntu Server 26.04 LTS arm64 ; `$U` = utilisateur de service (`ubuntu` par défaut) · **Joué** : au GATE 4 du LOT-1, après `/deploy qualif`. **Tag** : `critical` (chaîne BUILD → PUBLISH → DEPLOY).

## Prérequis

- [ ] Poste de dev : `uv`, `jq`, `dpkg-deb` disponibles ; branche `milestone/v0.1.0` à jour, CI verte
- [ ] Pi de qualif (Ubuntu Server 26.04 LTS arm64) provisionné (`tests/procedures/install/pi-qualif/` PASS), utilisateur de service `$U` (défaut `ubuntu`) avec linger ; `.claude/agents/environments/qualif.env` renseigné (`SSH_KEY_PATH`, `DEPLOY_HOST=<utilisateur>@btmux-qualif.local`, `BTMUX_USER` optionnel)
- [ ] Wheel candidate : `build/candidate_v0.1.0/btmux-<X.Y.Z.a>-py3-none-any.whl` (`<X.Y.Z.a>` = version courante `0.1.0.a`)

## Scénario 1 — Paquet `.deb` local

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `uv build` puis `scripts/build-deb.sh 0.1.0` | Sort en code 0 ; `dist/btmux_0.1.0_all.deb` créé (wheel `0.1.0.0` acceptée pour un paquet `0.1.0`) | | |
| 2 | `dpkg-deb --info dist/btmux_0.1.0_all.deb` | `Package: btmux`, `Version: 0.1.0`, `Architecture: all`, dépendances python3 (≥ 3.12) listées | | |
| 3 | `dpkg-deb --contents dist/btmux_0.1.0_all.deb` | Contient `/usr/share/btmux/btmux-*.whl` (la wheel ; le venv `/opt/btmux` n'est **pas** dans le .deb, il est créé par le postinst), `/lib/systemd/system/btmuxd.service`, `/etc/btmux/config.example.yaml`, `/usr/lib/btmux/set-user.sh` (exécutable) ; **aucun** `app-*.tar.gz` | | |
| 4 | Relancer `scripts/build-deb.sh 0.1.0` | Idempotent : même résultat, pas d'erreur | | |

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 2 — Unité systemd (décision D2)

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | Lire `systemd/btmuxd.service` | unité **générique** : `After=bluetooth.service user@1000.service dbus.service`, `Restart=on-failure`, `RestartPreventExitStatus=2`, `RestartSec=5`, `User=ubuntu`, `Environment=XDG_RUNTIME_DIR=/run/user/1000` (défauts Ubuntu ; l'utilisateur réel vient du drop-in, étape suivante) | | |
| 2 | Lire `ExecStart` | `/opt/btmux/bin/btmuxd --config /etc/btmux/config.yaml` | | |
| 2b | Lire `scripts/btmux-set-user.sh` | Génère `btmuxd.service.d/user.conf` (reset `After=`/`Wants=`/`Environment=` puis `User=`, `XDG_RUNTIME_DIR=/run/user/<uid>`, `user@<uid>.service`) ; refuse un nom invalide (code 2) | | |
| 3 | `systemd-analyze verify systemd/btmuxd.service` | Aucune erreur (avertissement sur binaire absent toléré en local) | | |

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 3 — `deploy.sh qualif` sur le Pi (idempotence incluse)

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `scripts/deploy.sh qualif build/qualif_v0.1.0/btmux-<X.Y.Z.a>-py3-none-any.whl` | Code 0 ; scp de la wheel, venv `/opt/btmux` créé/mis à jour, `daemon-reload`, `restart btmuxd` | | |
| 2 | `ssh $U@btmux-qualif.local 'ls -l /etc/systemd/system/btmuxd.service /etc/systemd/system/btmuxd.service.d/user.conf /etc/btmux/'` | Unité installée ; drop-in `user.conf` généré pour `$U` (`BTMUX_USER`, sinon utilisateur de `DEPLOY_HOST`, sinon `ubuntu`) ; `config.example.yaml` présent ; `config.yaml` créé **uniquement s'il était absent** | | |
| 3 | Modifier `/etc/btmux/config.yaml` (ajouter un commentaire), relancer l'étape 1 | Code 0 ; `config.yaml` **non écrasé** (commentaire conservé) | | |
| 4 | `ssh … 'systemctl is-active btmuxd'` | `active` | | |
| 5 | `ssh … '/opt/btmux/bin/btmuxd --version'` | `btmuxd 0.1.0.<a>` | | |
| 6 | `ssh … '/opt/btmux/bin/btmuxd --config /etc/btmux/config.yaml --check-config'` | `config OK: /etc/btmux/config.yaml`, code 0 | | |
| 7 | `ssh … 'ps -o user= -C python3,btmuxd'` (ou `systemctl show btmuxd -p User`) | Le service tourne sous `$U` (D2), `systemctl cat btmuxd` montre le drop-in ; `deploy.sh` n'a pas émis d'avertissement « linger absent » (sinon `sudo loginctl enable-linger $U`) | | |
| 8 | `ssh … 'journalctl -u btmuxd -n 20 --no-pager'` | Ligne `btmuxd <version> started — no daemon logic yet (v0.3.0)` ; pas de traceback ; pas de crash-loop : `systemctl show btmuxd -p NRestarts` = `0` et l'unité reste `active` en continu (le daemon reste vivant) | | |
| 9 | `ssh … 'sudo systemctl stop btmuxd; systemctl is-active btmuxd; journalctl -u btmuxd -n 3 --no-pager'` | `inactive` ; journal `btmuxd <version> stopped` ; arrêt propre (SIGTERM → code 0, pas de `Failed`, pas de redémarrage automatique) ; puis `sudo systemctl start btmuxd` | | |

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 4 — Smoke (`commands.smoke`, décision D5)

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | Exécuter `commands.smoke` de `.claude/project-config.json` | Enchaîne via SSH `is-active` + `--version` + `--check-config` ; code 0 | | |
| 2 | Arrêter le service puis relancer le smoke (`systemctl stop btmuxd`) | Smoke **échoue** (code ≠ 0) : il détecte bien un service inactif — puis `systemctl start btmuxd` | | |

**Verdict** : [ ] PASS [ ] FAIL

## Scénario 5 — Chaîne BUILD → PUBLISH → DEPLOY (CI de release, optionnel au GATE 4)

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `/publish qualif` | Wheel copiée vers `build/qualif_v0.1.0/` sans rebuild (même sha256 que le candidat) | | |
| 2 | `sha256sum build/candidate_v0.1.0/*.whl build/qualif_v0.1.0/*.whl` | Empreintes identiques | | |

**Verdict** : [ ] PASS [ ] FAIL

## Critères de validation

- [ ] Tous les scénarios 1 à 4 PASS (critères d'acceptation de l'issue #2)
- [ ] Aucune étape ne modifie un fichier hors du projet côté poste

## Notes QA

