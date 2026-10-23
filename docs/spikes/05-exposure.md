# Spike #5 — Exposition mono-adaptateur : « casque générique » pour les sources

> **Provisoire — à revalider avec dongle RTL8761B.** Tous les résultats ci-dessous ont été obtenus avec le
> **Bluetooth interne du Raspberry Pi 3 Model B** (UART, antenne partagée avec le Wi-Fi, Bluetooth 4.2), faute de
> dongle. Aucune décision d'architecture (v0.2.0) ne doit s'appuyer sur ce verdict seul.

Issue : #5 · Séance : 2026-10-23, 09:08–09:22 UTC (11:08–11:22 heure de Paris ; le Pi est en UTC) ·
Outillage : `spikes/05-exposure/` · Procédure QA : `tests/procedures/spikes/05-exposure/exposition-mono-adaptateur.md`.
Les adresses MAC des appareils de l'utilisateur sont masquées (`xx`) dans ce document et ses annexes.

## Objectif

Avec **un seul adaptateur**, BlueZ/PipeWire exposent sur le même `hci` les quatre rôles (A2DP sink + source, HFP HF + AG).
Vérifier que la contrainte non négociable tient : un PC pro Windows (sans rien installer, appairage standard) voit un
**casque Bluetooth générique**, et un casque peut s'appairer au même adaptateur comme à un téléphone.

## Matériel / versions

| Élément | Valeur |
|---------|--------|
| Pi | Raspberry Pi 3 Model B Rev 1.2, 894 Mo de RAM, `pi-qualif`, Wi-Fi actif (SSH), `eth0` sans câble |
| OS / noyau | Ubuntu 26.04.1 LTS (`resolute`), aarch64, noyau 7.0.0-1020-raspi |
| Contrôleur | `hci0`, UART, Broadcom BCM43430A1 (firmware 001.002.009 build 1042), **MAC B8:27:EB:1A:2E:D6**, HCI/LMP 4.2 |
| BlueZ / PipeWire / WirePlumber | 5.85-4ubuntu0.4 / 1.6.2-1ubuntu1.2 / 0.5.13-1ubuntu1.1 (cf. `docs/install-pi.md` §9) |
| Codecs Bluetooth disponibles | SBC, aptX, FastStream, G.722, LDAC, LC3, Opus, HFP CVSD/mSBC/LC3 — **pas d'AAC** |
| PC pro | « MSI », Windows 11, adaptateur Intel (84:7B:57:xx:xx:xx) |
| Téléphone | Samsung Galaxy S24 Ultra (BC:93:07:xx:xx:xx) |
| Casque | Bose, annoncé « Cache-oreilles » / « LE-Cache-oreilles » (28:11:A5:xx:xx:xx), Modalias 0x009E:0x4020 |
| Configuration | `wireplumber.conf.d/51-btmux-no-seat.conf` (prérequis headless, cf. Résultats §0), `bt-agent -c NoInputNoOutput` pendant la séance |

## Protocole

Pilotage par SSH (l'agent exécute côté Pi, l'utilisateur manipule). Détail dans la procédure QA ci-dessus ; résumé :

0. Identité (`set_identity.sh` : nom `btmux`, classe, fenêtre d'appairage 600 s), `pair_watch.py` (journal JSON Lines des
   `Device1`/`MediaTransport1`), `dump_sdp.sh --btmon` (capture passive).
1. Appairage standard depuis Windows 11 ; 2. lecture audio PC → Pi (A2DP sink) ; 3. appairage du téléphone ;
4. casque en appairage, `pair`/`trust`/`connect` lancés **depuis le Pi** pendant qu'une source est connectée ;
5. lecture Pi → casque (tonalité de 22 s) ; 6. redémarrage du Pi et vérification (`reboot_check.sh`) ; 7. clôture.

## Résultats

### Par étape

