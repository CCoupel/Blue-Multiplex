# Index des tests

> Tests de specification ecrits par le test-writer, ranges en lots `<famille>/<theme>/<lot>/` ; statuts tenus par le CDP.
> Le chemin porte l'identite ; cet index ne porte que l'etat : une ligne par lot (chemin termine par `/`),
> plus des lignes fichier pour les exceptions (quarantaine). Lot sans ligne = `feature`.
> Convention : `context/COMMON.md` section 15. Statuts : `feature` | `regression` | `quarantaine`.
> Tags : `smoke`, `critical`, `slow`, `hardware` (necessite BlueZ/PipeWire reels — execute sur le Pi de qualif, jamais en CI).

| Chemin | Niveau | Composant | Feature | Statut | Tags |
|--------|--------|-----------|---------|--------|------|
| tests/integration/config/validation/ | integration | config | Validation du schema config : MAC, adaptateurs, roles, fichier (V1-V3, V10) | regression | |
| tests/integration/config/devices/ | integration | config | Validation appareils, priorites, routes par defaut, accesseurs (V5-V7) | regression | |
| tests/integration/config/api-strict/ | integration | config | Bloc api, defauts, cles inconnues refusees (V8-V9) | regression | |
| tests/integration/config/critical/ | integration | config | V4 max 2 (3 adaptateurs refuses, bi accepte) et config.example.yaml valide | regression | critical |
| tests/integration/cli/btmuxd-smoke/ | integration | cli | btmuxd --version | regression | smoke |
| tests/integration/cli/btmuxd/ | integration | cli | btmuxd --config / --check-config (codes 0/2) | regression | |
| tests/integration/cli/btmuxctl/ | integration | cli | Stub btmuxctl (code 1) | regression | |
| tests/procedures/packaging/deb-deploy/ | procedure | packaging | Build .deb, unite systemd, deploy.sh qualif, smoke | regression | critical |
| tests/procedures/install/pi-qualif/ | procedure | packaging | Provisionnement du Pi de qualification | regression | |
| tests/procedures/spikes/05-exposure/ | procedure | bluez | Spike #5 : exposition casque generique en mono-adaptateur (BT interne, provisoire) | regression | hardware |
| tests/procedures/spikes/07-routing/ | procedure | pipewire | Spike #7 : routage PipeWire mono-adaptateur (BT interne / UB500) | regression | hardware |
| tests/procedures/spikes/06-hfp-dual-role/ | procedure | bluez | Spike #6 : double role HFP HF+AG (BT interne / UB500) | regression | hardware |
| tests/integration/config/bi-adapter/ | integration | config | Forme bi-adaptateur : V2/V3/V4 max 2 (#14) | feature | |
| tests/integration/config/pairing/ | integration | config | Cle pairing, V11 (#20/#21) | feature | |
| tests/integration/packaging/lockfile/ | integration | packaging | Export lockfile deterministe --no-dev --frozen --hashes (#17) | feature | |
| tests/integration/packaging/scripts/ | integration | packaging | Syntaxe des scripts shell et btmux-adapters.sh --dry-run (#18) | feature | |
| tests/procedures/spikes/revalidation-ub500/ | procedure | bluez | Campagne UB500 bi (S1/S2 : 05, 06, 07, 08, 12, 13) | feature | hardware |
| tests/integration/api/mock/ | integration | api | Fonctions propres au mock API (pilotage, statique, scenarios) (#16) | feature | |
| tests/integration/api/auth/ | integration | api | Authentification Bearer, routes protegees, jeton (#21) | feature | critical |
| tests/integration/api/pairing/ | integration | api | API appairages : fenetre, decouverte, pair/connect/forget, erreurs, SSE (#20 #21) | feature | |
| tests/hardware/bluez/pairing/ | hardware | bluez | Appairages sur le Pi reel : fenetre sources, refus hors fenetre, casque initie par le Pi, forget (#20) | feature | hardware |
| tests/procedures/ui/pairing/ | procedure | webui | Web UI appairages : jeton, fenetre, sources, casques, erreurs, SSE, responsive (#16 #21) | feature | critical |
