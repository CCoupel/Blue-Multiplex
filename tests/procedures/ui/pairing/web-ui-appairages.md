# Procédure QA — Web UI « Appairages » (#16, API #21, appairages #20)

**Version** : 0.2.0.x · **Date** : ____ · **Testeur** : QA · **Tags** : `critical` (jeton, refus hors fenêtre), `hardware` (mode B)
**Référence** : maquette `docs/mockup/v0.2.0/ui/webui_pairing__appairages.html` (validée au GATE 2), contraintes `docs/mockup/DECISIONS.md`,
contrats `contracts/http-endpoints.md` et `contracts/models.md`. Chaque écart avec la maquette est noté (pas de variante non validée).

## Deux modes

| Mode | Backend | Quand | Accès |
|------|---------|-------|-------|
| **A — mock** | `python tests/fixtures/api-mock/server.py --port 8099 --scenario <nom> --token mock-token --static-dir src/btmux/api/static` | Poste de dev / QA sans matériel (scénarios `default`, `empty`, `window-open`, `stale-bond`, `bluez-error`, `bluez-down`) ; `--time-scale 10` pour accélérer ; pilotage `/__mock__/*` (README du mock) | `http://127.0.0.1:8099/` |
| **B — Pi réel** | `btmuxd` v0.2.0 sur pi-qualif (BlueZ réel, UB500 ou BT interne **sans audio**, ≤ 1 lien à la fois) | GATE 4 LOT-2 avec l'utilisateur (~30 min) | `http://<IP-du-Pi>:8088/` ; jeton = `/etc/btmux/token` |

Colonnes « A » / « B » : ✔ = jouable dans ce mode, — = sans objet. Cocher « OK » par mode joué.

## Prérequis

- [ ] Navigateur de bureau (Chrome ou Firefox récents) **et** un téléphone (ou émulation mobile 375 px)
- [ ] Mode B : au démarrage de `btmuxd` avec `api.listen` hors loopback, l'avertissement **`api_listening_cleartext`** (« HTTP en clair sur le LAN, HTTPS prévu en #22 ») est **attendu** : `journalctl -u btmuxd | grep api_listening_cleartext` — à noter, pas un défaut (LAN personnel)
- [ ] Mode A : mock lancé ; Mode B : `systemctl is-active btmuxd`, `curl -s http://<IP-du-Pi>:8088/api/health` → `{"version": …}`
- [ ] Preuves (captures, vidéo courte) dans `_work/tmp/ui-pairing/` — **masquer** MAC et noms personnels avant tout commit (dépôt public)
- [ ] Mode B : `watch_hci.sh` + `link_guard.py` actifs, aucun audio lancé

## Scénarios

