# Spike #7 — Routage PipeWire : bascule de source par création/suppression de liens

> **Provisoire — à revalider avec dongle UB500 (T3.2b)** (puce RTL8761BU). Les mesures « réelles » ont été faites sur le
> **Bluetooth interne du Pi 3** (UART, ≤ 2 liens ACL en pratique, antenne partagée avec le Wi-Fi) et **sans deuxième source
> Bluetooth réelle** : la topologie « deux sources réelles + casque » s'est effondrée (cf. Incidents). Les temps de bascule
> sont **indicatifs** ; la mesure opposable réel ↔ réel est renvoyée à T3.2b.

Issue : #7 · Séance : 2026-10-23, 14:03–14:20 heure de Paris (12:03–12:20 UTC), précédée d'essais hors matériel (≈ 13:00–13:30 Paris) ·
Prototype : `spikes/07-routing/` (README avec les tableaux détaillés) · Procédure QA : `tests/procedures/spikes/07-routing/routage-mono-adaptateur.md`.
**Convention horaire** : heures de Paris (UTC+2) sauf mention « UTC » ; les annexes (`docs/spikes/07-routing/`) sont en UTC.
Les adresses MAC des appareils de l'utilisateur sont masquées (`xx`) ; seule celle du Pi est en clair.

## Objectif

Prouver le **multiplexage** mono-adaptateur : deux sources A2DP connectées au Pi et un casque alimenté par le Pi sur le même
`hci`, bascule de source purement logicielle (sans reconnexion Bluetooth), et choisir le mécanisme de routage pilotable depuis
Python asyncio (`pw-*` / Lua WirePlumber / API native).

## Matériel / versions

| Élément | Valeur |
|---------|--------|
| Pi | Raspberry Pi 3 Model B Rev 1.2 (`pi-qualif`), Ubuntu 26.04.1 (`resolute`, aarch64, noyau 7.0.0-1020-raspi), Python 3.14.4 |
| Bluetooth | **interne** `hci0` BCM43430A1, MAC B8:27:EB:1A:2E:D6, HCI 4.2, UART ; Wi-Fi actif (SSH), pas d'Ethernet |
| Audio | PipeWire 1.6.2, WirePlumber 0.5.13, BlueZ 5.85 ; config headless (`seat-monitoring` désactivé) ; **pas d'AAC** (codec A2DP du casque : SBC) |
| Appareils | casque Bose (sink A2DP), téléphone Samsung Galaxy S24 Ultra, PC « MSI » (Windows 11) |
| Sources virtuelles | `pw-play` de deux tonalités (440 Hz et 660 Hz, stéréo 8 kHz), `node.autoconnect=false` ; sink virtuel `support.null-audio-sink` |

## Protocole

1. **Hors matériel** (sources et sink virtuels, aucun appareil Bluetooth connecté) : `router.py --virtual` (3 méthodes), `measure_lua.py`,
   `relink_after_restart.py --virtual`, `skew_probe.py` — 12 cycles A↔B = 24 bascules par méthode.
2. **Séance réelle prévue** (procédure `_work`, 45 min) : téléphone en lecture → Bose connecté par le Pi → source virtuelle →
   bascules chronométrées → restart → clôture, avec garde-fou `watch_uart.sh`.
3. **Repli** (décision du 14:12) après l'effondrement de l'étape 2 : **Bose seul** (1 ACL) comme sink réel + **deux sources
   virtuelles** (440/660 Hz), téléphone et PC bloqués côté Pi (`bluetoothctl block`).
Les étapes jouées avec le Bose réel : écoute (5 cycles, pause de 4 s), mesures (12 cycles, pause de 1,5 s), variante Lua,
pause/reprise du flux, clôture.

## Résultats

### Par critère d'acceptation de #7