| Étape | Résultat | Preuve |
|-------|----------|--------|
| 0 — Outillage | OK. Résolution MAC → `hci0` par D-Bus OK ; `btmgmt name btmux` + `class 4 4` appliqués ; **classe annoncée 0x006C0404** (pas 0x240404) ; `sdptool browse local` inutilisable (R6, « Failed to connect to SDP server ») → repli `bluetoothctl show` + `btmon`. **Prérequis découvert** : sans « seat » logind, WirePlumber n'active pas le moniteur Bluetooth et BlueZ n'annonce que AVRCP (aucun profil audio) ; corrigé par `monitor.bluez.seat-monitoring = disabled` (cf. `docs/install-pi.md` §5 bis). | `show-20261022-145623.txt` (avant), `show-20261023-090731.txt` (après) |
| 1 — Windows | **Appairage standard abouti**, Windows affiche « btmux — Microphone, audio connectés » avec icône casque. Deux échecs préalables, tous deux côté Pi : (a) aucun agent d'autorisation → `Authentication attempt without agent`, A2DP et Hands-Free rejetés, Windows : « Réessayez de connecter votre appareil » (10:30–10:35) ; (b) après `trust` + agent, clés désynchronisées → HCI `Authentication Failure (0x05)` ×11 (« Nous n'avons pas pu assurer la connexion », 10:38–10:39) ; réglé par `bluetoothctl remove` côté Pi puis nouvel ajout côté Windows (10:40). | `journal-extraits.txt`, `btmon-extraits.txt`, `pair.jsonl`, `agent.log` |
| 2 — Audio PC → Pi | A2DP établi : Windows propose SBC/aptX/AAC, **aptX retenu** (le Pi n'a pas d'AAC). Le nœud PipeWire `bluez_input` n'apparaît qu'après une connexion initiée par le Pi ; ensuite **Windows bascule en HFP (mSBC, mono, 16 kHz)** et y reste (cf. Constats). Rien d'audible côté Pi (sink = Dummy, pas de sortie). | `pair.jsonl` (MediaTransport1), `btmon-extraits.txt` |
| 3 — Téléphone | Appairage du Galaxy S24 Ultra du premier coup (10:50:05–10:50:13), vu côté téléphone avec « Appels » et « Audio ». A2DP **aptX stéréo 44,1 kHz** actif à 10:52:39 ; un décrochage HFP de ~3 s à 10:51:12. Deux sources en simultané pendant ~3 min. | `pair.jsonl`, `agent.log` |
| 4 — Casque | `pair` + `trust` + `connect` **initiés par le Pi** (lien ACL sortant, Pi central) : OK en moins d'une minute (scan compris), **pendant que le PC est connecté**. Le casque annonce « connecté à btmux ». A2DP source du Pi vers le casque (SBC), carte PipeWire avec profils `a2dp-sink` (= Pi émetteur), `a2dp-sink-sbc_xq`, `headset-head-unit(-cvsd)` ; nœud `bluez_output` présent. HFP AG vers le casque non testé. | `pair.jsonl` |
| 5 — Pi → casque | Tonalité 22 s (puis seconde lecture de mesure) : **entendue par l'utilisateur, « propre, sans coupure »**. `pw-top` : ERR 0, BUSY 0,1–0,3 ms, sink SBC 48 kHz S16LE quantum 2048, transport A2DP `active`, PC resté connecté. | mesures de séance (cf. Mesures) |
| 6 — Reboot | **Appairages et Trusted conservés** (3 appareils), `hci0` revenu, MAC identique. **Aucune reconnexion automatique** : ni le PC ni le téléphone n'ont rappelé le Pi en 120 s (ni jusqu'à ~290 s) ; reconnexion obtenue seulement par `bluetoothctl connect` depuis le Pi. | `reboot-20261023-090735.txt` |
| 7 — Clôture | Fenêtre fermée, outils arrêtés, appairages laissés en place. | — |

### Par critère d'acceptation de #5

