# Changelog des contrats

> Changements de contrats (API, schemas) : `BREAKING` | `CHANGED` | `ADDED`. Lu par le CDP au GATE 2.

## [20261022] — milestone v0.1.0 (phase 0, mono-adaptateur)

- **[NEW]** `contracts/config-schema.md` — schéma `/etc/btmux/config.yaml` (liste `adapters` à `roles`, règles V1–V10), interface CLI `btmuxd --version / --check-config` et API Python `btmux.config` (#4). Aucun contrat HTTP/WebSocket en v0.1.0.
- **[CHANGED]** `btmuxd --config <path>` (sans `--check-config`) : ne sort plus en 0 immédiatement ; après validation il reste vivant (asyncio) jusqu'à SIGTERM/SIGINT (code 0), pour que l'unité systemd soit réellement active. Non BREAKING : aucun consommateur (#2 #4).

## [20261023] — révision bi-adaptateur (T3.2b à 2 dongles) — validé au GATE 2 v0.2.0 (2026-10-23 17:12)

- **[CHANGED]** `contracts/config-schema.md` — V4 levée : 1 ou 2 adaptateurs acceptés (max 2), message `config: at most 2 adapters are supported` ; forme bi-adaptateur documentée (#14). Rétrocompatible : toute config mono valide reste valide. Le test `critical` « multi-adaptateur refusé » (V4) devient « 3 adaptateurs refusés ».


## [20261023-b] — v0.2.0 LOT-2 « appairages + Web UI » (#20 #21 #16) — validé au GATE 2 v0.2.0 (2026-10-23 17:12 : aiohttp, SSE + repli polling)

- **[NEW]** `contracts/http-endpoints.md` — API HTTP `btmuxd` périmètre appairages (`/api/state`, `/api/pairing`, `/api/devices/{mac}/*`, `/api/events` SSE), jeton Bearer, aiohttp.
- **[NEW]** `contracts/models.md` — modèles `State`, `Adapter`, `Device`, `Discovered`, `PairingWindow`, événements SSE.
- **[CHANGED]** `contracts/config-schema.md` — `btmuxd --config` ne sort plus immédiatement : démarre le daemon (BlueZ + API) ; nouvelle clé optionnelle `pairing: { default_duration: 60, accept_incoming: true }` ; `api.token_file` généré à l'installation (0600). Rétrocompatible (défauts).

## [20261023-c] — v0.2.0 LOT-1 (#14)

- **[CHANGED]** `contracts/config-schema.md` — règle V12 : `adapters[].mac` uniques, `adapters[].name` sans caractère de contrôle (248 octets UTF-8 conservés). Mineur, non BREAKING : toute configuration valide existante le reste.

## [20261024] — v0.2.0 LOT-2 (#16 #21)

- **[CHANGED]** `contracts/http-endpoints.md` — `/api/events` : client en `fetch` streaming avec Bearer (pas `EventSource`), `Last-Event-ID` géré côté client et serveur (tampon 100, sinon événement `state` complet). Mineur, non BREAKING.

## [20261024-b] — v0.2.0 LOT-2 (#20 #21 #16) — arbitrage SSE

- **[CHANGED]** `contracts/models.md` — `PairingWindow` porte `open` ; fermée = objet explicite `{open:false, reason}` (jamais `null`) ; `State.pairing` toujours un objet. Nouvel événement SSE `device.removed` (`DeviceRemoved {mac, adapter}`) après `forget`, suivi d'un `device` placeholder si l'appareil est dans la config ; événement `state` défini. Mineur, non BREAKING (API non encore implémentée).
- **[CHANGED]** `contracts/http-endpoints.md` — `DELETE /api/pairing` idempotent (204), événements émis par `DELETE /api/pairing` et `forget` précisés.

## [20261024-c] — v0.2.0 LOT-2 avenant #23 (sélection des contrôleurs) — validé au GATE 2 avenant, amendé par [20261024-d]

- **[NEW]** `contracts/http-endpoints.md` — `GET /api/controllers`, `PUT /api/controllers/roles` (affectation atomique, 400/409 `pairing_open`/`devices_connected`/`change_pending`), fermeture systématique des contrôleurs sans rôle ; 409 `role_unassigned` sur l'appairage d'un rôle non affecté.
- **[NEW]** `contracts/models.md` — `Controller`, `Roles`, `RoleChange` ; `State.controllers`, `State.roles` ; événements SSE `controllers`, `roles`.
- **[CHANGED]** `contracts/config-schema.md` — V2 (`adapters` peut être vide), V3 (« exactement un » → « au plus un » par rôle) ; fichier d'état `/var/lib/btmux/adapters.yaml` (même schéma, précédence sur `config.yaml`) ; sortie 3 « adaptateur introuvable » remplacée par l'état `role_unassigned`. Rétrocompatible pour toute configuration valide existante ; **non BREAKING** (comportement de démarrage plus permissif, à noter dans `docs/install-pi.md`).

## [20261024-d] — avenant #23 validé au GATE 2 (2026-10-24 15:35) — remplace [20261024-c]

- **[CHANGED]** `contracts/models.md` — `Controller.assignable` et `RoleChange.force` **retirés** (D5 : l'interne UART est affectable comme les dongles, `bus` reste affiché) ; `Roles.restart_expected` ajouté ; compteur SSE `id` réinitialisé au redémarrage (client : `state` ou `id` inférieur ⇒ resync).
- **[CHANGED]** `contracts/http-endpoints.md` — `PUT /api/controllers/roles` : plus de 400 « UART sans force » ; application par **redémarrage piloté du service** (202 puis coupure ≈ 10–15 s) ; 409 `change_pending` sur toutes les écritures jusqu'à l'arrêt.
- **[CHANGED]** `contracts/config-schema.md` — § Affectation : séquence D3 b (`btmux-adapters.path` → `btmux-adapters-reload.service` → `systemctl restart btmuxd`, repli code 4 après 20 s). Statut DRAFT retiré partout. Non BREAKING.

## [20261024-e] — précisions #23 post-WIP (G1–G8 du rapport planner, validées par l'utilisateur le 2026-10-24) — non BREAKING

- **[CHANGED]** `contracts/http-endpoints.md` — `PUT /api/controllers/roles` : corps strict (clé inconnue → 400 `invalid_body`), codes 400 nommés (`invalid_body`, `invalid_confirm`, `invalid_mac`, `unknown_controller`, `same_controller`), **no-op → 200** `Roles` inchangé sans redémarrage, `details` de `devices_connected` = `[{mac, alias, name, adapter}]` ; `change_pending` couvre aussi `DELETE /api/pairing` et `PATCH /api/devices/{mac}` ; champ d'erreur optionnel `details`.
- **[NEW]** `contracts/http-endpoints.md` — interface `btmuxctl controllers` et `btmuxctl roles set --sources <MAC|none> --headsets <MAC|none> [--confirm]`.
- **[CHANGED]** `contracts/models.md` — `Controller.name` = alias BlueZ courant ; valeurs d'un contrôleur `present:false` (`hci:null`, `bus:"unknown"`…) ; source sysfs de `bus`/`usb_id` ; compteur SSE : `state` initial à l'id courant (0 au démarrage), premier événement réel à 1 ; forme des erreurs avec `details`.
- **[CHANGED]** `contracts/config-schema.md` — fichier d'état invalide = repli config + journal `state_invalid` ; `btmuxd --check-config` affiche la provenance ; `python -m btmux.config adapters --state` documenté (liste effective pour `btmux-adapters.sh`).

## [20261024-f] — précisions #23 post-revue (validées par l'utilisateur le 2026-10-24) — non BREAKING

- **[CHANGED]** `contracts/http-endpoints.md` — `PUT /api/controllers/roles` : le no-op (200) est évalué avant tout 409 d'état (prioritaire sur `pairing_open`) ; ordre de contrôle 400 → no-op → `change_pending` → `pairing_open` → `devices_connected` ; **[NEW]** code 500 `state_write_failed` (écriture du fichier d'état impossible : aucune déconnexion, `pending:false`, `Roles` inchangé).
- **[CHANGED]** `contracts/config-schema.md` — séquence D3 : l'écriture de l'état précède la fermeture de la fenêtre et les déconnexions (échec → 500 sans effet) ; délai de repli code 4 porté de **20 s à 30 s**.

## [20261024-g] — alignement D3 sur l'infra livrée (`c24ffba`, rapport `infra-20261024-194500` écart 1) — non BREAKING

- **[CHANGED]** `contracts/config-schema.md` — § Affectation étape 2 : `btmux-adapters-reload.service` ne fait que redémarrer `btmuxd` ; l'identité des contrôleurs (`btmux-adapters.sh --state …`) est appliquée par l'`ExecStartPre` de `btmuxd.service` à chaque démarrage (redémarrage piloté, repli code 4, boot) ; coupure attendue de l'API ≈ **15–20 s** (au lieu de 10–15 s, aussi dans `http-endpoints.md`). Le libellé de la Web UI (« environ 15 s ») et la procédure R-16 suivent.

## [20261024-h] — réserves QA matériel #23 (`qa-20261024-201039` écarts 1 et 2, décisions utilisateur du 2026-10-24) — non BREAKING

- **[CHANGED]** `contracts/config-schema.md` — § Affectation : **l'alias suit le rôle** (`name` écrit dans l'état = nom du rôle : entrée `config.yaml` portant le rôle, sinon `btmux` / `btmux-hp` ; mono-rôle double → nom `sources`), au lieu d'être repris par MAC.
- **[NEW]** `contracts/config-schema.md` — § Affectation : **identité réappliquée au hotplug** — le daemon écrit `/var/lib/btmux/identity.request` à l'apparition (`InterfacesAdded`) d'un contrôleur affecté ; `btmux-adapters-identity.path` → `btmux-adapters-identity.service` (root, oneshot) rejoue `btmux-adapters.sh --wait 5` sans redémarrer `btmuxd` (≤ 10 s) ; journaux `identity_requested` / `identity_request_failed`. Mesures QUALIF 0.2.0.5 de la coupure (16,9–18,3 s) notées.

## [20261025-a] — identité au hotplug ciblée (`infra-20261024-211455` point 1, décision utilisateur du 2026-10-25) — non BREAKING

- **[CHANGED]** `contracts/config-schema.md` — § Affectation « identité réappliquée au hotplug » : `btmux-adapters-identity.service` rejoue `btmux-adapters.sh --only <MAC>` lue dans `identity.request` (3e champ) et ne traite que le contrôleur réapparu — une fenêtre d'appairage ouverte sur l'autre contrôleur n'est plus refermée. Format du fichier figé (`ISO\thciN\tMAC`, 0640, atomique, existe vide à l'installation) ; comportement de `--only` pour une MAC non affectée (fermée seulement), absente ou invalide (avertissement, code 0) ; requêtes rapprochées coalescées, le daemon réémet si la classe observée ≠ rôle (au plus une par contrôleur et par minute).

## [20261025-b] — réserves de revue `code-reviewer-20261025-091500` (hotplug/alias), décision utilisateur du 2026-10-25 — non BREAKING

- **[CHANGED]** `contracts/config-schema.md` — `identity.request` **multi-lignes** (une ligne `ISO\thciN\tMAC` par MAC en attente, réécriture atomique de l'ensemble, débounce ≤ 1 s) ; service root : fichier régulier exigé (lien symbolique → ignoré, avertissement), lignes dédoublonnées, lignes invalides ignorées sans reproduire le contenu, `--only` répété, code 0 toujours, `StartLimitIntervalSec=0`.
- **[NEW]** `contracts/config-schema.md` — acquittement par classe observée ; **vérification différée à +60 s**, 3 tentatives max par contrôleur et par épisode, puis ERROR `identity_giving_up` ; aucune requête pendant `roles.pending`. Remplace « au plus une par contrôleur et par minute ».
- **[CHANGED]** `contracts/config-schema.md` — limite documentée : nom personnalisé perdu après libération d'un rôle quand l'état prime (contournement indiqué).

## [20261025-c] — alignement sur l'infra livrée `3a9263c` (`infra-20261025-090759` « Décision ») — non BREAKING

- **[CHANGED]** `contracts/config-schema.md` — § identité au hotplug : `btmux-adapters-identity.service` appelle `btmux-adapters.sh --requests /var/lib/btmux/identity.request` (option documentée : fichier régulier exigé, lecture bornée 4 Kio, dédoublonnage, lignes invalides comptées sans reproduire le contenu, = un `--only` par MAC valide) ; codes de sortie du script inchangés (2 config invalide, 0 sinon) — la garantie « ne jamais échouer » est portée par l'unité (`SuccessExitStatus=2`, `StartLimitIntervalSec=0`).

## [20261025-d] — écarts QA Pi 0.2.0.6 (`qa-20261025-100508` 1 et 2), décision utilisateur du 2026-10-25 — non BREAKING

- **[CHANGED]** `contracts/config-schema.md` — § identité au hotplug : **relecture de `identity.request` en fin de passe** par `btmux-adapters.sh --requests` (MAC nouvelles traitées dans la foulée, 3 relectures max par exécution, MAC déjà traitées ignorées ; ≤ ~10 s après écriture) ; le daemon **réécrit le fichier sans les MAC acquittées ou abandonnées** (vide quand rien n'est en attente) — la réécriture déclenche le `.path` mais un fichier vide/sans nouveauté se termine en code 0 sans passe.

## [20261025-e] — arbitrage rejeu idempotent (`infra-20261025-104500` § Conformité) — non BREAKING

- **[CHANGED]** `contracts/config-schema.md` — § identité au hotplug : « MAC déjà traitées ignorées » s'entend **au sein d'une exécution** ; aucun état persistant côté root — une exécution déclenchée par la réécriture du daemon peut **rejouer une fois** une MAC encore en attente (passe idempotente ≈ 4 s, le script n'écrit jamais le fichier → pas de boucle) ; `TimeoutStartSec=60` et pire cas `btmgmt` (10 s/appel) notés.

## [20261026-a] — contrôle post-sortie de l'unité identité (`infra-20261026-114500`, QA 0.2.0.8 écart 1, SHA `adb1837`) — non BREAKING

- **[CHANGED]** `contracts/config-schema.md` — § identité au hotplug : `btmux-adapters-identity.service` consigne les MAC lues (`--done-file /run/btmux-identity/done`, `RuntimeDirectory=`) et porte un **`ExecStopPost=btmux-adapters.sh --rearm …`** qui relit `identity.request` après la sortie du script : une MAC valide **non lue** par l'exécution → **une seule** relance `systemctl start --no-block` (mise en file en état `stop-post`, jamais fusionnée) ; sinon rien. Réduit à quelques ms la fenêtre « écriture entre la dernière relecture et la sortie » (résiduel : écriture après la lecture du contrôle et avant l'inactivité de l'unité, rattrapé par la réémission btmuxd +60 s — `code-review-20261026-103712` §1) ; **jamais de boucle** (relance seulement sur MAC nouvelle, l'exécution relancée lit tout le fichier) ; les MAC laissées par la borne de 3 relectures sont relancées immédiatement. Format de `identity.request` et délai (≤ ~10 s) **inchangés** ; aucun changement de `btmuxd` ni du packaging.
