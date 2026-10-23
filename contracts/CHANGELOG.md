# Changelog des contrats

> Changements de contrats (API, schemas) : `BREAKING` | `CHANGED` | `ADDED`. Lu par le CDP au GATE 2.

## [20261022] — milestone v0.1.0 (phase 0, mono-adaptateur)

- **[NEW]** `contracts/config-schema.md` — schéma `/etc/btmux/config.yaml` (liste `adapters` à `roles`, règles V1–V10), interface CLI `btmuxd --version / --check-config` et API Python `btmux.config` (#4). Aucun contrat HTTP/WebSocket en v0.1.0.
- **[CHANGED]** `btmuxd --config <path>` (sans `--check-config`) : ne sort plus en 0 immédiatement ; après validation il reste vivant (asyncio) jusqu'à SIGTERM/SIGINT (code 0), pour que l'unité systemd soit réellement active. Non BREAKING : aucun consommateur (#2 #4).

## [20261023] — révision bi-adaptateur (T3.2b à 2 dongles — sous réserve GATE 2)

- **[CHANGED]** `contracts/config-schema.md` — V4 levée : 1 ou 2 adaptateurs acceptés (max 2), message `config: at most 2 adapters are supported` ; forme bi-adaptateur documentée (#14). Rétrocompatible : toute config mono valide reste valide. Le test `critical` « multi-adaptateur refusé » (V4) devient « 3 adaptateurs refusés ».


## [20261023-b] — v0.2.0 LOT-2 « appairages + Web UI » (#20 #21 #16) — DRAFT, sous réserve GATE 2

- **[NEW]** `contracts/http-endpoints.md` — API HTTP `btmuxd` périmètre appairages (`/api/state`, `/api/pairing`, `/api/devices/{mac}/*`, `/api/events` SSE), jeton Bearer, aiohttp.
- **[NEW]** `contracts/models.md` — modèles `State`, `Adapter`, `Device`, `Discovered`, `PairingWindow`, événements SSE.
- **[CHANGED]** `contracts/config-schema.md` — `btmuxd --config` ne sort plus immédiatement : démarre le daemon (BlueZ + API) ; nouvelle clé optionnelle `pairing: { default_duration: 60, accept_incoming: true }` ; `api.token_file` généré à l'installation (0600). Rétrocompatible (défauts).
