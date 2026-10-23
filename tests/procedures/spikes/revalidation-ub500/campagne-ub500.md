# Procédure QA — Campagne de revalidation UB500 (bi-adaptateur) : séances S1 et S2

**Issues** : #19 (synthèse), #12 (identité), #13 (rôles), #6 (HFP double rôle), #8 (latence) ; revalide #5 et #7 · **Milestone** : v0.2.0
**Tags** : `hardware` (manuel, jamais en CI) · **Testeur** : QA · **Date** : ____
**Cible** : pi-qualif, **2 × TP-Link UB500** (RTL8761BU, `2357:0604`), config bi (`hci-src` = `sources`, `hci-hp` = `headsets`).
**Séances (utilisateur)** : `_work/handoff/dev-backend-s1-*.md` (≈ 1 h 15) et `-s2-*.md` (≈ 1 h). Code : `spikes/t32b/`, `spikes/common/`.
Cette checklist **valide les preuves et les rapports** produits par les séances. Elle reprend les colonnes « UB500 bi » des
procédures `05-exposure`, `06-hfp-dual-role`, `07-routing` (références `§6` de chacune) sans les dupliquer.

> **Règle de statut** : tant que cette campagne n'est pas jouée, les rapports 05/06/07/08 et les ADR 0001/0003 restent
> **« provisoire — validé sur BT interne »**. Cette procédure décide si le statut est **levé** ou **maintenu** (avec motif).

## Prérequis (préparation dev-backend, hors séance)

- [ ] Réception des 2 UB500 : `tests/procedures/install/pi-qualif/` scénario 7 (réception + bascule `disable-bt`) **PASS**, tableau MAC ↔ rôle ↔ port complété
- [ ] `BTMUX_BT_MODE=dongle` ; script `docs/install-pi.md` §8 : 2 contrôleurs USB, 0 UART
- [ ] **Ethernet branché, `disable-wifi` posé** (reporté de LOT-2.2) ; état consigné comme condition de mesure
- [ ] Config bi valide (`btmuxd --check-config` code 0) ; `btmux-adapters.service` actif ; `roles.conf` (`bluez5.roles` par adresse) en place
- [ ] `wpctl status` sain ; `watch_hci.sh` lancé **une fois par `hciN`** ; `link_guard.py` : plafond **par adaptateur** (`block`)
- [ ] Appareils : PC Windows (Teams), téléphone, casque ; fenêtre d'appairage ouverte uniquement pendant la séance
- [ ] Preuves dans `_work/tmp/campagne-ub500/` (sous-dossiers `s1/`, `s2/`) ; **arrêt immédiat** au premier `tx timeout`/`Frame reassembly`

## S1 — Identité, rôles, exposition, routage (≈ 1 h 15)

### S1.1 #12 — Identité par adaptateur

