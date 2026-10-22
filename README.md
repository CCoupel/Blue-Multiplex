# Blue-Multiplex

Un Raspberry Pi (`btmux`) équipé de deux dongles Bluetooth sert de multiplexeur : il apparaît comme un casque
aux sources (PC, téléphones) et comme une source aux casques, le routage étant logiciel (PipeWire/WirePlumber)
via le daemon `btmuxd`. Aucun logiciel n'est requis côté sources.

> **Statut** : v0.1.0 (phase 0, mono-adaptateur) — le daemon valide sa configuration et reste actif ; le routage
> audio arrive en v0.3.0.

- Cadrage : [docs/cadrage.md](docs/cadrage.md)
- Installation du Pi : [docs/install-pi.md](docs/install-pi.md)

## Développement

Prérequis : Python 3.12, [`uv`](https://docs.astral.sh/uv/) (installé hors repo : `curl -LsSf https://astral.sh/uv/install.sh | sh`
→ `~/.local/bin/uv`, à ajouter au `PATH`), `jq`, `dpkg-deb`.

```bash
uv sync --all-groups   # dépendances
scripts/ci.sh          # deps, lint, typecheck, tests + couverture, audit, build (artefacts dans dist/)
```

`scripts/ci.sh` exclut les tests marqués `hardware` (BlueZ/PipeWire réels) : ils s'exécutent uniquement sur le Pi
de qualification, jamais en CI.

**Sous WSL** (dépôt sur un système de fichiers Windows) : `dpkg-deb` exige des modes de fichiers POSIX que le
montage `drvfs` ne fournit pas. Pour `scripts/build-deb.sh`, pointer le répertoire de staging vers un système de
fichiers Linux natif :

```bash
BUILD_TMPDIR=$HOME/btmux-build scripts/build-deb.sh 0.1.0
```

Par défaut, le staging se fait dans `_work/tmp/` (gitignoré).

## Installation sur le Pi

Le paquet `btmux_<X.Y.Z>_all.deb` est attaché à chaque GitHub Release. Il installe la wheel, l'unité systemd
`btmuxd.service` et la configuration d'exemple ; le venv `/opt/btmux` est créé sur le Pi.

1. Provisionner le Pi (OS, Bluetooth, PipeWire, session `pi` avec linger) : [docs/install-pi.md](docs/install-pi.md).
2. Copier et adapter la configuration : `config/config.example.yaml` → `/etc/btmux/config.yaml`
   (renseigner l'adresse MAC du contrôleur, jamais `hci0`), puis vérifier :

   ```bash
   btmuxd --config /etc/btmux/config.yaml --check-config
   ```

   Le schéma de référence est dans [contracts/config-schema.md](contracts/config-schema.md).
3. Installer le paquet : `sudo dpkg -i btmux_<X.Y.Z>_all.deb`, puis `sudo systemctl enable --now btmuxd`.

Déploiement sur le Pi de qualification depuis une wheel déjà construite : `scripts/deploy.sh <env> <wheel>`.
Le fichier d'environnement `.claude/agents/environments/<env>.env` (modèle : `qualif.env.example` dans le même
répertoire) fournit `SSH_KEY_PATH` et `DEPLOY_HOST`. Le script est idempotent et ne remplace jamais une
configuration existante.
