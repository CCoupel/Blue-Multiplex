# Memoire projet — Blue-Multiplex

> Source de verite unique au demarrage d'une session (/start-session). Mise a jour par /end-session.

## Etat courant

- **Version** : 0.2.0.1 (`pyproject.toml`) — milestone v0.2.0 en cours ; v0.1.0 (0.1.0.3) clôturée sans release, jamais publiée
- **Branche** : `milestone/v0.2.0` (LOT-1 et LOT-2 livrés, tête de code `8cf91ff`) ; `milestone/v0.1.0` close (historique réécrit
  3 fois le 2026-10-23 : les clones doivent se réaligner). `main` reçoit v0.1.0 par `deployer`.
- **Travail en cours** : **v0.2.0 LOT-1 livré** (#14 #18 #17 : config bi-adaptateur V4 max 2 / V11 / V12, packaging déterministe,
  jeton d'API, unité durcie), sans matériel. **LOT-2 validé QA** (#20 agent BlueZ, #21 API HTTP aiohttp + SSE + `btmuxctl`,
  #16 Web UI d'appairages ; sécurité GO score 82). HTTP clair sur le LAN en v0.2.0 (HTTPS = #22, v0.3.0).
  Dongles UB500 : à réceptionner (`docs/install-pi.md` §6). Maquette Web UI appairages validée GATE 2 (`docs/mockup/v0.2.0/ui/`).
- **Milestones GitHub** :
  - `v0.1.0 — Phase 0 : exploration technique (mono-adaptateur)` : clôturé sans release ; #1 à #5 et #7 traités, #6 reporté
  - `v0.2.0 — Exploration technique bi-adaptateur (2 × UB500)` : préparation UB500 (#17), campagne T3.2b (#6, #7 revalidés),
    agent BlueZ d'appairage (#20), API HTTP (#21), Web UI de suivi et gestion des appairages (#16, périmètre réduit) ;
    issues `PLANNING` jusqu'au GATE 2 du plan v0.2.0
  - `v0.3.0 — Daemon btmuxd : routage, reconnexion, politique de connexions` : issues daemon créées après #11 ;
    sans agent, API ni Web UI (déjà en v0.2.0)
- **Issues actives** : aucune en cours sur v0.1.0
- **Prochaine étape** : BUILD 0.2.0.2 + DEPLOY QUALIF (`deployer`), puis GATE 4 LOT-2 (séance Web UI avec l'utilisateur).

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
- Schema config `adapters` en liste `{mac, name, roles}` (une entree en v0.1.0, deux en v0.2.0, contrat V4 à lever) — diverge du cadrage §4.6, à aligner en #11.
- Daemon fonctionnel, routage, MQTT, GPIO : hors v0.1.0 ; daemon en v0.3.0, MQTT/GPIO en v0.4.0. Agent BlueZ (#20), API HTTP (#21) et Web UI (#16) en v0.2.0.

## Regles critiques

- Règles permanentes, conventions de spike et branches réécrites : voir `.claude/agents/context/PROJECT_CONTEXT.md`
  (« Contraintes permanentes », « Spikes ») et `CLAUDE.md` (contrainte non négociable côté sources).

## Corrections de comportement

(aucune pour le moment)
