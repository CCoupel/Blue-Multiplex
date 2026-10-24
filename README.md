# Blue-Multiplex

Un Raspberry Pi (`btmux`) équipé de deux dongles Bluetooth sert de multiplexeur : il apparaît comme un casque
aux sources (PC, téléphones) et comme une source aux casques, le routage étant logiciel (PipeWire/WirePlumber)
via le daemon `btmuxd`. Aucun logiciel n'est requis côté sources.

> **Statut** : v0.1.0 clôturée le 2026-10-23 **sans release** (aucun tag, aucun paquet publié). Le daemon valide sa
> configuration et reste actif ; le routage audio arrive en v0.3.0.
>
> **v0.2.0 (LOT-1 livré, sans matériel)** : configuration bi-adaptateur, packaging déterministe (lockfile haché, jeton
> d'API), unité durcie. Les deux dongles UB500 restent à réceptionner : procédure dans
> [docs/install-pi.md §6](docs/install-pi.md#6-deux-dongles-ub500-cible-bi-adaptateur).

- Cadrage : [docs/cadrage.md](docs/cadrage.md)
- Installation du Pi : [docs/install-pi.md](docs/install-pi.md)

## Roadmap

- **v0.1.0** — exploration mono-adaptateur, clôturée sans release (socle, spikes #5 et #7 provisoires).
- **v0.2.0** — exploration technique bi-adaptateur (2 × TP-Link UB500) : préparation des dongles, campagne de
  revalidation (T3.2b), agent d'appairage BlueZ (#20), API HTTP (#21), Web UI de suivi et gestion des appairages (#16).
> **Sécurité de l'API (v0.2.0)** : HTTP **en clair** sur le LAN (jeton Bearer statique) ; HTTPS prévu en #22 (v0.3.0). Pour une
> utilisation locale seulement : `api.listen: "127.0.0.1:8088"`. Le jeton `/etc/btmux/token` doit être en mode 0600, sinon l'API
> reste verrouillée (401).
- **v0.3.0** — daemon `btmuxd` : routage, reconnexion, politique de connexions ; MQTT prévu en v0.4.0.

## État des spikes

| # | Sujet | Verdict | Rapport |
|---|-------|---------|---------|
| 5 | Exposition mono-adaptateur (« casque générique ») | RÉSERVES, **provisoire** (Bluetooth interne du Pi 3) | [docs/spikes/05-exposure.md](docs/spikes/05-exposure.md) |
| 6 | Double rôle HFP | **reporté** à la campagne UB500 (v0.2.0) | — |
| 7 | Routage PipeWire (bascule de source par liens) | RÉSERVES, **provisoire** (mécanisme `pw-*` retenu) | [docs/spikes/07-routing.md](docs/spikes/07-routing.md) |

Matériel : 2 dongles TP-Link UB500 (RTL8761BU) commandés ; à revalider à réception. Les verdicts actuels ne valent
que pour le Bluetooth interne du Pi 3, dont le développement radio est arrêté.

## Développement

Prérequis : Python ≥ 3.12 (3.12 et 3.14 testés en CI ; le Pi cible tourne Python 3.14), [`uv`](https://docs.astral.sh/uv/) (installé hors repo : `curl -LsSf https://astral.sh/uv/install.sh | sh`
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

Le paquet `btmux_<X.Y.Z>_all.deb` est produit par `scripts/build-deb.sh` (aucune release publique à ce jour). Il installe la wheel, l'unité systemd
`btmuxd.service`, la configuration d'exemple et `btmux-set-user.sh` ; le venv `/opt/btmux` est créé sur le Pi.

1. Provisionner le Pi (Ubuntu Server 26.04 LTS arm64, Bluetooth, PipeWire, session de l'utilisateur de service avec linger) : [docs/install-pi.md](docs/install-pi.md).
2. Copier et adapter la configuration : `config/config.example.yaml` → `/etc/btmux/config.yaml`
   (renseigner l'adresse MAC du contrôleur, jamais `hci0`), puis vérifier :

   ```bash
   btmuxd --config /etc/btmux/config.yaml --check-config
   ```

   Le schéma de référence est dans [contracts/config-schema.md](contracts/config-schema.md).
   Le jeton de l'API HTTP (v0.2.0) est généré à l'installation dans `/etc/btmux/token` (mode 0600, propriétaire
   l'utilisateur de service) et n'est jamais régénéré s'il existe ; il s'envoie en `Authorization: Bearer <jeton>`.
3. Installer le paquet : `sudo dpkg -i btmux_<X.Y.Z>_all.deb`, puis `sudo systemctl enable --now btmuxd`.
   L'utilisateur de service de `btmuxd` (celui dont la session PipeWire est utilisée, linger activé) est, dans
   l'ordre : `BTMUX_USER` s'il est fourni, sinon l'utilisateur qui lance `sudo`, sinon `ubuntu`. Pour le choisir :

   ```bash
   sudo BTMUX_USER=<utilisateur> dpkg -i btmux_<X.Y.Z>_all.deb
   ```

   Un drop-in `/etc/systemd/system/btmuxd.service.d/user.conf` déjà présent n'est pas écrasé sans `BTMUX_USER`.
   Pour le modifier plus tard : `sudo /usr/lib/btmux/btmux-set-user.sh <utilisateur>` puis `sudo systemctl daemon-reload`
   et `sudo systemctl restart btmuxd`. Le compte root est refusé.

Déploiement sur le Pi de qualification depuis une wheel déjà construite : `scripts/deploy.sh <env> <wheel>`.
Le fichier d'environnement `.claude/agents/environments/<env>.env` (modèle : `qualif.env.example` dans le même
répertoire) fournit `SSH_KEY_PATH`, `DEPLOY_HOST` (`ubuntu@btmux-qualif.local`) et, en option, `BTMUX_USER` (utilisateur de service
de `btmuxd`, défaut = partie utilisateur de `DEPLOY_HOST`). Le script est idempotent et ne remplace jamais une
configuration existante. Prérequis côté Pi : l'utilisateur SSH doit pouvoir lancer `sudo` **sans mot de passe**
(`NOPASSWD`, `BatchMode=yes` interdit toute invite) et le Pi doit avoir accès à `apt` et à PyPI (installation de
`python3-venv` si absent et des dépendances Python).