| Critère | Statut | Détail / preuve |
|---------|--------|-----------------|
| Deux sources A2DP (PC + téléphone) en sink + casque en source sur le même adaptateur, flux entrant et sortant simultanés, bascule A→B→A sans déconnexion BT, < 1 s | **PARTIEL** | Bascule A→B→A vers le **sink Bluetooth réel** (Bose, 1 ACL, aucune déconnexion BT) : OK, 153 ms (pwcli). **Deux sources réelles + casque : KO sur le BT interne** (effondrement UART, cf. Incidents) ; PC source réel non testé. Preuves : `router-real-*.json`, `incident-seance7-1210.txt`, `uart.log` |
| Prototype Python asyncio : découverte des nœuds, création de liens, état `running`, apparition/disparition de nœuds par événements | **OK (virtuel), PARTIEL (BT réel)** | `pw_graph.py` (événements `pw-dump -m`, sans polling), `router.py` ; `running` détecté sur nœuds virtuels et sur le sink du Bose (`sink-state.json`) ; apparition/disparition de nœuds : nœuds virtuels et restart OK (`relink-virtual.json`) ; **nœuds `bluez_*` à la (dé)connexion non consignés par événements pendant la séance (NON TESTÉ)** |
| Variante Lua WirePlumber évaluée sur les mêmes critères — tableau comparatif | **OK** | `lua-virtual.json`, `lua-real.json`, `skew-lua.json` ; restart WP : route et liens perdus (cf. ci-dessous) |
| Après `systemctl --user restart pipewire wireplumber` : liens reconstruits par le prototype | **OK sans BT / NON TESTÉ avec BT** | 1,67 s (`relink-virtual.json`) ; **avec appareil BT connecté : interdit** (incident), reporté en T3.2b |
| Rapport avec décision et squelette `src/btmux/pipewire/` | **OK** | Ce document |

### Temps de bascule (24 bascules par méthode, `t_active` = commande → liens `active`, en ms)

| Méthode | sink virtuel : médiane (p95, max) | **sink Bose réel** : médiane (p95, max) | Preuves |
|---------|-----------------------------------|------------------------------------------|---------|
| `pw-link` séquentiel (1 processus par lien) | 315 (392, 431) | **442** (528, 531) | `router-virtual-pwlink-seq.json`, `router-real-mesure-pwlink-seq.json` |
| `pw-link` parallèle | 271 (282, 287) | — | `router-virtual-pwlink-par.json` |
| **session `pw-cli` persistante** | **94** (104, 106) | **153** (170, 187) ; écoute (n = 10) : 155 (186, 186) | `router-virtual-pwcli.json`, `router-real-mesure-pwcli.json`, `router-real-ecoute.json` |
| Lua WirePlumber (`btmux.route`) | 168 (177, 180) dont ~67 ms de `pw-metadata` | 275 (311, 319) soit ≈ 207 hors `pw-metadata` | `lua-virtual.json`, `lua-real.json` |

Tous < 1 s (cible du cadrage), y compris vers le sink Bluetooth réel (+60 à +110 ms par rapport au virtuel). **Indicatif** :
sources virtuelles uniquement, un seul sink réel, un seul Pi.

### Pause / reprise du flux vers le sink Bose réel (3 tours, `sink-state.json`)

Le sink quitte `running` (→ `idle`) **65–71 ms** après la suppression des liens ; la reprise le ramène à `running` en
**114–209 ms**.

### Trou / chevauchement et écart FL/FR (`skew_probe.py`, sink virtuel, 20 bascules par méthode, `skew-*.json`)

`router.py` fait « **unlink de l'ancienne source (attente de sa disparition) puis link de la nouvelle** » : bascule exclusive,
**pas de mixage** au niveau PipeWire, mais un **trou** de quelques dizaines de ms.

| Méthode | trou médian (min–max) | écart FL/FR médian (max) |
|---------|------------------------|--------------------------|
| `pwcli` | 71 ms (58–79) | 0 ms (0) |
| `pwlink-seq` | 119 ms (103–132) | **71 ms** (93) |
| `pwlink-par` | 144 ms (136–180) | 0,8 ms (16) |
| Lua | 65 ms (39–83) | 0 ms (0) |

### Restart PipeWire + WirePlumber (sans appareil BT ; contrôleur éteint pour Lua)

| Variante | Résultat |
|----------|----------|
| Prototype Python | démon de retour à **0,67 s**, nœuds à **1,5 s**, liens reconstruits et `active` à **1,67 s** (`relink-virtual.json`) |
| Lua | un restart de WirePlumber fait **perdre liens et clé `btmux.route`** (métadonnée non persistante) ; la ré-émission de la clé reconstruit les liens (~1,5 s) |

