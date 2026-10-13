# Memoire projet — Blue-Multiplex

> Source de verite unique au demarrage d'une session (/start-session). Mise a jour par /end-session.

## Etat courant

- **Version** : 0.1.0 (aucun tag, aucun code)
- **Branche** : `main` (`milestone/v0.1.0` pas encore creee)
- **Travail en cours** : milestones et backlog crees le 2026-10-13, aucun developpement lance
- **Milestones GitHub** :
  - `v0.1.0 — Phase 0 : exploration technique (mono-adaptateur)` (milestone/1) : issues #1 a #11 (0 fermee)
  - `v0.2.0 — Double adaptateur Bluetooth` (milestone/2) : issues #12 a #15 (0 fermee)
- **Issues actives** : aucune en cours
- **Prochaine etape suggeree** : `/backlog #1` (socle : squelette Python + CI verte). Lots suggeres par le planner : LOT-1 #1 #2 #3 #4 (socle), puis spikes #5 → #6/#7 → #8 #9 #10, puis #11 (ADR)

## Decisions techniques

- 2026-10-13 : **v0.1.0 se limite a un seul adaptateur Bluetooth** (tous les roles sur le meme hci) ; le passage a deux adaptateurs `hci-src`/`hci-hp` est reporte en v0.2.0 (decision utilisateur).
- Label GitHub `spike` cree : exploration technique, livrable = rapport `docs/spikes/NN-<sujet>.md` + decision, code jetable sous `spikes/` (hors `src/`, hors couverture).
- Schema config `adapters` prevu en liste `{mac, name, roles}` (une entree en v0.1.0, extensible a deux en v0.2.0) — diverge du cadrage §4.6, a mettre a jour dans l'issue #11.
- Daemon fonctionnel, API HTTP/CLI, MQTT, GPIO, Web UI : hors v0.1.0 et v0.2.0 (v0.3.0+).
- Les spikes radio exigent des etapes manuelles utilisateur (appairages, appels) : prevoir une procedure manuelle en `_work/handoff/` a chaque ordre DEV de spike.

## Points de contexte pour la prochaine session

- Les teammates signalent que `TEAMMATES_PROTOCOL.md` et les `<agent>.md` compagnons n'existent pas (seuls les `.template.md`) et que l'adresse `main` est refusee par SendMessage (ils repondent a `team-lead`) — sans impact.
- `uv` n'est pas installe sur le poste de dev (prerequis pour l'issue #1).

## Regles critiques

- Aucun logiciel ni configuration cote sources (PC pro verrouille) — le Pi doit etre un casque Bluetooth generique.
- Les adaptateurs sont identifies par adresse MAC, jamais par hci0/hci1.
- Tests `hardware` (BlueZ/PipeWire reels) : sur le Pi de qualif uniquement, jamais en CI.

## Corrections de comportement

(aucune pour le moment)
