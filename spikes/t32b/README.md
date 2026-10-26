# spikes/t32b — campagne bi-adaptateur (2 × UB500)

> **Provisoire — à valider avec les dongles UB500 (T3.2b).** Préparé sans matériel (essais « à blanc » : virtuel, simulations, `--dry-run`).
> Les dongles ne sont pas encore reçus. Outils partagés : `spikes/common/` ; routage : `spikes/07-routing/` ; identité persistante :
> `scripts/btmux-adapters.sh`.

Topologie cible : `hci-src` (rôle `sources`, vu comme un casque par le PC et le téléphone) et `hci-hp` (rôle `headsets`, vu comme une source
par le casque), identifiés par MAC (`/etc/btmux/config.yaml`), jamais par `hciN`. Les deux dongles partagent un hub USB 2.0 (limite à noter).

## Coexistence avec `btmuxd` résident (LOT-3)

- `btmuxd` est le **seul agent BlueZ** : `session.sh` ne lance pas `agent.py` quand le daemon est actif (refus si `BTMUX_SPIKE_AGENT=1`).
  Fenêtres d'appairage : `btmuxctl pairing open sources|headsets [s]` / `pairing close` (`session.sh s1 --window 300` ouvre `sources`).
- `link_guard.py` reste le seul à `Blocked`-er un appareil (le daemon ne bloque jamais) ; il débloque à l'arrêt ce qu'il a bloqué.
- `preflight.sh` : `btmuxd` actif, 2 contrôleurs présents via `btmuxctl controllers`, sous-tension par `vcgencmd get_throttled` ou, à défaut,
  hwmon `rpi_volt` ; un lien ACL déjà actif (appareil en usage) est signalé (AVERT), à noter dans la séance.
- Wi-Fi conservé pendant la campagne (décision D2) : consigné dans les rapports.

## Fichiers

| Fichier | Rôle |
|---------|------|
| `preflight.sh` | Contrôles avant séance (hostname, 2 UB500, 0 UART, `disable-bt`, ACL existants, MAC de la config, `btmuxd` + API, sous-tension, Wi-Fi/Ethernet). |
| `session.sh s1\|s2 [--dry-run]` / `stop` | Orchestration : préflight, `watch_hci.sh` (par contrôleur), `link_guard.py`, `agent.py` (seulement sans `btmuxd` ; sinon fenêtre via `btmuxctl`), affichage des étapes. |
| `roles_report.sh` | Profils/UUIDs par contrôleur et par carte PipeWire (#13). |
| `telephony_inventory.sh` | Inventaire de l'API téléphonie BlueZ/PipeWire (#6). |
| `sco_capacity.sh` | Maximum de liens SCO/eSCO simultanés par contrôleur (#6). |
| `voice_links.py` | Liens de voix PC ↔ casque (HF sur `hci-src`, AG sur `hci-hp`) via `@hciN:…` (#6). |
| `profile_watch.py` | Chronomètre les bascules A2DP ↔ HFP d'un appareil (cible A2DP → HFP < 2 s) (#6/#8). |
| `impulse_track.py`, `analyze_latency.py` | Protocole de latence double saut (#8) : piste de clics + analyse d'un enregistrement stéréo. |
| `xrun_log.py` | Dropouts/xruns sur 30 min (colonne ERR de `pw-top`) (#8). |
| `../07-routing/router.py` | Bascule par adaptateur : `--sink @hci1:Audio/Sink --a @hci0:Stream/Output/Audio …`. |

## S1 (~1 h 15) — identité, rôles, exposition, routage (#12, #13, #5 ét. 3–6, #7 critère 1)

1. `session.sh s1` ; vérifier le préflight. Ouvrir la fenêtre d'appairage : `btmuxctl pairing open sources 300` (fermer : `btmuxctl pairing close`).
2. **Identité (#12)** : le PC et le téléphone ne voient que `btmux` ; le casque ne voit que `btmux-src` ; permuter les MAC des rôles dans la config,
   `btmux-adapters.sh`, reboot : les rôles suivent les MAC.
3. **Rôles (#13)** : `roles_report.sh` ; ajuster `config/wireplumber/roles.conf` si un appareil se comporte mal.
4. **Exposition (#5 bi)** : PC + téléphone sur `hci-src`, casque sur `hci-hp`, audio 5 min, reboot (reconnexion initiée par le Pi).
5. **Routage (#7 critère 1)** : bascule réel ↔ réel ×10 (`router.py --sink @hci1:Audio/Sink --a @hci0:Stream/Output/Audio:<PC> --b @hci0:Stream/Output/Audio:<tél>`), p95 < 1 s, 10 min, FL/FR, restart WirePlumber BT connecté.

## S2 (~1 h) — voix (#6) et latence (#8)

1. `session.sh s2` ; `telephony_inventory.sh` ; `sco_capacity.sh 600` pendant les appels.
2. **#6** : `voice_links.py --pc-in @hci0:Stream/Output/Audio --hs-out @hci1:Audio/Sink --hs-in @hci1:Audio/Source --pc-out @hci0:Stream/Input/Audio` ;
   appel Teams, voix dans les deux sens, 10 min ; 5 bascules A2DP ↔ HFP déclenchées par Windows (ouverture/fermeture du micro) avec
   `profile_watch.py --match <MAC du PC avec _>` ; codec de chaque côté (mSBC ou CVSD) ; décision backend (natif / oFono / hybride).
3. **#8 protocole de latence double saut** : la source joue `impulse_track.py --out clicks.wav` ; un enregistreur externe stéréo capte le canal 0 =
   sortie directe de la source, canal 1 = sortie du casque (≥ 10 clics par configuration) ; `analyze_latency.py rec.wav` donne n/min/médiane/p95/max
   (cible A2DP < 300 ms). Faire varier `quantum` / `bluez5.a2dp.*` et noter les réglages.
4. **Dropouts 30 min** : `xrun_log.py --minutes 30` avec 2 sources connectées + casque actif, puis avec un appel HFP.

## Sécurité de séance

`session.sh` lance `watch_hci.sh` (un garde-fou par contrôleur : erreur dure ou rafale de trames → arrêt du routeur et déconnexion des appareils de ce
contrôleur seul) et `link_guard.py` (plafond de liens par adaptateur, `block` de l'appareil en trop). Le restart de PipeWire/WirePlumber avec des
appareils BT connectés n'est autorisé qu'en S1 (#7), après les mesures, avec les UB500 uniquement.