### Ressenti de l'utilisateur (Bose, heures de Paris, attribué aux passes d'après leurs horodatages)

| Heure | Passe | Ressenti | Lecture |
|-------|-------|----------|---------|
| 14:16 | étape 3 : `pwcli`, 440/660 Hz, pause 4 s | « j'entends bien les deux sources alternativement » ; demande si on peut les entendre **en même temps** (chevauchement perçu) | Le graphe ne contient aucun lien double (unlink avant link, trou de ~70 ms) : le recouvrement perçu vient probablement de la **mise en tampon A2DP** du Bose, qui joue encore la fin de A pendant que B démarre. Non démontré sans capture audio. |
| 14:17–14:18 | étape 4 : `pwcli` rapide (1,5 s), puis `pwlink-seq` | « aucune coupure » ; « légère alternance droite/gauche au changement » | L'effet gauche/droite correspond à la passe `pwlink-seq` (14:17:48–14:18:39) : **écart FL/FR de 71 ms** (un `pw-link` par canal). |
| 14:19 | étape 5 : **Lua** | « bascule parfaite » | passe Lua (14:19:00–14:19:22) : écart FL/FR 0 ms, trou 65 ms. |

## Incidents

1. **Restart PipeWire/WirePlumber avec appareils BT connectés** (UTC 11:11 = 13:11 Paris, hors séance) : le contrôleur interne se fige
   (`link tx timeout`, `killing stalled connection`, `command 0x0406/0x0c24 tx timeout`, bluetoothd `Failed to remove/add UUID:
   Authentication Failed (0x05)` en boucle) ; reboot nécessaire. Cause probable : désenregistrement/ré-enregistrement des profils
   auprès de BlueZ = commandes HCI (UUID, classe d'appareil) que le contrôleur UART ne traite plus. Preuve :
   `incident-restart-pipewire-bt.txt`. **Interdit en séance avec BT connecté ; contournement validé : contrôleur éteint
   (`btmgmt power off`) pendant les restarts.**
2. **Téléphone + Bose connectés, démarrage de l'audio du téléphone** (12:10:31 UTC = 14:10 Paris) : rafale d'environ 140
   `Frame reassembly failed` + 2 `command tx timeout` ; le garde-fou `watch_uart.sh` déconnecte les deux appareils. Une erreur de
   trame isolée était déjà apparue à l'établissement du 2e lien (12:06:43) et deux autres juste avant la chute du lien du
   téléphone (12:08:46). Preuves : `incident-seance7-1210.txt`, `uart.log`.
3. **Reconnexion spontanée des sources** : le téléphone s'est reconnecté seul (12:11:27 UTC) pendant la mise en place du repli ;
   j'ai connecté le Bose sans m'arrêter sur « 1 ACL déjà actif » (erreur de ma part) → ~900 erreurs de trame supplémentaires (1038
   au total sur le boot, 2 timeouts) avant déconnexion de tout à 12:14. Remède appliqué : `bluetoothctl block` du téléphone et du
   PC pendant le repli (débloqués à la clôture).
4. **Alias non persistant** : `btmgmt name btmux` ne survit pas au reboot (le téléphone voyait « pi-qualif ») → prévoir
   `bluetoothctl system-alias` ou `Name=` dans `main.conf` à l'installation.

## Limites

- **Bluetooth interne du Pi 3 (provisoire, risque R13)** : HCI sur UART (≤ 3 Mbit/s), **≤ 2 liens ACL** en pratique, antenne partagée
  avec le Wi-Fi actif (Ethernet non branché, `disable-wifi` non posé), Bluetooth 4.2, **SBC seul** (pas d'AAC).
- **Topologie réellement jouée** : Bose (1 ACL) + deux sources virtuelles ; la topologie prévue (S24 + Bose + source virtuelle, ≤ 2 ACL)
  s'est effondrée à l'étape 2 ; le PC n'a pas été utilisé comme source. Aucune mesure de bascule **entre deux sources Bluetooth
  réelles**.
- Un seul Pi, un seul casque, un seul téléphone ; latence audio de bout en bout non mesurée ; trou/écart FL/FR mesurés sur sink
  virtuel (pas sur le Bose) ; variante Lua testée sur nœuds virtuels et vers le sink réel, pas avec des sources BT réelles ;
  l'API native PipeWire (bindings) n'a pas été évaluée (non disponible sur la cible).

## Décision / Verdict

**Mécanisme retenu : `pw-*` — événements `pw-dump -m` + session `pw-cli` persistante pour créer/supprimer les liens**, pilotés par
Python asyncio dans btmuxd (repli `pw-link` si `pw-cli` indisponible). Lua WirePlumber et API native ne sont pas retenus pour la v0.3.0.

| Critère | `pw-*` (pw-dump -m + session pw-cli) | Lua WirePlumber | API native |
|---------|--------------------------------------|-----------------|------------|
| Temps de bascule (Bose réel, médiane) | **153 ms** (442 ms avec un fork par lien) | 275 ms (≈ 207 ms dans WP) | non évalué |
| Écart FL/FR | 0 ms (deux `create-link` en un seul envoi) | 0 ms | — |
| Robustesse au restart PipeWire/WirePlumber | btmuxd détecte l'arrêt du flux d'événements, se reconnecte, recrée les liens depuis la route voulue (1,67 s) | route et liens perdus, à ré-émettre par btmuxd ; le restart de WP est le déploiement même du script | — |
| Observabilité | graphe complet en mémoire dans btmuxd (nœuds, ports, liens, états), journal applicatif | logs WirePlumber, aucun état exposé à btmuxd | — |
| Dépendances / déploiement | binaires `pw-dump`/`pw-cli` de PipeWire, aucun fichier WirePlumber à installer | script + composant `required` (un défaut empêche WP de démarrer ; `optional` ne charge pas), `collectgarbage` absent du bac à sable ; restart WP à chaque mise à jour | bindings Python absents |
| Risque Bluetooth | aucun restart nécessaire | restart WP à l'installation = risque contrôleur sur BT interne | — |

Verdict normalisé sur le critère « routage par liens PipeWire sans reconnexion BT avec sink Bluetooth réel » : **RÉSERVES — provisoire — à revalider avec dongle UB500 (T3.2b)**. Pour : bascule exclusive en 153 ms (médiane) vers un sink A2DP réel, sans déconnexion
Bluetooth, restart reconstruit en 1,7 s (sans BT) ; la variante Lua offre le meilleur ressenti (« parfaite ») mais pas de robustesse
supérieure. Contre / réserves : la configuration à **deux sources réelles + casque n'a pas pu être jouée** sur le BT interne
(effondrement UART) ; trou de ~70 ms à chaque bascule ; restart sous BT non testé.

## Squelette proposé pour `src/btmux/pipewire/`

```
src/btmux/pipewire/
  graph.py      # PwGraph : modèle Node/Port/Link alimenté par événements (pw-dump -m), wait_for(), snapshots
  linker.py     # Linker (Protocol) ; PwCliLinker (session pw-cli persistante, create-link/destroy) ; PwLinkLinker (repli)
  route.py      # RouteManager : route voulue {source, sink}, exclusivité, resynchronisation sur chaque événement
  errors.py     # PipeWireUnavailable, NodeMissing, LinkTimeout
```

```python
# graph.py
class PwGraph:
    async def start(self) -> None: ...            # lance `pw-dump -m`, parse le flux JSON incrémental, gère l'EOF
    async def stop(self) -> None: ...
    nodes: dict[int, Node]; ports: dict[int, Port]; links: dict[int, Link]
    def subscribe(self, cb: Callable[[GraphEvent], None]) -> None: ...   # node/port/link, added/changed/removed
    async def wait_for(self, predicate, timeout: float) -> None: ...     # asyncio.Condition, pas de polling
    def node_by_name(self, name: str) -> Node | None: ...
# linker.py
class Linker(Protocol):
    async def link(self, pairs: Sequence[tuple[Port, Port]]) -> None: ...   # un seul envoi pour tous les canaux (FL/FR atomique)
    async def unlink(self, link_ids: Sequence[int]) -> None: ...
# route.py
class RouteManager:
    def __init__(self, graph: PwGraph, linker: Linker): ...
    async def set_route(self, source: str, sink: str, *, exclusive: bool = True) -> RouteResult: ...  # unlink -> link -> attend `active`
    async def clear(self) -> None: ...
    async def run(self) -> None: ...   # boucle d'événements : reconstruit la route après disparition/réapparition de nœuds ou restart
```

Boucle d'événements : `PwGraph.start()` relance `pw-dump -m` tant que le démon est absent (seule boucle de reconnexion, faute d'événement
possible) ; chaque événement `node/port` met à jour le graphe puis réveille `RouteManager.run()`, qui compare la route voulue à
l'état réel et recrée les liens manquants. `running`/`idle` d'un nœud source alimente la règle de routage n°3 du cadrage.

## Points pour btmuxd

1. **Exclusivité vs mixage** : le cadrage attend une bascule exclusive ; la séquence « unlink puis link » laisse un trou de ~70 ms (pas de mixage). Option « lier B puis supprimer A » (make-before-break) → chevauchement de quelques ms ; à trancher selon le ressenti (le tampon A2DP produit déjà un léger recouvrement).
2. **Liaison FL/FR atomique** : tous les canaux dans un seul envoi à la session `pw-cli` (0 ms d'écart) ; ne jamais lancer un `pw-link` par canal (71 ms d'écart, audible).
3. **Relink après restart** : détecter l'EOF de `pw-dump -m`, reconnecter, recréer sink/nœuds attendus, relier ; **ne jamais redémarrer PipeWire/WirePlumber avec un appareil BT connecté sur le contrôleur interne** (contrôleur éteint, ou dongle).
4. **Reconnexion des sources** : les sources se reconnectent d'elles-mêmes et peuvent dépasser le plafond de liens ; politique de connexions dans btmuxd (`block`/`Trusted`, plafond d'ACL) et watchdog UART (arrêt au premier `tx timeout`).
5. **Alias persistant** : `bluetoothctl system-alias` ou `Name=` dans `main.conf` à l'installation (l'alias `btmgmt` ne survit pas au reboot).
6. Sink Bluetooth : le sink repasse `idle` ~70 ms après la suppression des liens et revient `running` en 110–210 ms : tenir compte de ce délai dans la règle « source `running` ».