| # | Contrôle | Preuve attendue | OK |
|---|----------|-----------------|----|
| S1.1.1 | Windows et téléphone voient **`btmux` seul** (pas de second appareil) | Captures « Bluetooth et appareils » ; scan téléphone | |
| S1.1.2 | Le casque voit **`btmux-hp`** (nom du rôle `headsets`), jamais `btmux` | Capture / `bluetoothctl scan` côté casque ou journal d'appairage | |
| S1.1.3 | Classes : `sources` ≈ casque audio (`0x240404` cible), `headsets` ≈ « ordinateur » | `bluetoothctl show` par contrôleur ; écart documenté (#12 tranche la classe de `hci-hp`) | |
| S1.1.4 | **Permutation** des deux dongles (ports échangés) puis reboot : les rôles suivent les **MAC** | Tableau MAC ↔ rôle ↔ port avant/après ; alias/classe restaurés par `btmux-adapters.service` | |
| S1.1.5 | Reboot : appairages conservés, reconnexion automatique | `reboot_check.sh` ×2 | |

### S1.2 #13 — Rôles par adaptateur

| # | Contrôle | Preuve attendue | OK |
|---|----------|-----------------|----|
| S1.2.1 | SDP/profils exposés par **chaque** adaptateur (`sdptool browse`/`bluetoothctl show`) | Dump par `hciN` : `hci-src` = A2DP sink + HFP HF ; `hci-hp` = A2DP source + HFP AG | |
| S1.2.2 | `roles.conf` (`bluez5.roles` par adresse) ajusté et appliqué | Fichier + `wpctl status` : cartes du bon rôle seulement | |
| S1.2.3 | Aucun rôle parasite (pas d'AG sur `hci-src`, pas de sink sur `hci-hp`) | Dump SDP | |
| S1.2.4 | `roles.conf` validé livré dans `config/wireplumber/` (T3.5) | Chemin + diff relu | |

### S1.3 #5 étapes 3–6 en bi (voir `05-exposure` §6)

- [ ] 05 §6.1 → §6.5 joués (PC + téléphone sur `hci-src`, casque sur `hci-hp`, audio 5 min, reboot) — colonne « UB500 bi » cochée

### S1.4 #7 critère 1 en bi (voir `07-routing` §6)

- [ ] 07 §6.1 → §6.7 joués : 2 sources réelles + casque, bascule réel ↔ réel ×10, **p95 < 1 s**, tenue 10 min, FL/FR, `restart pipewire wireplumber` BT connecté

### S1.5 Rapports S1

| # | Contrôle | OK |
|---|----------|----|
| S1.5.1 | `docs/spikes/12-adapters.md` et `13-roles.md` : sections Objectif · Matériel/versions · Protocole · Résultats · Limites · Décision/Verdict · À revalider ; **verdict explicite** (OUI/NON/RÉSERVES) | |
| S1.5.2 | § « Revalidation UB500 » ajoutée à `05` et `07`, statut provisoire levé ou maintenu, motivé | |
| S1.5.3 | Hub USB 2.0 partagé et Ethernet/`disable-wifi` cités dans les conditions de mesure | |
| S1.5.4 | Masquage avant commit (dépôt public) : `python spikes/common/mask_evidence.py --pi-mac <MAC> --check docs/spikes` retourne 0 ; `grep -rE '([0-9A-Fa-f]{2}[:_-]){5}[0-9A-Fa-f]{2}' docs/spikes` ne montre que les MAC du Pi/dongles | |

## S2 — Voix et mesures (≈ 1 h)

### S2.1 #6 — Double rôle HFP, double SCO (voir `06-hfp-dual-role` §6)

- [ ] 06 §6.1 → §6.8 joués : HF `hci-src` + AG `hci-hp`, double SCO, codecs, capacité SCO par dongle, 5 bascules Teams, 10 min
- [ ] **Décision backend** (natif / oFono / hybride) consignée ; si oFono : essai du rôle HF documenté

### S2.2 #8 — Latence et fiabilité du double saut

| # | Contrôle | Preuve attendue | OK |
|---|----------|-----------------|----|
| S2.2.1 | Latence A2DP double saut (≥ 10 mesures par configuration, corrélation croisée) | `out/latency_*.csv` ; **objectif informatif < 300 ms** (`testing.perf`) | |
| S2.2.2 | Bascule source → source mesurée | Médiane/p95 vs **< 1 s** | |
| S2.2.3 | Bascule A2DP → HFP (Teams) | Durée vs **< 2 s** | |
| S2.2.4 | Dropouts : `dropouts_30min.sh` (30 min pleins = S3 **optionnelle**) | Comptage `xrun` ; si S3 non jouée, durée réelle et limite consignées | |
| S2.2.5 | Variations `quantum` / `bluez5.a2dp.*` | Tableau réglage → latence | |
| S2.2.6 | Conditions : Ethernet, `disable-wifi`, hub USB 2.0 unique, codec A2DP/SCO | Dans `08-latency.md` | |

### S2.3 Rapports S2 et synthèse #19

| # | Contrôle | OK |
|---|----------|----|
| S2.3.1 | `06-hfp-dual-role.md` : sections obligatoires, **décision backend**, § bi-adaptateur (#15), statut provisoire levé/maintenu | |
| S2.3.2 | `08-latency.md` : résultats vs `testing.perf` (300 / 1000 / 2000 ms) et **verdict mono/bi explicite** (viable / réserves / insuffisant) | |
| S2.3.3 | `19-revalidation-ub500.md` (synthèse) : tableau récapitulatif de tous les contrôles « UB500 bi » (OK / KO / non joué), **verdict bi** global, statut de chaque ADR concerné | |
| S2.3.4 | Cohérence croisée 05/06/07/08/12/13/19 : aucun verdict contradictoire avec les preuves ; incidents (`tx timeout`, reset contrôleur) cités | |
| S2.3.5 | Masquage des preuves (même contrôle que S1.5.4) | |

## Critères de validation

- [ ] S1 et S2 : tous les contrôles OK, ou écarts documentés avec impact sur le verdict
- [ ] Décision **levée / maintenue** du statut « provisoire » écrite pour : rapports 05, 06, 07, 08 ; ADR 0001, 0003
- [ ] Verdict bi-adaptateur tranché (viable / réserves / insuffisant) et répercuté sur le backlog (#15)
- [ ] Aucune modification hors `spikes/`, `docs/spikes/`, `config/wireplumber/`, preuves
- [ ] Verdict QA : [ ] VALIDATED  [ ] NOT VALIDATED — motif : ______

## Notes QA

