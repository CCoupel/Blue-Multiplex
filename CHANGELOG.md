# Changelog

## [0.1.0]

Phase 0 — mono-adaptateur : un Raspberry Pi avec un seul dongle Bluetooth, qui porte les deux rôles
(`sources` et `headsets`). Pas encore de routage audio : le daemon démarre, valide sa configuration et reste vivant.

### Added
- Squelette Python `btmux` (daemon `btmuxd`, client `btmuxctl` en stub), outillage ruff/mypy/pytest (#1).
- `btmuxd --version`, `btmuxd --config <path>`, `btmuxd --check-config` (codes de sortie 0 / 2) (#1, #4).
- Module `btmux.config` : schéma `/etc/btmux/config.yaml`, liste `adapters` (un seul adaptateur en v0.1.0),
  appareils, `default_routes`, bloc `api` ; validation V1–V10, erreurs collectées une par ligne (#4).
- Unité systemd `btmuxd.service` (session PipeWire de l'utilisateur de service via `loginctl enable-linger` ; utilisateur paramétrable par drop-in `scripts/btmux-set-user.sh`) (#2).
- Exemple de configuration `config/config.example.yaml` (#2).
- Paquet Debian `btmux_<X.Y.Z>_all.deb` (`scripts/build-deb.sh`) et déploiement sur le Pi de qualification
  (`scripts/deploy.sh`), sans rebuild ni publication (#2).
- Procédure de provisionnement du Pi de qualification `docs/install-pi.md` (#3).

### Changed
- `btmuxd --config <path>` (sans `--check-config`) ne sort plus en 0 après validation : le daemon reste vivant
  jusqu'à SIGTERM/SIGINT (code 0), pour que l'unité systemd soit réellement active (#2, #4).
- Cible du Pi : Ubuntu Server 26.04 LTS arm64 (au lieu de Raspberry Pi OS / Debian Trixie) ; utilisateur de service `ubuntu` par défaut, paramétrable via `BTMUX_USER` (#2 #3).

### Fixed
- Corrections de revue de code du lot 1 (#2, #4) :
  - validation des routes sans valeurs non hashables (refus propre au lieu d'une exception) ;
  - `scripts/deploy.sh` : propagation correcte des codes de sortie ;
  - `scripts/build-deb.sh` : sélection de la wheel sans confusion entre `0.1.1` et `0.1.10`, message clair si absente ;
  - répertoire de travail du build configurable (`BUILD_TMPDIR`), répertoire distant de déploiement en `mktemp -d`.
