# Memoire projet — Blue-Multiplex

> Source de verite unique au demarrage d'une session (/start-session). Mise a jour par /end-session.

## Etat courant

- **Version** : 0.1.0.3 (`pyproject.toml`) — déployée sur QUALIF, jamais publiée (aucun tag, aucun `.deb`, aucune PROD)
- **Branche** : `milestone/v0.1.0` (tête `8fedac1` au moment de la clôture ; historique réécrit 3 fois le 2026-10-23,
  les clones doivent se réaligner sur `origin/milestone/v0.1.0`). Merge sur `main` à faire par `deployer`.
- **Travail en cours** : **v0.1.0 clôturée le 2026-10-23 sans release** (socle LOT-1 + spikes #5 et #7 provisoires).
  Checklist de clôture : `_work/reports/planner-20261022-094005.md` § « Révision 2026-10-23 15:05 ».
- **Milestones GitHub** :
  - `v0.1.0 — Phase 0 : exploration technique (mono-adaptateur)` : clôturé sans release ; #1 à #5 et #7 traités, #6 reporté
  - `v0.2.0 — Exploration technique bi-adaptateur (2 × UB500)` : préparation UB500 (#17), campagne T3.2b (#6, #7 revalidés),
    Web UI appairages ; issues `PLANNING` jusqu'au GATE 2 du plan v0.2.0
  - `v0.3.0 — Daemon btmuxd : appairage, routage, API` : #16 et issues daemon créées après #11
- **Issues actives** : aucune en cours sur v0.1.0
- **Prochaine étape** : ouverture de `milestone/v0.2.0` depuis `main` (`deployer`, `pyproject.toml` → `0.2.0.0` + `uv lock`,
  patch contrats V4 `_work/tmp/contracts-v4-bi-adaptateur.patch`, `CHANGELOG [0.2.0]`), puis `/feature` plan v0.2.0 (LOT-1 #18 #14 #17)

## Decisions techniques

- 2026-10-13 : ~~v0.1.0 se limite a un seul adaptateur Bluetooth~~ — **révoquée le 2026-10-23** : la cible est le bi-adaptateur
  (2 × TP-Link UB500, RTL8761BU) ; le mono-adaptateur ne sert plus que de phase d'exploration close.
- 2026-10-23 (14:24, décision utilisateur) : **arrêt de tout développement radio sur le Bluetooth interne du Pi 3**. Les spikes
  #5 et #7 restent provisoires ; tout ce qui est « réel ↔ réel » attend la revalidation avec les UB500 (T3.2b).
- 2026-10-23 (15:03, décision utilisateur) : **v0.1.0 clôturée sans release** ; issues ouvertes → v0.2.0 ; v0.3.0 = daemon.
- 2026-10-23 : 2 × TP-Link UB500 commandés ; à revalider à réception.
- 2026-10-23 (spike #5) : classe réelle annoncée **0x006C0404** avec les quatre rôles (et non 0x240404) ; Windows et le téléphone
  classent quand même btmux en casque. Pistes d'évolution : rôles restreints par adaptateur en v0.2.0.
- 2026-10-23 (spike #7) : routage par liens PipeWire = `pw-dump -m` (événements) + session `pw-cli` persistante ; les liens
  meurent avec la session (btmuxd doit la surveiller et reconstruire les liens) ; Lua WirePlumber et API native non retenus
  pour la v0.3.0. Garde-fou UART (`watch_uart.sh`) : arrêt au premier `tx timeout`.
- 2026-10-23 : **historique de `milestone/v0.1.0` purgé** (données tierces déplacées hors dépôt) ; preuves de spikes masquées
  par `spikes/common/mask_evidence.py` avant tout commit sous `docs/spikes/`.
- Alias `btmux` non persistant après reboot (`btmgmt name`) : correctif `bluetoothctl system-alias` ou `Name=` dans `main.conf`
  prévu en v0.2.0 (#18).
- Label GitHub `spike` cree : exploration technique, livrable = rapport `docs/spikes/NN-<sujet>.md` + decision, code jetable sous `spikes/` (hors `src/`, hors couverture).
- Schema config `adapters` en liste `{mac, name, roles}` (une entree en v0.1.0, deux en v0.2.0, contrat V4 à lever) — diverge du cadrage §4.6, à aligner en #11.
- Daemon fonctionnel, API HTTP/CLI, MQTT, GPIO, Web UI : hors v0.1.0 ; daemon en v0.3.0, MQTT/GPIO en v0.4.0.
- Les spikes radio exigent des etapes manuelles utilisateur (appairages, appels) : prevoir une procedure manuelle en `_work/handoff/` a chaque ordre DEV de spike.

## Points de contexte pour la prochaine session

- `CLAUDE.md` § Contexte mentionne encore « mono-adaptateur v0.1.0 » : à corriger (`/init-project` ou `doc-updater`).
- Les teammates signalent que `TEAMMATES_PROTOCOL.md` et les `<agent>.md` compagnons n'existent pas (seuls les `.template.md`) et que l'adresse `main` est refusee par SendMessage (ils repondent a `team-lead`) — sans impact.
- Les branches `milestone/*` peuvent être réécrites (purges) : toujours `git fetch` et vérifier la tête avant d'agir.

## Regles critiques

- Aucun logiciel ni configuration cote sources (PC pro verrouille) — le Pi doit etre un casque Bluetooth generique.
- Les adaptateurs sont identifies par adresse MAC, jamais par hci0/hci1.
- Tests `hardware` (BlueZ/PipeWire reels) : sur le Pi de qualif uniquement, jamais en CI.
- Preuves de spikes : jamais commitées brutes ; passent par `mask_evidence.py --check` (code 0) avant `docs/spikes/`.

## Corrections de comportement

(aucune pour le moment)