### S1 — Jeton et authentification (`critical`)

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 1.1 | Ouvrir `/` sans jeton enregistré | La page se charge (publique), l'en-tête affiche le champ « Jeton » (masqué) et **aucune donnée** d'appareil | ✔ | ✔ | | |
| 1.2 | Saisir un jeton invalide puis « Enregistrer » | Message d'erreur clair (401), aucune liste affichée, le jeton n'apparaît pas en clair dans l'URL ni dans l'erreur | ✔ | ✔ | | |
| 1.3 | Saisir le bon jeton → « Enregistrer » | Les panneaux **Sources** et **Casques** se remplissent ; statut « API <version> · événements : en direct » | ✔ | ✔ | | |
| 1.4 | Recharger la page | Le jeton est retenu (ou redemandé selon le choix de #16, noté) ; jamais de jeton dans l'URL | ✔ | ✔ | | |
| 1.5 | DevTools > Réseau : toutes les requêtes `/api/*` | En-tête `Authorization: Bearer …` ; `Cache-Control: no-store` sur les réponses d'API | ✔ | ✔ | | |

### S2 — Ouvrir et fermer la fenêtre d'appairage (Sources)

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 2.1 | Panneau Sources, fenêtre fermée : choisir la durée (30/60/120/300 s) et ouvrir | Bandeau « Fenêtre d'appairage **ouverte** » avec compte à rebours `mm:ss` qui décroît ; adaptateur `discoverable`/`pairable` | ✔ | ✔ | | |
| 2.2 | Observer le journal « Événements » | Ligne `pairing … fenêtre ouverte (N s)` en direct, sans recharger | ✔ | ✔ | | |
| 2.3 | Cliquer « Fermer » | Bandeau « fermée » immédiat, événement `pairing` ; l'adaptateur n'est plus découvrable | ✔ | ✔ | | |
| 2.4 | Rouvrir et attendre l'expiration (mock : `--time-scale 30`) | La fenêtre se ferme seule à 00:00 ; l'UI se met à jour sans action | ✔ | ✔ | | |
| 2.5 | Une fenêtre déjà ouverte (autre onglet / `window-open`) : tenter d'en ouvrir une 2ᵉ | Erreur 409 explicite (« une fenêtre est déjà ouverte »), état inchangé | ✔ | ✔ | | |

### S3 — Appairer une source (entrant : PC, téléphone) — `critical` pour le refus

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 3.1 | Fenêtre Sources **ouverte** ; appairer `btmux` depuis le téléphone (B) / `curl -X POST /__mock__/incoming -d '{"mac":"BB:00:00:00:00:01","name":"PC visiteur"}'` (A) | L'appareil apparaît dans Sources, état « appairé » + « confiance », ligne `device … appairé` dans le journal | ✔ | ✔ | | |
| 3.2 | Appareil hors config | Tag « hors config » ; alias vide ; le nom BlueZ est affiché | ✔ | ✔ | | |
| 3.3 | Fenêtre **fermée** : retenter l'appairage depuis le téléphone / `POST /__mock__/incoming` | **Refusé** : aucun nouvel appareil, aucun changement d'état (A : réponse 409 du mock) | ✔ | ✔ | | |
| 3.4 | « Faire confiance » / « Retirer la confiance » sur un appareil | Le tag « confiance » bascule, événement `device` reçu | ✔ | ✔ | | |

### S4 — Appairer un casque (initié par le Pi)

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 4.1 | Panneau Casques : « Rechercher des casques » (durée 60 s) | Bandeau « ouverte » + compte à rebours ; section « Casques découverts » se remplit **au fil de l'eau** (mock : Bose QC45 après ~1 s, JBL après ~2,5 s ; B : casque en mode appairage) | ✔ | ✔ | | |
| 4.2 | Lignes découvertes | Nom, MAC, signal en dBm, bouton « Appairer » | ✔ | ✔ | | |
| 4.3 | « Appairer » un casque | Après quelques secondes : casque ajouté à la liste Casques, « connecté », « appairé », « confiance » ; il quitte « découverts » | ✔ | ✔ | | |
| 4.4 | Fermer la fenêtre | La liste « découverts » se vide ; message « Aucune recherche en cours » | ✔ | ✔ | | |
| 4.5 | Tenter « Appairer » après fermeture (onglet périmé) | Erreur 409 lisible (fenêtre fermée) | ✔ | — | | |

### S5 — Connecter, déconnecter, oublier

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 5.1 | « Connecter » sur un appareil déconnecté | Tag « connecté » après la fin de l'action, événement `device` | ✔ | ✔ | | |
| 5.2 | « Déconnecter » | Tag « déconnecté » | ✔ | ✔ | | |
| 5.3 | « Oublier » | **Dialogue de confirmation** : « Oublier « <nom> » ? … Il faudra aussi l'oublier côté PC… » avec Annuler / Oublier | ✔ | ✔ | | |
| 5.4 | « Annuler » | Aucun changement | ✔ | ✔ | | |
| 5.5 | « Oublier » confirmé | L'appareil disparaît (hors config) ou passe « non appairé » (dans la config) ; événement reçu | ✔ | ✔ | | |
| 5.6 | Mode B : tenter de connecter un 2ᵉ appareil alors que le plafond de liens est atteint | Refus ou avertissement explicite ; **ne jamais dépasser le plafond** (garde-fou `link_guard`) | — | ✔ | | |

### S6 — Erreurs (toasts) et indisponibilités

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 6.1 | Mock `stale-bond` : casque « JBL Tune 760 » → « Appairer » | Toast `role="alert"` « Appairage refusé … (bond périmé). Oubliez l'appareil ici **et** sur l'appareil… » ; erreur persiste jusqu'à fermeture | ✔ | — | | |
| 6.2 | Après `Oublier` puis nouvel essai | L'appairage aboutit (mock : retirer `stale_bond_macs` via `/__mock__/fail`) | ✔ | ✔ | | |
| 6.3 | Mock `bluez-error` : « Appairer » le Bose | Toast 502 avec le message D-Bus (`org.bluez.Error…`) | ✔ | — | | |
| 6.4 | Mock `bluez-down` | Bandeau/toast « BlueZ indisponible » (503), pas de crash, `/api/health` reste joignable | ✔ | — | | |
| 6.5 | Couper `btmuxd` (B : `systemctl stop btmuxd`) | Statut « événements : hors ligne / reconnexion », message clair, reprise automatique au redémarrage (retry 3 s) | ✔ (arrêter le mock) | ✔ | | |

### S7 — Événements en direct (SSE) et repli polling

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 7.1 | Deux onglets ouverts ; ouvrir une fenêtre dans l'un | L'autre se met à jour **sans recharger** | ✔ | ✔ | | |
| 7.2 | Mock : `POST /__mock__/close-streams` | L'UI affiche « hors ligne », tente de se reconnecter ; si SSE indisponible, **repli polling** (données toujours à jour, statut « polling ») | ✔ | — | | |
| 7.3 | Le journal « Événements » | Horodaté, une ligne par événement (`pairing`, `device`, `discovered`), pas de doublons, borné (n'enfle pas indéfiniment) | ✔ | ✔ | | |
| 7.4 | Mock : `POST /__mock__/event {"event":"pairing","data":null}` | La fenêtre est affichée comme fermée | ✔ | — | | |

### S8 — Responsive, thème, accessibilité

| # | Action | Résultat attendu | A | B | OK A | OK B |
|---|--------|------------------|---|---|------|------|
| 8.1 | Largeur ≥ 800 px | Deux colonnes (Sources / Casques), journal pleine largeur | ✔ | — | | |
| 8.2 | Largeur ≤ 600 px (téléphone) | Une colonne ; la colonne MAC du tableau est masquée ; aucun défilement horizontal de la page ; boutons utilisables au doigt | ✔ | ✔ | | |
| 8.3 | Thème système sombre / clair | Les deux thèmes lisibles (contraste), pas de fond blanc résiduel | ✔ | — | | |
| 8.4 | Clavier : Tab / Entrée / Échap | Tous les boutons atteignables ; le dialogue « Oublier » se ferme par Échap (= Annuler), focus piégé dans le dialogue | ✔ | — | | |
| 8.5 | Lecteur d'écran / DevTools a11y | Panneaux étiquetés (`aria-labelledby`), toasts en `role="alert"`, champ jeton avec `aria-label` | ✔ | — | | |
| 8.6 | Console navigateur | Aucune erreur JS ; aucune requête hors origine ; pas de CDN externe (LAN seul) | ✔ | ✔ | | |

### S9 — Cohérence avec la maquette et sécurité de la page

| # | Contrôle | OK A | OK B |
|---|----------|------|------|
| 9.1 | Écrans comparés à `webui_pairing__appairages.html` : mêmes zones (en-tête+jeton, Sources, Casques, découverts, toast, journal, dialogue) ; écarts listés | | |
| 9.2 | Contraintes de `docs/mockup/DECISIONS.md` respectées (aucune ajoutée sans validation) | | |
| 9.3 | Les valeurs dynamiques (noms d'appareils) sont échappées : un nom `<img src=x onerror=alert(1)>` (via `/__mock__/incoming`) s'affiche en texte, sans exécution | | |
| 9.4 | `GET /` et `/static/*` publics ; `/api/*` sans jeton → 401 (testé en S1) ; en-têtes de sécurité raisonnables (`X-Content-Type-Options`) | | |

## Critères de validation

- [ ] Mode A : S1–S9 OK (aucun écart bloquant avec la maquette)
- [ ] Mode B (GATE 4) : S1, S2, S3, S4, S5, S6.5, S7.1 OK sur le Pi, plafond de liens respecté, aucun audio
- [ ] `critical` : jeton requis (S1) et refus hors fenêtre (S3.3) OK
- [ ] Preuves masquées avant tout commit ; verdict QA : [ ] VALIDATED [ ] NOT VALIDATED — motif : ______

## Notes QA