| Critère | Statut | Détail |
|---------|--------|--------|
| Script jetable `spikes/05-exposure/` : MAC → index hci, `name`/`class` via `btmgmt`, relevé SDP | **OK** (SDP : repli) | `sdptool` inutilisable (R6) ; UUIDs via `bluetoothctl show` et capture `btmon` ; dossier `spikes/05-exposure/` |
| PC Windows **et** téléphone : apparaît comme casque audio, appairage standard, A2DP + HFP, captures consignées | **PARTIEL** | Appairage OK sur les deux, A2DP + HFP établis côté Windows (A2DP aptX puis HFP mSBC) et A2DP aptX côté téléphone (« Appels » + « Audio » vus). Captures disponibles en texte uniquement (« Paramètres > Son », erreurs et succès d'ajout, ci-dessous) ; **« Périphériques et imprimantes > Services » et l'écran Bluetooth du téléphone non capturés** |
| Casque appairé, connexion initiée par le Pi, pendant qu'une source est connectée | **OK** | PC connecté pendant l'appairage et la lecture (étapes 4–5) ; avec PC + téléphone + casque tous connectés : **NON TESTÉ** |
| Appairages conservés après redémarrage ; reconnexion automatique observée | **OK / KO** | Appairages et Trusted conservés : OK. Reconnexion automatique : **KO** (non observée) |
| Rapport `docs/spikes/05-exposure.md` avec verdict et recommandations | **OK** | Ce document |

### Ce que Windows affiche (captures en texte, images non archivées)

- Ajout de l'appareil, 10:39 : « btmux — Nous n'avons pas pu assurer la connexion. Réessayez. » (icône casque).
- Ajout de l'appareil, 10:40 : « btmux — Microphone, audio connectés » (icône casque).
- « Paramètres > Son », 11:22 : Sortie = « Headphones — btmux — Appareil par défaut » (autres sorties : haut-parleurs Realtek,
  LC34G55T NVIDIA), volume 100, audio mono désactivé ; Entrée = « Headset — btmux — Appareil par défaut » (autre entrée :
  Microphone Array Intel), volume 100. Windows expose donc btmux comme **un seul** périphérique « Headphones » en sortie et
  « Headset » en entrée (pas de double entrée stéréo / mains libres dans cette vue).
- Téléphone : btmux apparaît avec les profils « Appels » et « Audio ».

## Mesures

| Mesure | Valeur | Source |
|--------|--------|--------|
| PC → Pi, A2DP | codec aptX (vendeur 0x0001), configuration `4f000000010022`, `Delay` rapporté 200 puis 400–600 (unités BlueZ de 1/10 ms, soit 20–60 ms côté sink — **pas** une latence bout en bout) | `pair.jsonl` |
| PC → Pi, HFP | nœud `bluez_input` mSBC, S16LE **mono 16 kHz**, quantum 512 ; ERR 0 | pw-top 10:48 |
| Téléphone → Pi, A2DP | aptX, **S24LE stéréo 44,1 kHz**, quantum 512 ; transport pending → active 10:52:39 | pw-dump, pw-top |
| Deux flux simultanés (10:53) | BUSY 0,18 ms (PC) et 0,44 ms (téléphone), **ERR = 4 sur chaque nœud** (stable pendant la fenêtre de 10 s, apparus entre 10:48 et 10:53) | pw-top |
| Pi → casque, A2DP | SBC 48 kHz S16LE stéréo, quantum 2048, ERR 0, transport `active` | pw-top, pw-dump |
| Erreurs UART HCI (boot précédent) | `Frame reassembly failed -84/-90` : **136 à 10:44 (une seule source, PC)** puis **2935 à 10:53 (deux flux)** ; total 3071 + 35 `tx timeout` ; **premiers `command tx timeout` / `Opcode failed -110` à 10:56:43** ; contrôleur muet jusqu'au reboot | `journal-extraits.txt` |
| Erreurs UART (boot courant) | 11 erreurs à la reconnexion de deux sources par le Pi (11:11:30–11:12:35, `killing stalled connection` ×2) ; **0 erreur de 11:13:53 à 11:22:21** (PC seul puis PC + casque, un flux à la fois) ; 17 erreurs à 11:22:41, à la clôture (cause non élucidée) | `journal-extraits.txt` |
| Compteurs HCI avant le plantage | `sco: 93861` paquets TX : l'audio SCO circule **via l'UART HCI** (routage HCI) | `hciconfig` en séance |

## Constats

1. **Un appairage standard suffit côté Windows** : aucun logiciel, aucun pilote ; btmux est présenté comme « Headphones /
   Headset » avec une icône casque, malgré la classe 0x006C0404.
2. **La classe réelle est 0x006C0404**, pas 0x240404 : avec les quatre rôles, les bits *Capturing* (0x080000) et *Telephony*
   (0x400000) s'ajoutent à *Audio* (0x200000) et *Rendering* (0x040000) à cause de HFP (AG et HF). `btmgmt class` ne fixe que
   majeur/mineur (4/4 = casque) ; le noyau recalcule les bits de service depuis les UUIDs enregistrés. Cela n'a pas empêché
   Windows ni le téléphone de classer btmux en casque.
3. **Windows reste en HFP dès que le micro btmux est l'entrée par défaut** : le flux mesuré était en mSBC mono 16 kHz alors
   que A2DP aptX stéréo était établi. Ce n'est pas un défaut de BlueZ mais un choix de profil de Windows (risque R4 réalisé
   en partie) ; à traiter par la politique de profils de btmuxd ou par la séparation des rôles entre deux adaptateurs.
