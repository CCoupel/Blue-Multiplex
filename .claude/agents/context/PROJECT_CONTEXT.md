# PROJECT_CONTEXT.md — Contexte technique Blue-Multiplex (btmux)

> Fichier PROJET (tracké git, jamais écrasé par la sync). Référencé par `context/COMMON.md`,
> `context/DEV_COMMON.md`, `context/VALIDATION_COMMON.md` et `commands/context/COMMON.md` §10.
> Source de vérité des valeurs : `.claude/project-config.json`. Cadrage fonctionnel : `docs/cadrage.md`.

## Stack

| Couche | Technologie |
|--------|-------------|
| Daemon `btmuxd` | Python ≥ 3.12, asyncio, `dbus-fast` (BlueZ D-Bus), PipeWire piloté par `pw-dump -m` (événements) + session `pw-cli` persistante (liens reconstruits si la session meurt ; Lua WirePlumber non retenu — spike #7) |
| API HTTP | aiohttp (+ flux SSE), LAN uniquement, jeton statique (`/etc/btmux/token`) |
| CLI `btmuxctl` | Python, consomme l'API |
| Web UI | HTML/CSS/JS vanilla, statique, servie par l'API — `src/btmux/api/static/` |
| Config | YAML `/etc/btmux/config.yaml` — aucune base de données |
| Cible | Raspberry Pi (qualif : Pi 4 Model B), Ubuntu Server 26.04 LTS arm64, BlueZ, PipeWire ≥ 1.2, WirePlumber 0.5, systemd |
| Outillage | `uv`, `ruff`, `mypy`, `pytest` |

## Structure cible

```
src/btmux/
├── bluez/        # agent d'appairage, adaptateurs (par MAC), profils, AVRCP, HFP
├── pipewire/     # découverte des nœuds, liens, métadonnées, profils des devices
├── routing/      # politique de routage (appel HFP > sélection manuelle > dernier flux actif)
├── api/          # HTTP (+ static/ pour la Web UI), MQTT optionnel
├── cli/          # btmuxctl
└── config/       # chargement/validation YAML
systemd/          # btmuxd.service
config/           # config.example.yaml
scripts/          # ci.sh, build-deb.sh, deploy.sh (qualif)
tests/            # INDEX.md, METRICS.md, lots <famille>/<theme>/<lot>/
docs/             # cadrage.md, mockup/
contracts/        # contrats API (CHANGELOG.md)
```

## Commandes

Toutes définies dans `.claude/project-config.json` (`commands.*`) et exécutées par `scripts/ci.sh` (script unique CI/local) :

| Usage | Commande |
|-------|----------|
| Dépendances | `uv sync --locked --all-groups` |
| Lint | `uv run ruff check . && uv run ruff format --check .` |
| Typecheck | `uv run mypy src` |
| Tests complets | `uv run pytest` |
| Tests rapides (DEV) | `uv run pytest -m "not slow"` |
| Tests ciblés | `uv run pytest {TARGETS}` |
| Couverture (min 70 %) | `uv run pytest --cov=btmux --cov-report=term-missing` |
| Audit dépendances | `uv run pip-audit` |
| Build (wheel) | `uv build` |
| Paquet PROD | `scripts/build-deb.sh <X.Y.Z>` (CI uniquement, sur tag) |

Marqueurs pytest : `slow`, `smoke`, `critical`, `hardware` (nécessite BlueZ/PipeWire réels — exclu de la CI, joué sur le Pi de qualif).

## Routage vers les agents DEV (`commands/context/COMMON.md` §10)

| Fichiers impactés | Agent |
|-------------------|-------|
| `src/btmux/**` (hors `api/static/`), `tests/**`, `pyproject.toml`, `config/` | `dev-backend` |
| `src/btmux/api/static/**` | `dev-frontend` |
| `systemd/`, `scripts/`, `.github/workflows/`, `debian/` | `infra` |

**Ordre d'exécution** : `dev-backend` avant `dev-frontend` dès qu'un endpoint ou un schéma de l'API change (contrat dans `contracts/`) ; parallèle sinon.

## Environnements

| Env | Machine | Publish | Deploy |
|-----|---------|---------|--------|
| QUALIF | Pi de qualification (`ubuntu@btmux-qualif.local`) | promote (wheel dans `build/qualif_v<X.Y.Z>/`) | SSH + `scripts/deploy.sh` |
| PROD | Pi de production (`ubuntu@btmux.local`) | rebuild-ci (tag `vX.Y.Z` → `.github/workflows/release.yml` → `.deb`) | SSH + `dpkg -i` |

Procédures détaillées : `.claude/agents/environments/{publish,deploy}.{qualif,prod}.template.md`, complétées par les compagnons
`publish.qualif.md` et `deploy.qualif.md`, qui priment sur le template (aucun compagnon PROD pour l'instant).

## Contraintes permanentes

- Aucun logiciel, pilote ou configuration côté sources (PC pro verrouillé) : le Pi est un casque Bluetooth générique.
- Adaptateurs identifiés par adresse MAC, jamais par `hci0`/`hci1`.
- Appairage refusé hors fenêtre explicite (60 s) ; appareils appairés marqués Trusted.
- Un casque = une source active au plus ; priorité appel HFP > sélection manuelle > dernier flux actif.
- Tests `hardware` (BlueZ/PipeWire réels) : sur le Pi de qualif uniquement, jamais en CI.
- Les branches `milestone/*` peuvent être réécrites (purges d'historique) : toujours `git fetch` et vérifier la tête avant d'agir.

## Spikes (exploration technique)

- Label GitHub `spike` ; livrable = rapport `docs/spikes/NN-<sujet>.md` + décision ; code jetable sous `spikes/`
  (hors `src/`, hors couverture).
- Preuves de spikes : jamais commitées brutes ; elles passent par `spikes/common/mask_evidence.py --check` (code 0)
  avant tout commit sous `docs/spikes/`.
- Les spikes radio exigent des étapes manuelles de l'utilisateur (appairages, appels) : chaque ordre DEV de spike
  s'accompagne d'une procédure manuelle en `_work/handoff/`.
