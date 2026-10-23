# Index des tests

> Tests de specification ecrits par le test-writer, ranges en lots `<famille>/<theme>/<lot>/` ; statuts tenus par le CDP.
> Le chemin porte l'identite ; cet index ne porte que l'etat : une ligne par lot (chemin termine par `/`),
> plus des lignes fichier pour les exceptions (quarantaine). Lot sans ligne = `feature`.
> Convention : `context/COMMON.md` section 15. Statuts : `feature` | `regression` | `quarantaine`.
> Tags : `smoke`, `critical`, `slow`, `hardware` (necessite BlueZ/PipeWire reels — execute sur le Pi de qualif, jamais en CI).

| Chemin | Niveau | Composant | Feature | Statut | Tags |
|--------|--------|-----------|---------|--------|------|
| tests/integration/config/validation/ | integration | config | Validation du schema config : MAC, adaptateurs, roles, fichier (V1-V3, V10) | feature | |
| tests/integration/config/devices/ | integration | config | Validation appareils, priorites, routes par defaut, accesseurs (V5-V7) | feature | |
| tests/integration/config/api-strict/ | integration | config | Bloc api, defauts, cles inconnues refusees (V8-V9) | feature | |
| tests/integration/config/critical/ | integration | config | Refus multi-adaptateur (V4) et config.example.yaml valide | feature | critical |
| tests/integration/cli/btmuxd-smoke/ | integration | cli | btmuxd --version | feature | smoke |
| tests/integration/cli/btmuxd/ | integration | cli | btmuxd --config / --check-config (codes 0/2) | feature | |
| tests/integration/cli/btmuxctl/ | integration | cli | Stub btmuxctl (code 1) | feature | |
| tests/procedures/packaging/deb-deploy/ | procedure | packaging | Build .deb, unite systemd, deploy.sh qualif, smoke | feature | critical |
| tests/procedures/install/pi-qualif/ | procedure | packaging | Provisionnement du Pi de qualification | feature | |
| tests/procedures/spikes/05-exposure/ | procedure | bluez | Spike #5 : exposition casque generique en mono-adaptateur (BT interne, provisoire) | feature | hardware |
| tests/procedures/spikes/07-routing/ | procedure | pipewire | Spike #7 : routage PipeWire mono-adaptateur (BT interne / UB500) | feature | hardware |
| tests/procedures/spikes/06-hfp-dual-role/ | procedure | bluez | Spike #6 : double role HFP HF+AG (BT interne / UB500) | feature | hardware |