4. **L'autorisation des profils exige un agent** : sans agent, BlueZ rejette les connexions A2DP/HFP initiées par la source.
5. **Un bond désynchronisé empêche toute connexion** (HCI 0x05) : il faut oublier l'appareil des deux côtés.
6. **Les sources ne se reconnectent pas seules après un redémarrage** ; une connexion initiée par le Pi fonctionne avec
   des appareils Paired + Trusted.
7. **Le contrôleur interne du Pi 3 n'est pas fiable sous charge** (cf. Limites).

## Limites

- **Bluetooth interne du Pi 3 (provisoire)** : HCI sur UART ; **l'audio SCO passe par l'UART** (SCO routé via HCI), antenne
  partagée avec le Wi-Fi actif (Ethernet non branché), Bluetooth 4.2. Des erreurs de trames UART sont apparues dès une seule
  source (136 en une minute) et se sont aggravées à deux flux jusqu'à un contrôleur muet nécessitant un redémarrage ; elles sont
  revenues dès la reconnexion simultanée de deux sources, sans audio. Avec un seul flux à la fois (PC + casque), 0 erreur sur
  ~8 min.
- Un seul contrôleur : les mêmes rôles (casque pour les sources, source pour les casques) sont exposés sur `hci0`.
- **Non testés** : le vrai multiplexage (une source jouant vers le casque en même temps, c'est l'objet de la suite), HFP AG vers
  le casque et micro de retour, deux casques, PC + téléphone + casque simultanés, qualité de la voix (SCO), latence mesurée de
  bout en bout, la variante à rôles restreints (`50-btmux-roles.conf`, R4), l'effet d'un filtrage SDP.
- Captures Windows « Périphériques et imprimantes > Services » et écran Bluetooth du téléphone non réalisées ; captures
  fournies en texte seulement.
- Windows 11 uniquement (une version), un seul téléphone (Android), un seul casque (Bose) : pas de généralisation.

## Décision / Verdict

**Casque générique en mono-adaptateur : OUI AVEC RÉSERVES — provisoire, à revalider avec dongle RTL8761B.**

Pour : le PC pro et le téléphone s'appairent par l'interface standard, sans rien installer, et voient un casque ;
A2DP (aptX) et HFP (mSBC) s'établissent ; le Pi appaire, fait confiance et connecte un casque **de lui-même** pendant
qu'une source est connectée, et le son sortant est entendu « propre, sans coupure » ; les appairages survivent au redémarrage.

Réserves : le contrôleur interne s'effondre dès que deux sources sont actives ; les sources ne se reconnectent pas seules
(la reconnexion doit être pilotée par le Pi) ; Windows reste en HFP 16 kHz mono tant que le micro btmux est l'entrée par
défaut ; le critère « reconnexion automatique » est KO, le critère « captures Windows » est partiel, et le multiplexage
réel (une source vers le casque) n'a pas été éprouvé. Aucune réserve ne remet en cause la contrainte non négociable côté
source (rien à installer), mais elles pèsent sur l'expérience.

### Recommandations (classe, nom, SDP, `bluez5.roles`)

- **Nom** : `btmux` (Alias) fonctionne ; garder un nom court et sans accents.
- **Classe** : ne pas forcer 0x240404. Garder majeur 4 / mineur 4 (casque) et laisser BlueZ composer les bits de service ;
  la classe 0x006C0404 a été acceptée par Windows et le téléphone.
