# spikes/13-roles — restriction des rôles Bluetooth par contrôleur (#13)

> **Provisoire — investigation du 2026-10-26 sur pi-qualif (Pi 4, 2 × UB500, WirePlumber 0.5.13, PipeWire 1.6.2, BlueZ 5.85), hors séance,
> sans modifier la configuration ni redémarrer WirePlumber.** À confirmer en S1 (rapport `docs/spikes/13-roles.md`).

## Constats (D-2)

1. **Annonce identique sur les deux contrôleurs.** `Adapter1.UUIDs` de hci0 (`headsets`) et de hci1 (`sources`) sont **identiques** :
   A2DP source `110a` **et** sink `110b`, HFP AG `111f` **et** HF `111e`, AVRCP `110c`/`110e`, PnP `1200`, GATT/GAP/DIS. Les deux classes portent les bits
   *Rendering, Capturing, Audio, Telephony* (`0x6c0404` / `0x6c010c`). L'enregistrement des endpoints A2DP (`Media1`, présent sur chaque
   adaptateur) et du profil HFP (`ProfileManager1`, global au démon BlueZ) est fait par WirePlumber/SPA pour **tous** les adaptateurs : aucun réglage
   WirePlumber ne retire un profil de l'annonce d'**un seul** contrôleur.
2. **Une propriété d'adaptateur est matchable, indirectement.** Les règles `monitor.bluez.rules` (`scripts/monitors/bluez.lua`, `match_rules_update_properties`)
   s'appliquent aux propriétés de chaque **appareil distant** à sa création. Ces propriétés contiennent `api.bluez5.path = /org/bluez/hciN/dev_<MAC>` :
   un motif `~/org/bluez/hciN/dev_*` (motif **GLib/glob**, `g_pattern_match`, pas une regex) cible « les appareils vus par le contrôleur hciN ».
   `bluez5.roles` posé par cette règle restreint les profils **utilisés par le Pi** avec cet appareil (nœuds A2DP/HFP créés), pas l'annonce SDP.
3. **Limites** : (a) `hciN` n'est pas stable (hotplug, reboot) → le fragment doit être régénéré depuis les rôles/MAC (`gen_rules.py`) ; (b) les règles ne sont
   lues qu'au démarrage de WirePlumber (restart = coupure des flux BT, règle S1 : contrôleurs sans appareil connecté) ; (c) l'effet fonctionnel n'est pas
   encore prouvé avec un appareil (à constater en S1 : `pw-dump` → propriétés `bluez5.roles` de la carte, profils proposés).
4. **Fallback prototypé** (`profile_guard.py`) : le daemon connaît le contrôleur d'appairage de chaque appareil ; il coupe les profils distants
   incohérents avec le rôle (`Device1.DisconnectProfile`). Essai à vide : sur `headsets`, le casque annonce `110a` (A2DP source) — le cas existe en réel.
   Choix daemon vs règle WirePlumber : rapport #13 (issue v0.3.0 pour l'implémentation).
5. **Téléphonie native (#6, inventaire à vide)** : pas d'oFono ; `libspa-bluez5` embarque un service D-Bus de téléphonie `org.pipewire.Telephony`
   (`AudioGateway1` : `Dial`, `HangupAll`, `SendTones`, volumes ; `Call1` : `Answer`, `Hangup` ; interfaces compatibles `org.ofono.VoiceCallManager/VoiceCall`),
   **non actif** par défaut (absent des bus session/système ; propriété `bluez5.telephony-dbus-service`). Il couvre le rôle **AG** (Pi → casque), pas le rôle
   HF (Pi → PC/téléphone) : à confirmer en S2 (activation = restart WirePlumber, contrôleurs sans appareil connecté).

## Fichiers

| Fichier | Rôle |
|---------|------|
| `gen_rules.py` | Génère le fragment `monitor.bluez.rules` par contrôleur (`api.bluez5.path`) depuis `btmuxctl controllers`. Aucune écriture hors `--out`. |
| `profile_guard.py` | Fallback : liste (défaut) ou coupe (`--apply`) les profils distants incohérents avec le rôle du contrôleur. |
| `../t32b/roles_report.sh` | UUID annoncés **par contrôleur** (`Adapter1.UUIDs`), classes, profils des cartes PipeWire. |
| `../../config/wireplumber/roles.conf` | Gabarit global (inchangé : aucune règle effective prouvée à ce stade). |
