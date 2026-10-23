# spikes/07-routing — prototype de routage PipeWire (spike #7)

> **Provisoire — à revalider avec dongle RTL8761B.** Validé hors matériel (sources virtuelles) sur `pi-qualif`
> (Pi 3, Ubuntu 26.04, PipeWire 1.6.2, WirePlumber 0.5.13) ; les essais avec appareils Bluetooth réels viennent
> avec la séance (voir la procédure) et sont limités à **2 liens ACL** sur le Bluetooth interne.
> Code jetable : stdlib Python 3.12+ seulement, aucune dépendance.

## Contenu

| Fichier | Rôle |
|---------|------|
| `pw_graph.py` | Modèle nœuds / ports / liens alimenté par **événements** (`pw-dump -m`), `wait_for(prédicat)` sans polling, détection `running` et apparition/disparition de nœuds. Une suppression arrive sans `type` : `{"id": N, "info": null}`. |
| `router.py` | Bascule A → B → A par création/suppression de liens, **chronométrée** (`t_link`, `t_active`, `t_running`). Méthodes : `pwlink-seq`, `pwlink-par`, `pwcli` (session `pw-cli` persistante). `--virtual` (tout virtuel), `--virtual-b` (A et sink réels, B virtuelle), ou nœuds existants. |
| `relink_after_restart.py` | Mémorise la route, `systemctl --user restart pipewire wireplumber`, attend le démon puis les nœuds (événements), recrée sink/sources virtuels si besoin et reconstruit les liens. |
| `virtual.py` | Sink `support.null-audio-sink` (linger) + sources `pw-play` (`node.autoconnect=false`). |
| `wireplumber/btmux-route.lua`, `52-btmux-route.conf` | Variante Lua : route pilotée par la métadonnée `btmux.route` (`SRC>SINK`). |
| `measure_lua.py` | Mesure la bascule de la variante Lua. |
| `watch_uart.sh` | Garde-fou : signale la première erreur UART HCI (Bluetooth interne). |

## Résultats hors matériel (sources virtuelles, 12 cycles A↔B = 24 bascules, `pi-qualif`, 2026-10-23)

| Méthode | médiane | p95 | max | Remarque |
|---------|---------|-----|-----|----------|
| `pw-link` un processus par lien, séquentiel | 315 ms | 392 ms | 430 ms | ~100–140 ms par fork sur Pi 3 |
| `pw-link` en parallèle | 270 ms | 282 ms | 288 ms | |
| **session `pw-cli` persistante** (`create-link`/`destroy`) | **94 ms** | 104 ms | 106 ms | aucun fork ; `t_active` ≈ `t_running` |
| Lua WirePlumber (clé `btmux.route`) | 168 ms | 177 ms | 180 ms | dont ~69 ms de lancement de `pw-metadata` : ≈ 100 ms dans WirePlumber (timer de regroupement 20 ms inclus) |

Tous < 1 s (cible du cadrage). Mesures `t_active`, depuis la commande jusqu'aux liens `active`.
Fichiers : `out/router-virtual-*.json`, `out/lua-virtual.json` (non versionnés).

### Après `systemctl --user restart pipewire wireplumber` (sans appareil BT)

| Variante | Résultat |
|----------|----------|
| Python (`relink_after_restart.py --virtual`) | PipeWire répond de nouveau à **0,67 s**, nœuds à **1,5 s**, liens reconstruits et `active` à **1,67 s** (nœuds virtuels recréés par le script ; avec BT les nœuds `bluez_*` réapparaissent seuls — non testé, cf. ci-dessous). |
| Lua | Après un restart de WirePlumber, **les liens et la clé `btmux.route` sont perdus** (métadonnée non persistante) ; ré-émettre la clé reconstruit les liens (~1,5 s). Le script se recharge seul mais n'a plus la route. |

## Tableau comparatif (préliminaire — décision dans le rapport T2.8)

| Critère | `pw-*` pilotés par Python asyncio | Lua WirePlumber |
|---------|-----------------------------------|-----------------|
| Temps de bascule | 94 ms (session `pw-cli`), 270–315 ms (fork par lien) | ≈ 100 ms dans WP + coût du canal de commande |
| Détection `running`, apparition/disparition de nœuds | Oui, par événements (`pw-dump -m`), état complet du graphe côté btmuxd | Possible dans le script (ObjectManager) mais l'état n'est pas observable depuis btmuxd sans export |
| Robustesse au restart PipeWire/WirePlumber | btmuxd détecte l'arrêt du flux d'événements, se reconnecte et reconstruit depuis la route voulue (1,67 s) | La route (métadonnée) est perdue ; doit être ré-émise par btmuxd, donc dépendance équivalente |
| Observabilité | Journal applicatif de btmuxd, graphe en mémoire | Logs WP (`s-btmux-route`), pas d'état exposé |
| Déploiement | Aucun changement côté WirePlumber | Fichier script + composant `required` ; un défaut de script peut empêcher WirePlumber de démarrer ; le charger exige **un restart WirePlumber** (interdit avec un appareil BT connecté sur le contrôleur interne) |
| Contraintes du bac à sable Lua | — | `collectgarbage` absent ; `optional` ne charge pas le composant (il faut `required`) |
| Test local | Oui (PipeWire sur une machine de dev) | Seulement sur une machine avec WirePlumber |

Pistes pour `src/btmux/pipewire/` : un `PwGraph` (événements `pw-dump -m`), un `PwLinker` (session `pw-cli` persistante,
repli `pw-link`), un `RouteManager` (route voulue + resynchronisation sur chaque événement de graphe) ; l'API native
(bindings Python) n'a pas été évaluée (non disponible sur la cible).

## Limites et sécurité du spike

- Valeurs mesurées sur Pi 3 avec **sources virtuelles** : les délais en conditions réelles (Bluetooth) restent à mesurer.
- **Incident (2026-10-23, 11:11 UTC)** : un `systemctl --user restart pipewire wireplumber` exécuté **avec** le Bose et le PC
  connectés a figé le contrôleur interne (`link tx timeout`, `killing stalled connection`, `command 0x0406/0x0c24 tx timeout`,
  bluetoothd `Failed to remove/add UUID: Authentication Failed (0x05)` en boucle) ; reboot nécessaire. Cause probable : le
  restart désenregistre/ré-enregistre les profils auprès de BlueZ, d'où des commandes HCI (UUID, classe d'appareil) que le
  contrôleur UART ne traite plus. **Interdit** : restart PipeWire/WirePlumber avec un appareil BT connecté sur le
  Bluetooth interne (reporté en T3.2b avec dongle). Les essais sans BT se font **contrôleur éteint** (`btmgmt power off`).
- Jamais plus de **2 liens ACL** simultanés ; arrêt immédiat au premier `Frame reassembly failed` / `tx timeout` (`watch_uart.sh`).
