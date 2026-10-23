# Changelog

## [0.2.0] — Unreleased

Exploration technique bi-adaptateur (2 × TP-Link UB500) : revalidation de la topologie cible (`hci-src` / `hci-hp`),
préparation sans matériel, puis campagne de spikes. Pas de daemon fonctionnel complet.

### Changed
- `btmuxd.service` durci (`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp`, `RestartPreventExitStatus=2 3`) ;
  `deploy.sh` exige le lockfile à côté de la wheel (`btmux-<V>.requirements.lock.txt`).
- Configuration bi-adaptateur (#14) : règle V4 levée (1 ou 2 adaptateurs acceptés ; 3 refusés avec
  `config: at most 2 adapters are supported (found N)`), `config/config.example.yaml` en deux adaptateurs (forme mono en commentaire).

### Added
- Packaging déterministe (#17) : lockfile runtime haché (`dist/requirements.lock.txt`, produit par `scripts/ci.sh`), paquet `.deb` avec
  `postinst` (venv, `pip install --require-hashes --no-deps -r`, wheel `--no-index`), `prerm`/`postrm`, `btmux-adapters.service`, policy D-Bus
  de l'utilisateur de service, jeton d'API 0600 généré, `scripts/btmux-configure.sh` partagé avec `scripts/deploy.sh`.
- Clé de configuration optionnelle `pairing` (`default_duration` 1..300 s, `accept_incoming`), règle V11 (#14, #20).
- Brouillons de contrats `contracts/http-endpoints.md` et `contracts/models.md` (DRAFT, API appairages — #20 #21 #16).

## [0.1.0] — 2026-10-23 (non publié : exploration mono-adaptateur, clôturée sans release)

Phase 0 — mono-adaptateur : un Raspberry Pi avec un seul dongle Bluetooth, qui porte les deux rôles
(`sources` et `headsets`). Pas encore de routage audio : le daemon démarre, valide sa configuration et reste vivant.

Clôture : aucun tag, aucun paquet `.deb` publié, aucune mise en production ; `pyproject.toml` reste à `0.1.0.3`.
Les verdicts des spikes #5 et #7 sont **provisoires** (Bluetooth interne du Pi 3) et doivent être revalidés avec les
dongles TP-Link UB500 (RTL8761BU) en v0.2.0. Le spike #6 est reporté à cette campagne.

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
- Script `scripts/btmux-set-user.sh` (installé en `/usr/lib/btmux/set-user.sh`) : choisit l'utilisateur de service de
  `btmuxd` par drop-in systemd, sans modifier l'unité livrée ; refus de root (#2).
- Matrice CI sur Python 3.12 (plancher `requires-python`) et 3.14 (Python d'Ubuntu Server 26.04) (#1).
- Spike #5 (exposition mono-adaptateur, « casque générique ») : rapport `docs/spikes/05-exposure.md`, verdict
  RÉSERVES, **provisoire** (mesuré sur le Bluetooth interne du Pi 3, à revalider avec le dongle RTL8761B) ; outillage
  jetable `spikes/05-exposure/` ; script de masquage des preuves `spikes/common/mask_evidence.py` (#5).
- WirePlumber en mode headless (sans seat logind) : `config/wireplumber/51-btmux-no-seat.conf`
  (`monitor.bluez.seat-monitoring = disabled`) et `scripts/btmux-install-wireplumber.sh`, installés sans écraser un
  fichier existant (#5).
- Spike #7 (routage PipeWire, bascule de source par liens) : rapport `docs/spikes/07-routing.md`, verdict RÉSERVES,
  **provisoire** ; prototype jetable `spikes/07-routing/` ; garde-fou UART `watch_uart.sh` (arrêt au premier
  `tx timeout`). Décision : routage par `pw-dump -m` (événements) et session `pw-cli` persistante pour créer et
  supprimer les liens, repli `pw-link` ; Lua WirePlumber et API native non retenus pour la v0.3.0 (#7).
- Masquage des preuves des spikes #5 et #7 par `mask_evidence.py` (annexes sous `docs/spikes/`) (#5, #7).

### Changed
- `btmuxd --config <path>` (sans `--check-config`) ne sort plus en 0 après validation : le daemon reste vivant
  jusqu'à SIGTERM/SIGINT (code 0), pour que l'unité systemd soit réellement active (#2, #4).
- Cible du Pi : Ubuntu Server 26.04 LTS arm64 (au lieu de Raspberry Pi OS / Debian Trixie) ; utilisateur de service `ubuntu` par défaut, paramétrable via `BTMUX_USER` (#2 #3).
- `scripts/deploy.sh` durci : installe `python3-venv` si absent, garde Python ≥ 3.12 côté Pi, recrée un venv
  incomplet, valide `BTMUX_USER`, `DEPLOY_HOST` et le nom de la wheel avant tout appel `ssh`, refuse root,
  accepte un fichier d'environnement alternatif (`BTMUX_ENV_FILE`) et un `.env` en fins de ligne CRLF (#2).
- Fins de ligne LF forcées pour `scripts/` et `systemd/` via `.gitattributes` (#2).
- Sorties brutes et captures HCI des spikes (`spikes/*/out/`, `*.snoop`) exclues du dépôt via `.gitignore` ; les
  preuves publiées passent par `mask_evidence.py` (#5).
- Historique de la branche `milestone/v0.1.0` réécrit le 2026-10-23 (purges successives, données tierces déplacées
  hors dépôt). Les clones existants doivent être réalignés sur `origin/milestone/v0.1.0` (conserver les travaux
  locaux avant un `git reset`) (#5).

### Fixed
- Corrections de revue de code du lot 1 (#2, #4) :
  - validation des routes sans valeurs non hashables (refus propre au lieu d'une exception) ;
  - `scripts/deploy.sh` : propagation correcte des codes de sortie ;
  - `scripts/build-deb.sh` : sélection de la wheel sans confusion entre `0.1.1` et `0.1.10`, message clair si absente ;
  - répertoire de travail du build configurable (`BUILD_TMPDIR`), répertoire distant de déploiement en `mktemp -d`.
- Copie du fichier WirePlumber sous root quand `BTMUX_USER` diffère de l'utilisateur de déploiement, avec le
  propriétaire `BTMUX_USER` (#5).
