# Blue-Multiplex

Un Raspberry Pi (`btmux`) équipé de deux dongles Bluetooth sert de multiplexeur : il apparaît comme un casque
aux sources (PC, téléphones) et comme une source aux casques, le routage étant logiciel (PipeWire/WirePlumber)
via le daemon `btmuxd`. Aucun logiciel n'est requis côté sources.

- Cadrage : [docs/cadrage.md](docs/cadrage.md)
- Installation du Pi : [docs/install-pi.md](docs/install-pi.md)

## Développement

Prérequis : Python 3.12, [`uv`](https://docs.astral.sh/uv/) (installé hors repo : `curl -LsSf https://astral.sh/uv/install.sh | sh`
→ `~/.local/bin/uv`, à ajouter au `PATH`), `jq`, `dpkg-deb`.

```bash
uv sync --all-groups   # dépendances
scripts/ci.sh          # lint, mypy, tests + couverture, audit, build
```

Les tests marqués `hardware` s'exécutent uniquement sur le Pi de qualification.