## À revalider avec le dongle UB500 (T3.2b)

- Bascule **réel ↔ réel** (PC + téléphone réels, casque réel) < 1 s, sans déconnexion BT ; trois liens ACL ou plus.
- Tenue > 8 min à deux flux simultanés sans erreur (USB à la place de l'UART).
- Restart PipeWire/WirePlumber **avec appareils BT connectés** et reconstruction des liens ; apparition/disparition des nœuds `bluez_*` par événements.
- Trou et écart FL/FR mesurés sur le sink Bluetooth réel ; latence A2DP de bout en bout ; chevauchement perçu (capture audio).
- Variante Lua avec sources BT réelles ; API native PipeWire si des bindings existent.
- Ethernet branché et `disable-wifi` posé (antenne partagée).

## Annexes

Fichiers versionnés dans `docs/spikes/07-routing/` (horaires UTC ; MAC des appareils de l'utilisateur masquées) :

| Fichier | Contenu |
|---------|---------|
| `router-virtual-pwlink-seq.json`, `router-virtual-pwlink-par.json`, `router-virtual-pwcli.json` | 24 bascules chacune, sink virtuel |
| `router-real-ecoute.json`, `router-real-mesure-pwcli.json`, `router-real-mesure-pwlink-seq.json` | bascules vers le Bose réel (écoute n = 10, mesures n = 24) |
| `lua-virtual.json`, `lua-real.json` | variante Lua (sink virtuel / Bose réel) |
| `sink-state.json`, `relink-virtual.json`, `skew-virtual.json`, `skew-lua.json` | pause/reprise, restart sans BT, trou et écart FL/FR |
| `uart.log` | journal du garde-fou `watch_uart.sh` pendant la séance |
| `incident-seance7-1210.txt`, `incident-restart-pipewire-bt.txt` | journaux dmesg des deux incidents |
