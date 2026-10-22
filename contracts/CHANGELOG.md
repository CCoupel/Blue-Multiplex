# Changelog des contrats

> Changements de contrats (API, schemas) : `BREAKING` | `CHANGED` | `ADDED`. Lu par le CDP au GATE 2.

## [20261022] — milestone v0.1.0 (phase 0, mono-adaptateur)

- **[NEW]** `contracts/config-schema.md` — schéma `/etc/btmux/config.yaml` (liste `adapters` à `roles`, règles V1–V10), interface CLI `btmuxd --version / --check-config` et API Python `btmux.config` (#4). Aucun contrat HTTP/WebSocket en v0.1.0.
- **[CHANGED]** `btmuxd --config <path>` (sans `--check-config`) : ne sort plus en 0 immédiatement ; après validation il reste vivant (asyncio) jusqu'à SIGTERM/SIGINT (code 0), pour que l'unité systemd soit réellement active. Non BREAKING : aucun consommateur (#2 #4).
