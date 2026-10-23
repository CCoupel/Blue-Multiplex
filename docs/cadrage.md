# Blue-Multiplex — Cadrage initial (btmux)

> Document fourni par l'utilisateur lors du workshop /init-project du 2026-10-13.

## 1. Contexte et objectif

L'utilisateur possède plusieurs PC (dont un PC professionnel verrouillé, sur lequel rien ne peut être installé), plusieurs téléphones et plusieurs casques Bluetooth. Aujourd'hui, changer de source impose de déconnecter le casque d'un appareil et de le reconnecter à un autre.

**Objectif** : un Raspberry Pi joue le rôle de multiplexeur Bluetooth.

- Toutes les sources (PC, téléphones) sont appairées une seule fois au Pi, qu'elles voient comme un casque Bluetooth standard (A2DP sink + HFP Hands-Free).
- Tous les casques sont appairés une seule fois au Pi, qu'ils voient comme une source standard, c'est-à-dire un téléphone (A2DP source + HFP Audio Gateway).
- Le basculement entre sources se fait uniquement en logiciel (routage PipeWire), sans aucune reconnexion Bluetooth.
- Le flux est bidirectionnel : le micro du casque remonte vers la source active (Teams sur PC, appels sur téléphone).

### Contrainte non négociable

Aucun logiciel, pilote ou configuration ne peut être ajouté sur les sources. Le PC pro doit voir un casque Bluetooth générique, appairé via l'interface Windows standard.

### Hors périmètre (v1)

- Streaming audio réseau (ROC, RTP, Snapcast). Envisageable plus tard pour les PC perso.
- LE Audio / Auracast.
- Codecs haute définition propriétaires en entrée (LDAC/aptX côté sink). SBC/AAC en entrée suffisent ; en sortie vers les casques, utiliser le meilleur codec supporté par PipeWire.
- Mixage de plusieurs sources dans un même casque (prévoir l'architecture pour, ne pas l'implémenter).

## 2. Matériel

- Raspberry Pi 4 ou 5, alimentation officielle, Ethernet (le Wi-Fi est désactivé pour libérer la radio 2.4 GHz).
- 2 dongles USB Bluetooth 5.x bien supportés sous Linux (cible : Realtek RTL8761B, ex. TP-Link UB500), chacun sur une rallonge USB pour l'éloigner des ports USB 3.
  - `hci-src` (dongle n°1) : rôle « casque » vis-à-vis des sources.
  - `hci-hp` (dongle n°2) : rôle « source » vis-à-vis des casques.
- Le Bluetooth intégré du Pi est désactivé (`dtoverlay=disable-bt`).
- Optionnel : un bouton GPIO pour passer en mode appairage / changer de source.

Les noms hci0/hci1 ne sont pas stables : identifier les adaptateurs par adresse MAC dans la configuration.

## 3. Pile logicielle

- OS : Raspberry Pi OS / Debian Trixie (64 bits). Bookworm est exclu (PipeWire trop ancien).
- BlueZ (version de la distribution).
- PipeWire ≥ 1.2 + WirePlumber 0.5, backend Bluetooth natif (pas oFono, sauf si la phase 0 le rend nécessaire).
- Daemon applicatif `btmuxd` : Python 3.12+, asyncio, dbus-fast pour BlueZ, pilotage de PipeWire via `pw-dump` (JSON) / `pw-link` / `pw-metadata`, ou via un script Lua WirePlumber si c'est plus robuste. Choix à justifier en phase 0.
- Outillage : uv, ruff, mypy, pytest.
- Déploiement : unités systemd + rôle Ansible pour provisionner un Pi vierge de façon reproductible.

## 4. Architecture

```
 PC pro ─┐                                                         ┌─> Casque A
 PC perso ┼─(BT)─> [hci-src]  ──> PipeWire ──> [hci-hp] ─(BT)──────┤
 Tél. ───┘   rôle casque          routage       rôle source        └─> Casque B
            A2DP sink, HFP HF   (btmuxd)       A2DP src, HFP AG
```

### 4.1 Rôles par adaptateur

| Adaptateur | Classe annoncée | Profils actifs | Nom annoncé |
|------------|-----------------|----------------|-------------|
| hci-src | 0x240404 (casque audio) | A2DP sink, HFP HF, AVRCP controller | configurable, ex. « btmux » |
| hci-hp | téléphone / ordinateur | A2DP source, HFP AG, AVRCP target | configurable, ex. « btmux-src » |

Nom et classe se règlent par adaptateur (`btmgmt -i <idx> name|class`) au démarrage, et non via `main.conf` qui s'applique globalement.

