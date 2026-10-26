# Procédure QA — Spike #7 : routage PipeWire sur un adaptateur unique

**Issue** : #7 · **Milestone** : v0.1.0 · **Tags** : `hardware` (manuel, jamais en CI) · **Testeur** : QA · **Date** : ____
**Cible** : pi-qualif (`ubuntu@<IP-du-Pi>`), `hci0` **BT interne** BCM43430A1 (MAC du Pi dans `docs/install-pi.md` §9).
**Séance (utilisateur)** : `_work/handoff/dev-backend-spike07-*.md`. Code : `spikes/07-routing/`. Rapport : `docs/spikes/07-routing.md`.

> **Mention obligatoire** : en BT interne les résultats sont **provisoires — à revalider avec dongle UB500 (T3.2b)**.
> Contrainte : **≤ 2 liens ACL** (au-delà l'UART saturé : `Frame reassembly failed`, contrôleur muet). Topologie jouée
> maintenant : **1 source réelle** (téléphone Samsung S24) + **casque Bose** + **1 source virtuelle PipeWire**. Wi-Fi conservé,
> pas d'Ethernet (`disable-wifi` reporté à T3.2b) : le consigner comme condition de mesure.

**Colonnes** : « Interne » = jouable maintenant (BT interne) ; « UB500 » = reporté en T3.2b (`⏭` = reporté, `—` = sans objet).
Cocher une colonne par contrôle effectivement joué ; un `⏭` non joué n'est pas un échec.

## Prérequis et garde-fous

- [ ] `BTMUX_BT_MODE=internal` : le prototype **refuse** de connecter un 3ᵉ appareil (vérifier le refus)
- [ ] `dmesg -w` surveillé pendant toute la séance ; **arrêt immédiat au premier `tx timeout` / `Frame reassembly`** (noter l'heure, ne pas relancer sans reboot)
- [ ] Jamais plus de 2 liens ACL simultanés (`bluetoothctl devices Connected` ≤ 2 à tout moment)
- [ ] Preuves dans `_work/tmp/spike-07/` (fichiers `out/` du prototype, `pw-dump`, journaux horodatés)
- [ ] Prototype validé **hors matériel** avec deux sources virtuelles (bascule logicielle pure) avant la séance : sortie jointe

## 1. Critère 1 — Multiplexage et bascule

| # | Contrôle | Preuve attendue | Interne | UB500 bi | OK int. | OK UB500 bi |
|---|----------|-----------------|---------|-------|---------|----------|
| 1.1 | Source réelle (S24) en A2DP sink + casque en A2DP source, flux entrant et sortant simultanés | `pw-dump`/`wpctl status` : nœuds `bluez_input`/`bluez_output` `running` ; audio audible | ✔ | — | | |
| 1.2 | Bascule **réelle → virtuelle → réelle**, ×3 minimum, sans déconnexion BT | `bluetoothctl devices Connected` inchangé avant/après chaque bascule ; liens PipeWire créés/supprimés (journal prototype) | ✔ | — | | |
| 1.3 | Temps de bascule mesuré (≥ **10** bascules au total sur la séance) | Fichier `out/switch_times.*` : n, min/médiane/max ; comparé à `testing.perf.source_switch_ms_max` (1000 ms) — **indicatif, non bloquant** en interne | ✔ (indicatif) | ✔ opposable | | |
| 1.4 | **2 sources réelles** (PC + téléphone) + casque, bascule réelle ↔ réelle | Mesure < 1 s, aucune déconnexion BT | ⏭ (3 liens ACL interdits) | ✔ | | |
| 1.5 | Tenue ≥ 10 min avec 2 flux | Aucun `xrun`/coupure/erreur HCI | ⏭ (≥ 8 min max observé en interne) | ✔ | | |
| 1.6 | Conditions de mesure consignées | Wi-Fi actif, pas d'Ethernet, version PipeWire/WirePlumber, codec A2DP négocié (SBC attendu, pas d'AAC) | ✔ | ✔ | | |

## 2. Critère 2 — Prototype Python asyncio

| # | Contrôle | Preuve attendue | Interne | UB500 bi | OK int. | OK UB500 bi |
|---|----------|-----------------|---------|-------|---------|----------|
| 2.1 | Découverte des nœuds (`pw-dump` JSON ou API native) | Sortie du prototype listant source réelle, virtuelle, casque | ✔ | ✔ | | |
| 2.2 | Création / suppression de liens | Journal + `pw-link -l` avant/après | ✔ | ✔ | | |
| 2.3 | Détection de l'état `running` d'un stream (règle n°3 du cadrage) | Pause/lecture du S24 → événement `running`/`idle` horodaté | ✔ | ✔ | | |
| 2.4 | Apparition/disparition de nœuds **par événements, sans polling** | Éteindre/rallumer le casque → événements reçus ; revue du code : pas de boucle `sleep` de scrutation | ✔ | ✔ | | |

## 3. Critère 3 — Variante Lua WirePlumber

| # | Contrôle | Preuve attendue | Interne | UB500 bi | OK int. | OK UB500 bi |
|---|----------|-----------------|---------|-------|---------|----------|
| 3.1 | Variante Lua rejouée sur les étapes 2–4 de la séance (bascule, `running`) | Script + sortie dans `out/lua/` | ✔ | — | | |
| 3.2 | Tableau comparatif pw-* / API native / Lua : robustesse au redémarrage, resync d'état, observabilité | Tableau dans le rapport, une ligne par critère, chaque cellule justifiée | ✔ | — | | |

## 4. Critère 4 — Redémarrage PipeWire/WirePlumber

| # | Contrôle | Preuve attendue | Interne | UB500 bi | OK int. | OK UB500 bi |
|---|----------|-----------------|---------|-------|---------|----------|
| 4.1 | `systemctl --user restart pipewire wireplumber` en cours de lecture | Liens reconstruits par le prototype, durée relevée ; BT non reconnecté (ou reconnexion notée) | ✔ | ✔ | | |
| 4.2 | Idem avec la variante Lua | Résultat consigné (reconstruits / non) | ✔ | — | | |

## 5. Contrôle du rapport `docs/spikes/07-routing.md` (critère 5)

| # | Contrôle | OK ? |
|---|----------|------|
| 5.1 | Sections : **Objectif · Matériel/versions · Protocole · Résultats · Limites · Décision/Verdict · À revalider avec le dongle (UB500)** | |
| 5.2 | Mention **« provisoire — à revalider avec dongle UB500 (T3.2b) »** en tête et dans le verdict | |
| 5.3 | Topologie réellement jouée décrite (S24 + Bose + source virtuelle ; ≤ 2 liens ACL) et conditions : Wi-Fi conservé, pas d'Ethernet | |
| 5.4 | Chaque résultat renvoie à une preuve ; aucun résultat sans preuve ; mesures de bascule avec n, min/médiane/max | |
| 5.5 | Temps de bascule présenté comme **indicatif** (réel ↔ virtuel) ; la mesure opposable réel ↔ réel est renvoyée à T3.2b | |
| 5.6 | **Décision explicite** : `pw-*` / `Lua WirePlumber` / `API native` (une seule valeur, justifiée par le tableau comparatif) | |
| 5.7 | **Squelette d'abstraction** proposé pour `src/btmux/pipewire/` (classes/événements, pas de polling) | |
| 5.8 | § « À revalider avec le dongle » : 2 sources réelles, bascule réel ↔ réel < 1 s, tenue > 8 min à 2 flux, `disable-wifi`/Ethernet | |
| 5.9 | Limites : UART ≤ 3 Mbit/s, ≤ 2 ACL, antenne partagée Wi-Fi, SBC seul (pas d'AAC) | |
| 5.10 | Cohérence verdict ↔ observations (aucun PASS malgré un échec constaté ; incident `tx timeout` éventuel cité) | |
| 5.11 | **Masquage avant commit** (dépôt public) : `python spikes/common/mask_evidence.py --pi-mac <MAC du Pi> --check docs/spikes` retourne 0 ; `grep -rE '([0-9A-Fa-f]{2}[:_-]){5}[0-9A-Fa-f]{2}' docs/spikes` ne montre que la MAC du Pi ; aucun nom d'appareil personnel ni appareil tiers du voisinage | |

## 6. Revalidation UB500 bi — critère 1 complet (séance S1, `revalidation-ub500/`)

Topologie : `hci-src` (rôle `sources`) porte PC + téléphone (A2DP sink) ; `hci-hp` (rôle `headsets`) porte le casque (A2DP source).
Plus de limite à 2 liens ACL : `link_guard.py` plafonne **par adaptateur**, cohérent avec le garde-fou de `btmuxd` (pas de double `block`).
Config bi, `BTMUX_BT_MODE=dongle`, Pi 4, `btmuxd` résident (fenêtres via `btmuxctl`), **Wi-Fi actif** (D2, consigné), sous-tension via hwmon `rpi_volt`.
Codecs : SBC + aptX (AAC indisponible sur Ubuntu 26.04). La latence bout en bout est **retirée** de ce périmètre (D3 → #28, v0.3.0).

| # | Contrôle | Preuve attendue | OK UB500 bi |
|---|----------|-----------------|-------------|
| 6.1 | 2 sources **réelles** (PC + téléphone) sur `hci-src`, casque sur `hci-hp`, flux entrants/sortant simultanés | `bluetoothctl devices Connected` = 3 ; nœuds `running` ; audio audible | |
| 6.2 | Bascule **réelle ↔ réelle** ×10 chronométrée, sans déconnexion BT | `out/switch_times.*` : n ≥ 10, médiane et **p95 < 1 s** (`testing.perf.source_switch_ms_max`) | |
| 6.3 | Tenue 10 min avec 2 flux | 0 `xrun`, 0 erreur HCI (`watch_hci.sh` ×2), aucune déconnexion | |
| 6.4 | Bascule avec formats **FL/FR** (canaux) correcte | Pas d'inversion de canaux ni de silence, relevé `pw-dump` | |
| 6.5 | `systemctl --user restart pipewire wireplumber` **avec BT connecté** (3 liens) | Liens reconstruits, durée relevée, appareils non reconnectés (ou délai noté) | |
| 6.6 | Conditions consignées : **Wi-Fi actif** (D2), hub USB 2.0 interne du Pi 4 partagé, codec A2DP (aptX/SBC) | Dans le rapport § « Revalidation UB500 » | |
| 6.7 | Rapport `docs/spikes/07-routing.md` § « Revalidation UB500 » : statut provisoire **levé ou maintenu**, motivé ; mesures opposables | | |

## Critères de validation

- [ ] Colonne « Interne » : tous les contrôles jouables OK (écarts documentés avec impact sur la décision)
- [ ] Colonne « UB500 » : cases `⏭` listées dans le rapport § « À revalider » (non bloquant pour le GATE du LOT-2.2)
- [ ] §5 complet ; aucune modification hors `spikes/07-routing/`, `docs/spikes/07-routing.md`, preuves
- [ ] Verdict QA : [ ] VALIDATED (provisoire)  [ ] NOT VALIDATED — motif : ______

## Notes QA

