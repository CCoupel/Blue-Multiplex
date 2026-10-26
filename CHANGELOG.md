# Changelog

## [0.2.0] — Unreleased

Exploration technique bi-adaptateur (2 × TP-Link UB500) : revalidation de la topologie cible (`hci-src` / `hci-hp`),
préparation sans matériel, puis campagne de spikes. Pas de daemon fonctionnel complet.

### Added (T2.1 #20)
- `btmux.bluez` : bus D-Bus système (dbus-fast, reconnexion), adaptateurs par MAC, agent `NoInputNoOutput` « fenêtre seulement » (refus par défaut), `PairingManager` (`open/close`, `pair/connect/disconnect/forget/set_trusted`, erreurs typées `BondStale`/`NotFound`/`WindowClosed`/`WindowOpen`), inventaire + file d'événements (modèles de `contracts/models.md`), journal structuré `clé=valeur`.
- `btmuxd` : se connecte à BlueZ au démarrage ; adaptateur introuvable après `BTMUX_ADAPTER_WAIT` s (défaut 30) → code de sortie 3.

### Added (T2.3 #21)
- `btmux.api` (aiohttp) : routes `/api/*` de `contracts/http-endpoints.md`, auth Bearer (`hmac.compare_digest`, 401), SSE `/api/events` (keep-alive 15 s, `Last-Event-ID` tampon 100 sinon évènement `state`), Web UI statique `Cache-Control: no-store`, API verrouillée si le jeton est illisible, code de sortie 2 si `api.listen` est invalide ou occupé.
- `btmuxctl` : `state`, `pairing open|close`, `device pair|connect|disconnect|forget` (`--url`/`--token`, `BTMUX_URL`/`BTMUX_TOKEN`, `/etc/btmux/token`).
- Dépendance : `aiohttp`.

### Added (T2.2 #16)
- Web UI d'appairages servie par l'API (`/`, `/static/*`, HTML/CSS/JS sans framework) : fenêtre d'appairage par rôle,
  appareils découverts et connus, actions pair/connect/disconnect/forget, mise à jour par SSE avec repli. Maquette validée au GATE 2
  (`docs/mockup/v0.2.0/ui/webui_pairing__appairages.html`).

### Security (LOT-2 revue/audit)
- API : arrêt < 5 s avec flux SSE ouverts ; `Authorization`/`Last-Event-ID` invalides sans trace ; évènement `state` à l'ouverture du flux ; jeton lisible par groupe/autres → API verrouillée ; CSP, `nosniff`, `X-Frame-Options`, `Referrer-Policy` ; statiques limités à html/js/css ; avertissement `api_listening_cleartext` hors loopback.
- BlueZ : `PairableTimeout`, rollback de `open()`, `pair()` découplé de la requête HTTP (409 `operation_in_progress`), `ExecStopPost` de btmuxd (`btmux-adapters.sh --reset`) ; regex MAC/alias en `fullmatch`.

### Fixed (QUALIF 0.2.0.2)
- `btmuxd` : BlueZ rend l'adaptateur `Pairable` dès qu'un agent est enregistré (constaté sur pi-qualif) ; l'état sûr (Pairable/Discoverable faux) est maintenant posé APRÈS l'enregistrement de l'agent, vérifié (3 essais, `adapter_not_closed` en ERROR sinon) ; journal `agent_registered`.

### Fixed (séance GATE 4 LOT-2)
- Appairage entrant « Just Works » : BlueZ n'appelle pas l'agent ; `Trusted` est posé sur le signal `Paired` pendant une fenêtre `sources` (WARN `unexpected_incoming_pairing`, sans confiance, hors fenêtre).
- `kind`/rôle hors config : la classe majeure (audio 0x04 → casque, ordinateur/téléphone → source) prime sur les UUID (un casque expose A2DP source ET sink) ; l'origine de l'appairage arbitre les cas ambigus.

### Changed (LOT-2)
- `btmuxd.service` : `RestartPreventExitStatus=2` seul (le code 3, adaptateur absent, est relancé), `RestartSec=30`, `StartLimitBurst=30` / 1 h — dongles USB lents à énumérer.

### Changed
- Config : `adapters[].mac` dupliquée refusée ; `adapters[].name` sans caractère de contrôle (sortie TSV de `btmux.config adapters` non forgeable) ; `btmux-adapters.sh` : `python -I -P`, `btmgmt` en échec = avertissement + code 0 ; installation pip `--only-binary=:all:` ; agent de spike fail-closed.
- `btmuxd.service` durci (`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp`, `RestartPreventExitStatus=2 3`) ;
  `deploy.sh` exige le lockfile à côté de la wheel (`btmux-<V>.requirements.lock.txt`).
