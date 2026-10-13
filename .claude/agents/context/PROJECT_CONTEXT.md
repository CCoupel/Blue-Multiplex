# PROJECT_CONTEXT.md — Contexte technique Blue-Multiplex (btmux)

> Fichier PROJET (tracké git, jamais écrasé par la sync). Référencé par `context/COMMON.md`,
> `context/DEV_COMMON.md`, `context/VALIDATION_COMMON.md` et `commands/context/COMMON.md` §10.
> Source de vérité des valeurs : `.claude/project-config.json`. Cadrage fonctionnel : `docs/cadrage.md`.

## Stack

| Couche | Technologie |
|--------|-------------|
| Daemon `btmuxd` | Python ≥ 3.12, asyncio, `dbus-fast` (BlueZ D-Bus), PipeWire piloté via `pw-dump`/`pw-link`/`pw-metadata` ou script Lua WirePlumber (choix phase 0) |
| API HTTP | FastAPI ou aiohttp (choix phase 0), LAN uniquement, jeton statique (`/etc/btmux/token`) |
| CLI `btmuxctl` | Python, consomme l'API |
| Web UI (ultérieure) | HTML/CSS/JS vanilla, statique, servie par l'API — `src/btmux/api/static/` |
| Config | YAML `/etc/btmux/config.yaml` — aucune base de données |
| Cible | Raspberry Pi 4/5, Raspberry Pi OS / Debian Trixie 64 bits, BlueZ, PipeWire ≥ 1.2, WirePlumber 0.5, systemd |
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
| QUALIF | Pi de qualification (`pi@btmux-qualif.local`) | promote (wheel dans `build/qualif_v<X.Y.Z>/`) | SSH + `scripts/deploy.sh` |
| PROD | Pi de production (`pi@btmux.local`) | rebuild-ci (tag `vX.Y.Z` → `.github/workflows/release.yml` → `.deb`) | SSH + `dpkg -i` |

Procédures détaillées : `.claude/agents/environments/{publish,deploy}.{qualif,prod}.template.md`.

## Contraintes permanentes

- Aucun logiciel, pilote ou configuration côté sources (PC pro verrouillé) : le Pi est un casque Bluetooth générique.
- Adaptateurs identifiés par adresse MAC, jamais par `hci0`/`hci1`.
- Appairage refusé hors fenêtre explicite (60 s) ; appareils appairés marqués Trusted.
- Un casque = une source active au plus ; priorité appel HFP > sélection manuelle > dernier flux actif.