> **Note (spike #5, 2026-10-23, provisoire)** : avec les quatre rôles, la classe réelle est **0x006C0404** et non
> 0x240404 (le noyau ajoute les bits *Capturing* et *Telephony* liés à HFP). Windows et le téléphone classent quand
> même btmux comme casque. Le Bluetooth interne du Pi 3 ne convient pas à deux liens (UART, antenne partagée) : le
> bi-adaptateur reste la cible. Détail : [spikes/05-exposure.md](spikes/05-exposure.md).

> **Note (2026-10-23)** : BT interne abandonné pour les spikes (décision utilisateur du jour) ; cible bi-adaptateur
> 2 × TP-Link UB500 (RTL8761BU) dès v0.2.0. Détail : [spikes/07-routing.md](spikes/07-routing.md).

Les rôles PipeWire (`bluez5.roles`) doivent être restreints par adaptateur pour qu'aucun profil AG/source n'apparaisse côté sources et inversement. Mécanisme exact à valider en phase 0 (règles WirePlumber sur les propriétés d'adaptateur/périphérique). Fallback : filtrage par le daemon.

### 4.2 Appairage

- Agent BlueZ fourni par btmuxd, en NoInputNoOutput.
- Appairage refusé par défaut. Il n'est accepté que pendant une fenêtre « mode appairage » (60 s) ouverte via l'API, un bouton GPIO ou la CLI.
- Les appareils appairés sont marqués Trusted et se reconnectent automatiquement.
- Côté casques, c'est btmuxd qui initie la connexion vers les casques connus au démarrage et lorsqu'ils réapparaissent.

### 4.3 Politique de routage

Pour chaque casque, une source active au plus. Ordre de priorité :

1. Appel HFP actif (entrant, sortant ou en cours) sur une source → cette source prend le casque, profil HFP des deux côtés, micro routé vers elle.
2. Sélection manuelle (API, CLI, bouton) → maintenue jusqu'à nouvelle sélection ou déconnexion de la source.
3. Dernière source ayant commencé à émettre (le stream A2DP passe à l'état actif).

À la fin d'un appel, retour à la source précédente. Les sources non routées restent connectées et leurs flux sont ignorés (pas de mise en pause forcée en v1).

Changement de profil côté casque : A2DP quand aucun appel n'est en cours, HFP (mSBC si supporté, sinon CVSD) quand un appel ou un usage micro est actif. Côté source, c'est la source elle-même qui choisit son profil (Windows bascule en HFP quand Teams ouvre le micro) ; le daemon suit et aligne le profil du casque.

### 4.4 Contrôles et métadonnées

- AVRCP : les boutons du casque (play/pause/next/prev) sont relayés vers la source active (le Pi est AVRCP target pour les casques, controller pour les sources). Voir `org.bluez.Media1.RegisterPlayer` et `org.bluez.MediaPlayer1`.
- Volume absolu : synchronisé entre la source active et le casque via `MediaTransport1.Volume`.
- Contrôle d'appel HFP : décrocher/raccrocher/rejeter depuis le casque doit être relayé vers la source (commandes AT `ATA`/`AT+CHUP`). Utiliser l'API téléphonie D-Bus du backend natif PipeWire si elle couvre le besoin (à vérifier en phase 0), sinon évaluer oFono pour le rôle HF uniquement.
- La sonnerie / l'indication d'appel entrant doit être présentée au casque.

### 4.5 Interfaces de pilotage

API HTTP (FastAPI ou aiohttp), écoute LAN uniquement, jeton statique dans la config :

- `GET /state` : adaptateurs, appareils connus/connectés, routage courant, appels en cours.
- `POST /route {headset, source}` : sélection manuelle.
- `POST /pairing {adapter, duration}` : ouvre une fenêtre d'appairage.
- `POST /devices/{mac}/forget` : oublie un appareil.

MQTT optionnel (Home Assistant discovery) : un `select` par casque pour la source.

CLI `btmuxctl` utilisant l'API.

### 4.6 Configuration

Fichier YAML `/etc/btmux/config.yaml` :

```yaml
adapters:
  sources:   { mac: "AA:BB:CC:00:00:01", name: "btmux" }
  headsets:  { mac: "AA:BB:CC:00:00:02", name: "btmux-src" }
devices:
  - { mac: "...", alias: "pc-pro",   kind: source,  priority: 10 }
  - { mac: "...", alias: "tel-perso", kind: source, priority: 20 }
  - { mac: "...", alias: "xm5",      kind: headset }
default_routes:
  xm5: pc-pro
api: { listen: "0.0.0.0:8088", token_file: /etc/btmux/token }
mqtt: { enabled: false }
```

## 5. Exigences non fonctionnelles

- Latence bout en bout en A2DP : < 300 ms. Mesurer et documenter.
- Bascule de source (sans changement de profil) : < 1 s.
- Bascule A2DP → HFP lors d'un appel : < 2 s.
- Reconnexion automatique après redémarrage du Pi ou extinction d'un casque, sans intervention.
- Aucune perte d'appairage au redémarrage.
- Logs structurés (journald) : connexions, changements de profil, décisions de routage avec leur motif.
- Le daemon doit survivre au redémarrage de PipeWire ou de BlueZ (resynchronisation de l'état).