- Configuration bi-adaptateur (#14) : règle V4 levée (1 ou 2 adaptateurs acceptés ; 3 refusés avec
  `config: at most 2 adapters are supported (found N)`), `config/config.example.yaml` en deux adaptateurs (forme mono en commentaire).
- `btmuxd --config <path>` ne sort plus immédiatement : il valide la configuration, se connecte à BlueZ (code 3 si un
  adaptateur de `adapters[]` reste introuvable pendant 30 s), démarre l'API HTTP et reste actif jusqu'à SIGTERM/SIGINT
  (code 0). `--check-config` est inchangé (#20 #21).
- Jeton d'API : généré dans `/etc/btmux/token` (0600) à l'installation s'il manque, jamais régénéré (#17).
- Mise à jour : le `.deb` 0.2.0 ne réécrit pas `/etc/btmux/config.yaml` (créé depuis l'exemple seulement s'il est absent) et
  ne régénère pas le jeton ; une configuration mono-adaptateur v0.1.0 reste valide (#17).

### Added
- Packaging déterministe (#17) : lockfile runtime haché (`dist/requirements.lock.txt`, produit par `scripts/ci.sh`), paquet `.deb` avec
  `postinst` (venv, `pip install --require-hashes --no-deps -r`, wheel `--no-index`), `prerm`/`postrm`, `btmux-adapters.service`, policy D-Bus
  de l'utilisateur de service, jeton d'API 0600 généré, `scripts/btmux-configure.sh` partagé avec `scripts/deploy.sh`.
- Clé de configuration optionnelle `pairing` (`default_duration` 1..300 s, `accept_incoming`), règle V11 (#14, #20).
- Brouillons de contrats `contracts/http-endpoints.md` et `contracts/models.md` (DRAFT, API appairages — #20 #21 #16).
- Outils de séance bi-adaptateur `spikes/common` (`watch_hci`, `link_guard`, agent, `roles.conf`, résolution par rôle) et
  orchestration des spikes `spikes/t32b` (scripts #6 voix et #8 latence, routage par adaptateur) (#18).
- Environnement QUALIF : companions `deploy.qualif.md` et `qualif.env.example` avec `FORBIDDEN_HOSTS` (hôtes interdits :
  jamais de `ssh`/`scp` vers un Pi en service) (#18).

### Fixed (#23, 0.2.0.8 → 0.2.0.12)
- Identité des contrôleurs au hotplug : le `identity.request` résiduel est vidé au démarrage du daemon quand rien n'est en
  attente ; un résidu déjà traité n'est plus réécrit, et l'échec du vidage est journalisé.
- Permutation des rôles (`PUT /api/controllers/roles`) avec `confirm` : les appareils connectés sur les rôles modifiés sont
  déconnectés **en parallèle et confirmés avant** l'écriture de l'état (délai borné, ≲ 5 s au total) ; un appareil déjà
  déconnecté compte comme succès. Échec de déconnexion, ou reconnexion avant écriture : **502 `disconnect_failed`** (`details`
  = appareils encore connectés), rien n'est écrit, pas de redémarrage. Les contrôles `change_pending` et `pairing_open` sont
  rejoués après les déconnexions.
- Web UI : attente affichée pendant le `PUT` des rôles (libellé ≲ 5 s), message dédié au 502 `disconnect_failed`, garde
  anti double envoi (l'état « occupé » des rôles est conservé pendant le PUT confirmé).

### Changed (#23)
- Limite de rattrapage acceptée : quand deux dongles apparaissent à quelques secondes d'écart, le second peut recevoir son
  identité (nom `btmux` / `btmux-hp`, classe) **≈ 60–70 s** plus tard (réémission btmuxd) au lieu de quelques secondes. Rien n'est perdu.
  Consigne d'exploitation : brancher ou rebrancher **un dongle à la fois** et attendre ≈ 10 s entre deux (`docs/install-pi.md` §6.5).
- Contrats : `contracts/CHANGELOG.md` entrées `[20261026-a]` à `[20261026-d]` (contrôle post-sortie retiré, S3 alignée sur l'implémentation).

### Reporté
- Policy D-Bus de l'utilisateur de service : resserrement des droits à faire avant la mise en production (#20, M3).
- Plafond du nombre de flux SSE simultanés (F6).
- Durcissements systemd supplémentaires de `btmuxd.service` (I4, I5).
- HTTPS pour l'API et la Web UI (#22, v0.3.0).

### Connu
- Un adaptateur mono-rôle à deux rôles (configuration mono) est listé deux fois dans l'état de l'API : comportement accepté en v0.2.0.
- HTTP clair sur le LAN, jeton Bearer statique : l'API est utilisable sur un LAN de confiance uniquement (`api.listen: "127.0.0.1:8088"` pour le local).

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
