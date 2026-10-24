# Procédure de Test — Redémarrage piloté après changement de rôles (#23, D3)

**Version** : 0.2.0.x · **Date** : ____ · **Testeur** : QA
**Cible** : Pi de qualif (Ubuntu 26.04 arm64), `btmuxd` déployé avec les unités `btmux-adapters.path` et `btmux-adapters-reload.service` · **Tag** : `hardware`
**Équivalent mock** : `tests/integration/api/controllers/` (coupure simulée) ; ici on prouve le comportement réel (systemd, codes de sortie). Pas de systemd en CI.

## Prérequis

- [ ] `/deploy qualif` joué ; `systemctl is-enabled btmux-adapters.path` → `enabled`, `systemctl is-active btmux-adapters.path` → `active`
- [ ] `btmuxd` actif, `btmuxctl controllers` liste ≥ 2 contrôleurs (dongles UB500) ; noter `SRC` (rôle sources), `HP` (rôle headsets)
- [ ] Aucun appareil connecté (sauf scénario 3), aucune fenêtre d'appairage ouverte
- [ ] Un terminal avec `journalctl -u btmuxd -u btmux-adapters-reload -f` ouvert pendant toute la procédure
- [ ] `/var/lib/btmux/` existe, propriétaire = utilisateur de service, mode 0750

## Scénarios

### Scénario 1 — Permutation des rôles : écriture, `.path`, redémarrage, retour

**Validation** : AUTO — **Issues** : #23

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `btmuxctl roles set --sources $HP --headsets $SRC` ; chronométrer | Code 0 ; `roles.pending=true`, `restart_expected=true` | | |
| 2 | `stat -c '%a' /var/lib/btmux/adapters.yaml` ; `cat` du fichier | Mode `640` ; sources = `$HP`, headsets = `$SRC`, schéma identique à `adapters` de config.yaml | | |
| 3 | Journal | `btmux-adapters.path` déclenche `btmux-adapters-reload.service` ; arrêt propre de `btmuxd` (SIGTERM) ; **pas** de `restart_fallback` | | |
| 4 | Boucler `btmuxctl state` toutes les secondes | API injoignable pendant la coupure ≈ 10–15 s, puis réponse | | |
| 5 | `btmuxctl controllers` après retour | `roles.sources=$HP`, `roles.headsets=$SRC`, `source=state`, `pending=false`, `restart_expected=false` | | |
| 6 | `bluetoothctl list` / `btmuxctl state` | Classe 0x006C0404 et alias portés par le nouveau contrôleur sources ; `adapters[]` reflète la permutation | | |
| 7 | Rétablir : `btmuxctl roles set --sources $SRC --headsets $HP` et attendre le retour | Situation initiale rétablie | | |

**Verdict** : [ ] PASS  [ ] FAIL

### Scénario 2 — Écritures refusées pendant `change_pending`

**Validation** : AUTO — **Issues** : #23

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | Lancer le scénario 1 étape 1, puis immédiatement `btmuxctl pairing open sources 60` | Code 1, erreur `change_pending` (409) | | |
| 2 | Immédiatement `btmuxctl roles set …` (autre affectation) | Code 1, `change_pending` | | |
| 3 | Immédiatement `btmuxctl state` / `btmuxctl controllers` | Lectures autorisées (code 0) | | |
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

### Scénario 4 — Repli code 4 si `btmux-adapters.path` est inactive

**Validation** : AUTO — **Issues** : #23

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | `sudo systemctl mask --now btmux-adapters.path` | Unité masquée | | |
| 2 | `btmuxctl roles set --sources $HP --headsets $SRC` | Code 0 (202) ; `pending=true` | | |
| 3 | Attendre ≈ 30 s sans rien faire | Journal `restart_fallback` ; `btmuxd` sort en **code 4** (`systemctl show btmuxd -p ExecMainStatus`) | | |
| 4 | Attendre | systemd relance `btmuxd` (`RestartForceExitStatus=4`) ; le service revient avec la nouvelle affectation | | |
| 5 | Nettoyage : `sudo systemctl unmask btmux-adapters.path && sudo systemctl start btmux-adapters.path`, rétablir l'affectation initiale | `is-active` = `active` | | |

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

### Scénario 6 — Hotplug d'un contrôleur

**Validation** : AUTO — **Issues** : #23

| Étape | Action | Résultat attendu | Obtenu | OK ? |
|-------|--------|------------------|--------|------|
| 1 | Ouvrir `GET /api/events` (curl avec jeton) | Premier événement : `state` complet (6 clés) | | |
| 2 | Débrancher le dongle `$HP` | Événement `controllers` : `present=false` ; `PUT roles` vers ce MAC → 400 `unknown_controller` | | |
| 3 | Rebrancher | Événement `controllers` : `present=true` ; contrôleur fermé s'il n'a pas de rôle | | |

**Verdict** : [ ] PASS  [ ] FAIL

## Critères de Validation

- [ ] Coupure du service ≈ 10–15 s, retour automatique avec la nouvelle affectation
- [ ] Repli code 4 observé quand `.path` est masquée
- [ ] Aucune écriture acceptée pendant `change_pending`
- [ ] Aucun contrôleur sans rôle ne reste appairable/découvrable

## Notes QA

[observations, durées mesurées]
