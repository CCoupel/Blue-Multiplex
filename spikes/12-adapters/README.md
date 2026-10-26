# spikes/12-adapters — identité des adaptateurs par MAC (#12)

> Décision D5 (GATE 2 LOT-3) : **pas de script jetable dédié** — le livrable du critère « MAC → hci, nom/classe par adaptateur sans `main.conf` global »
> est le mécanisme de production, déjà validé en #23 (débranchement/rebranchement, permutation logique des rôles) :
>
> - `scripts/btmux-adapters.sh` (installé en `/usr/lib/btmux/btmux-adapters.sh`) : retrouve `hciN` par la MAC, fixe alias et classe selon le rôle
>   (`btmgmt -i N`), ferme appairage/découverte ; `--dry-run` affiche le plan (`MAC -> hciN`), `--only <MAC>` ne traite qu'un contrôleur ;
> - unités `btmux-adapters(.path/-identity).service` (démarrage, changement de rôles, hotplug) ;
> - `spikes/common/resolve_adapter.py --role sources|headsets [--index]` : MAC d'un rôle → chemin/index (outillage de séance).
>
> Reste à jouer en S1 (hors #23) : permutation **physique** des deux dongles + reboot, vue téléphone (scan), comparaison SDP par contrôleur.
> Commandes de capture : `spikes/t32b/roles_report.sh`, `bluetoothctl show`, `btmon` (voir `spikes/t32b/README.md`). Rapport : `docs/spikes/12-adapters.md`.