- **Filtrage des enregistrements SDP** : pas nécessaire pour l'appairage (réussi sans filtrage). Le problème observé (HFP
  au lieu d'A2DP) tient au micro par défaut de Windows, pas aux enregistrements SDP. À tester seulement si une source se
  comporte mal : `bluez5.roles = [ a2dp_sink hfp_hf ]` (fichier prêt, non activé).
- **Structure** : en bi-adaptateur (v0.2.0), exposer **seulement les rôles « casque » sur l'adaptateur côté sources** (A2DP sink
  + HFP HF) et les rôles « source » sur l'adaptateur côté casques (A2DP source + HFP AG) supprime le sujet du filtrage à la
  racine, et sépare la charge UART/USB.

## À revalider en bi-adaptateur (dongle RTL8761B)

- Stabilité avec deux sources actives, puis source + casque, **sans UART** (USB) ; erreurs de trames et contrôleur muet
  doivent disparaître.
- Nombre de liens SCO simultanés et route SCO (HCI vs PCM), qualité de la voix HFP (R1).
- Reconnexion automatique après redémarrage (comportement des sources, éventuelle reconnexion pilotée par le Pi).
- Classe, nom et rôles restreints par adaptateur ; comportement de Windows avec un adaptateur ne portant que les rôles casque.
- Multiplexage réel (source → casque pendant qu'une autre source est connectée), latence A2DP mesurée de bout en bout
  (objectif < 300 ms) et bascule < 1 s.
- Captures Windows « Services » et téléphone ; autres versions de Windows, iOS, autres casques (Bose seul testé).
- Effet du Wi-Fi/Ethernet : refaire avec l'Ethernet branché et `disable-wifi`.

## Points pour btmuxd

1. Enregistrer un **agent d'autorisation/appairage** (`NoInputNoOutput`, auto-accept) et poser `Trusted` à l'appairage.
2. Gérer les **bonds périmés** : sur `Authentication Failure (0x05)`, supprimer l'appareil (`Adapter1.RemoveDevice`) et rouvrir
   la fenêtre d'appairage.
3. **Reconnexion initiée par le Pi** pour les appareils connus (les sources ne rappellent pas) ; appairage et connexion du
   casque toujours initiés par le Pi.
4. Fenêtre d'appairage : `DiscoverableTimeout` côté bluetoothd (`btmgmt discov` ne suffit pas) ; identité = Alias `btmux` + classe.
5. WirePlumber headless : `monitor.bluez.seat-monitoring = disabled`. Nœuds : `bluez_input.<mac>` (source → Pi),
   `bluez_output.<mac>` (Pi → casque), carte `bluez_card.<mac>` ; le profil A2DP « sink » n'est pas toujours énuméré avant
   une connexion initiée par le Pi.
6. Détecter un contrôleur muet (`command tx timeout`, `Opcode … failed: -110`) : alerte et procédure de reset (power cycle
   insuffisant sur le Bluetooth interne, redémarrage nécessaire).
7. Surveiller la bascule A2DP → HFP (mSBC 16 kHz) côté Windows et définir une politique de profils.

## Annexes

Fichiers versionnés dans `docs/spikes/05-exposure/` (MAC des appareils de l'utilisateur et nom du téléphone masqués) :

| Fichier | Contenu |
|---------|---------|
| `show-20261022-145623.txt` | `bluetoothctl show` **avant** le correctif headless (sans profils audio) |
| `show-20261023-090731.txt` | `bluetoothctl show` après (Alias btmux, classe 0x006C0404, UUIDs Audio Sink/Source, HFP HF/AG) |
| `pair.jsonl` | journal `pair_watch` : Device1 et MediaTransport1 de la séance |
| `agent.log` | autorisations demandées à `bt-agent` (A2DP 110d, HFP 111e, AVRCP 110e) |
| `reboot-20261022-145737.txt`, `reboot-20261023-090735.txt` | `reboot_check.sh` (le second : appairages conservés, pas de reconnexion automatique) |
| `journal-extraits.txt` | erreurs HCI par minute, premiers timeouts, boot précédent et courant |
| `btmon-extraits.txt` | extraits `btmon` : `Authentication Failed` ×22, raisons de déconnexion, capacités AVDTP |

Preuves complètes, non versionnées (`_work/tmp/spike-05/`, y compris les captures `btmon-*.snoop`/`.txt` de plusieurs Mo) :
conservées localement par le teamleader.
