# Procédure QA — Web UI « Contrôleurs » (#23, section ajoutée à la Web UI #16)

**Version** : 0.2.0.x · **Date** : ____ · **Testeur** : QA · **Tags** : `critical` (confirmation de déconnexion, bandeau de redémarrage), `hardware` (mode B)
**Référence** : maquette `docs/mockup/v0.2.0/ui/webui_pairing__controleurs.html`, contrats `contracts/http-endpoints.md`
(`GET /api/controllers`, `PUT /api/controllers/roles`) et `contracts/models.md` (`Controller`, `Roles`, `RoleChange`, événements `controllers`/`roles`).
Chaque écart avec la maquette est noté. **Écart connu** : le bandeau de redémarrage est placé en tête de `<main>` (la maquette le place dans la section).

## Modes

| Mode | Backend | Accès |
|------|---------|-------|
| **A — mock** | `python tests/fixtures/api-mock/server.py --port 8099 --scenario <nom> --token mock-token --static-dir src/btmux/api/static` ; `--time-scale 10` pour accélérer ; pilotage `/__mock__/*` (hotplug : `POST /__mock__/controllers`) | `http://127.0.0.1:8099/` (Chrome de WSL ou navigateur du poste) |
| **B — Pi réel** | `btmuxd` v0.2.0 sur pi-qualif, 2 UB500 + BT interne UART | `http://<IP-du-Pi>:8088/`, jeton `/etc/btmux/token` |

Scénarios mock : `default`, `swap-ready`, `unassigned`, `uart-only`, `restart-pending`. Preuves dans `_work/tmp/ui-controllers/`
(masquer MAC et noms personnels avant tout commit).

## S1 — Affichage et sélection (`default`)

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 1.1 | Ouvrir la page avec le jeton | Section « Contrôleurs Bluetooth » **au-dessus** de Sources/Casques : 3 lignes (nom/hci, adresse, bus `USB 2357:0604`/`UART`, état, sélecteur de rôle) ; tag « affectation : config » | ✔ | ✔ | | |
| 1.2 | Lire les états | `powered`, « fermé » (ni appairable ni visible), nombre d'appareils connectés (« 1 appareil connecté ») | ✔ | ✔ | | |
| 1.3 | Changer le rôle de l'UART en « Sources » | Les sélecteurs reflètent le choix ; l'ancien titulaire passe à « Aucun » ; bandeau « Modification en attente : … → … » avec Annuler / Appliquer ; rien n'est envoyé | ✔ | ✔ | | |
| 1.4 | « Annuler » | Retour à l'affectation courante, bandeau de modification disparu | ✔ | ✔ | | |

## S2 — Permutation sans appareil connecté (`swap-ready`) — `critical`

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 2.1 | Mettre Sources → contrôleur HP, puis Casques → contrôleur SRC (permutation en deux choix), « Appliquer » | `PUT /api/controllers/roles` unique (les deux rôles), réponse 202 ; **pas** de boîte de confirmation (aucun appareil connecté) | ✔ | ✔ | | |
| 2.2 | Observer l'écran | Bandeau en tête de page « Application de l'affectation… » avec compte à rebours (~15 s) ; boutons et sélecteurs désactivés ; ligne `roles` dans le journal | ✔ | ✔ | | |
| 2.3 | Attendre la fin du redémarrage | La page se reconnecte seule, bandeau retiré, `state` complet resynchronisé, tag « affectation : état (API) », rôles permutés, panneaux Sources/Casques cohérents | ✔ | ✔ | | |

## S3 — Confirmation de déconnexion (`default`) — `critical`

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 3.1 | Avec des appareils connectés, permuter les rôles puis « Appliquer » | Le serveur répond 409 `devices_connected` ; une boîte de dialogue liste les appareils concernés (alias/nom) et propose « Annuler » / « Déconnecter et appliquer » ; aucun redémarrage | ✔ | ✔ | | |
| 3.2 | « Annuler » | Dialogue fermé, aucune modification appliquée ; le brouillon reste affiché | ✔ | ✔ | | |
| 3.3 | Recommencer puis « Déconnecter et appliquer » | Second `PUT` avec `confirm:true` → 202 ; appareils déconnectés (journal `device`) puis bandeau de redémarrage comme en 2.2 | ✔ | ✔ | | |
| 3.4 | Fenêtre d'appairage ouverte, tenter d'appliquer | Erreur 409 `pairing_open` affichée dans la page (« Fermez d'abord la fenêtre… »), jamais d'`alert()` | ✔ | ✔ | | |

## S4 — Bandeau de redémarrage et coupure (`restart-pending`)

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 4.1 | Ouvrir la page (`roles.pending:true`) | Bandeau de redémarrage visible d'emblée ; toutes les actions désactivées ; erreur réseau pendant la coupure = « redémarrage du service… » (pas d'erreur rouge) | ✔ | — | | |
| 4.2 | Pendant la coupure (≈ 10–15 s), recharger la page | Pas de crash ; reconnexion automatique à la fin | ✔ | ✔ | | |
| 4.3 | Après reconnexion | Premier événement `state` (compteur `id` repart de 1) : vue réinitialisée, `pending:false`, bandeau retiré | ✔ | ✔ | | |
| 4.4 | Tenter une écriture (autre onglet) entre acceptation et arrêt | 409 `change_pending` affiché clairement | ✔ | ✔ | | |

## S5 — Rôle non affecté (`unassigned`)

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 5.1 | Ouvrir la page | Tous les sélecteurs sur « Aucun » ; panneaux Sources et Casques : tag « rôle non affecté » et message invitant à choisir un contrôleur ; **aucun** bouton d'appairage | ✔ | ✔ | | |
| 5.2 | Affecter un contrôleur à Sources puis appliquer | Redémarrage (S2.2–2.3), le panneau Sources redevient actif, Casques reste « non affecté » | ✔ | ✔ | | |
| 5.3 | Tenter d'appairer un rôle non affecté (API) | 409 `role_unassigned` affiché comme erreur lisible | ✔ | ✔ | | |

## S6 — UART affectable (`uart-only`) et hotplug

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 6.1 | Ouvrir la page : un seul contrôleur UART, rôle Sources | Ligne unique « UART », sélecteur actif ; Casques « non affecté » ; l'UART est affectable sans option « forcer » | ✔ | ✔ | | |
| 6.2 | `POST /__mock__/controllers` (ajout d'un USB) / branchement d'un dongle | La ligne apparaît sans recharger (événement `controllers`), journal `controllers N contrôleur(s)` | ✔ | ✔ | | |
| 6.3 | Retrait du dongle affecté | Ligne « absent » (`present:false`), sélecteur désactivé | ✔ | ✔ | | |

## S7 — Transverse

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 7.1 | Écran 375 px | Tableau défilable horizontalement, aucun débordement de page, sélecteurs utilisables | ✔ | ✔ | | |
| 7.2 | Clavier seul | Sélecteurs, Appliquer/Annuler et dialogue accessibles au clavier ; focus initial sur « Annuler » dans le dialogue | ✔ | ✔ | | |
| 7.3 | Console navigateur | Aucune erreur JS, aucune requête hors origine, jeton jamais dans l'URL | ✔ | ✔ | | |
