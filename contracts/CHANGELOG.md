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
