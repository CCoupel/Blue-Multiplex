# Procédure QA — Campagne de revalidation UB500 (bi-adaptateur) : séances S1 et S2

**Issues** : #19 (synthèse), #12 (identité), #13 (rôles), #6 (HFP double rôle), #8 (latence) ; revalide #5 et #7 · **Milestone** : v0.2.0
**Tags** : `hardware` (manuel, jamais en CI) · **Testeur** : QA · **Date** : ____
**Cible** : pi-qualif (**Raspberry Pi 4 Model B**, Ubuntu 26.04), **2 × TP-Link UB500** (RTL8761BU, `2357:0604`), config bi (`hci-src` = `sources`, `hci-hp` = `headsets`).
**Séances (utilisateur)** : `_work/handoff/dev-backend-s1-*.md` (≈ 1 h 15) et `-s2-*.md` (≈ 1 h), + **S3 optionnelle sans présence** (≈ 1 h). Code : `spikes/t32b/`, `spikes/common/`.
**Plan** : `_work/reports/planner-20261026-154731.md` ; décisions D2–D7 (GATE 2 LOT-3) ; relevé matériel V-0 : `_work/reports/deployer-20261026-170000.md`.

**Acquis #23 (non rejoués à l'identique, référencés)** : identité par MAC (`scripts/btmux-adapters.sh`, `btmux-adapters(.path/-identity).service`),
alias/classe par rôle (`btmux` `0x6c0404` / `btmux-hp` `0x6c010c`), **débranchement/rebranchement** (identité restaurée en 2–3 s), **permutation logique**
des rôles (`--confirm`). La campagne ne les revérifie que **sur dongle réel dans un parcours complet** et ajoute ce que #23 n'a pas joué :
**permutation physique des ports + reboot**, appairage du PC sur `hci-src`, vue téléphone.

**Conditions de mesure à consigner (rapports)** : Pi 4 ; alimentation ; **Wi-Fi actif (D2 : pas de `disable-wifi`, Ethernet non requis)** ; hub USB 2.0 interne partagé
(les deux UB500 sont sur 1-1.1 / 1-1.2 du bus USB 2) ; codecs **SBC + aptX** (**AAC indisponible** sur Ubuntu 26.04).

**Périmètre retiré** : la **latence bout en bout** (impulsion source → sortie casque) n'est **plus** dans cette campagne (D3, reportée dans **#28**, v0.3.0).
#8 conserve : bascules (source→source, A2DP→HFP) et dropouts.
Cette checklist **valide les preuves et les rapports** produits par les séances. Elle reprend les colonnes « UB500 bi » des
procédures `05-exposure`, `06-hfp-dual-role`, `07-routing` (références `§6` de chacune) sans les dupliquer.

> **Règle de statut** : tant que cette campagne n'est pas jouée, les rapports 05/06/07/08 et les ADR 0001/0003 restent
> **« provisoire — validé sur BT interne »**. Cette procédure décide si le statut est **levé** ou **maintenu** (avec motif).

## Prérequis (préparation dev-backend, hors séance)

- [ ] Réception des 2 UB500 : `tests/procedures/install/pi-qualif/` scénario 7 (réception + bascule `disable-bt`) **PASS**, tableau MAC ↔ rôle ↔ port complété
- [ ] `BTMUX_BT_MODE=dongle` ; script `docs/install-pi.md` §8 : 2 contrôleurs USB, 0 UART
- [ ] **Pi 4** confirmé (`/proc/device-tree/model`), hostname `pi-qualif` vérifié (jamais piClock) ; relevé V-0 : 2 × `2357:0604`, 0 contrôleur UART, `disable-bt` posé
- [ ] **Alimentation** : alimentation officielle 5,1 V / 2,5 A (ou hub alimenté) ; **sous-tension** surveillée via hwmon `rpi_volt` (`in0_lcrit_alarm` = 0, `vcgencmd get_throttled` indisponible : `/dev/vcio` absent) et `dmesg` sans `under-voltage` / `-110` / `-71` ; **arrêt** si alarme
- [ ] **Wi-Fi actif consigné** (D2) comme condition de mesure (pas d'`disable-wifi`) ; Ethernet non requis
- [ ] Config bi valide (`btmuxd --check-config` code 0) ; **`btmuxd` actif** ; `btmux-adapters.service` actif ; `GET /api/controllers` = 2 contrôleurs présents ; `roles.conf` en place
- [ ] **Coexistence `btmuxd`** : les spikes n'enregistrent **pas** leur propre agent BlueZ (`session.sh`) ; **fenêtres d'appairage uniquement via `btmuxctl pairing open|close`** ; `link_guard.py` cohérent avec le garde-fou du daemon (pas de double `block`) ; `preflight.sh` vert
- [ ] `wpctl status` sain ; `watch_hci.sh` lancé **une fois par `hciN`** ; `link_guard.py` : plafond **par adaptateur** (`block`)
- [ ] Appareils : PC Windows (Teams), téléphone, casque ; fenêtre d'appairage ouverte uniquement pendant la séance
- [ ] Preuves dans `_work/tmp/campagne-ub500/` (sous-dossiers `s1/`, `s2/`) ; **arrêt immédiat** au premier `tx timeout`/`Frame reassembly`

## S1 — Identité, rôles, exposition, routage (≈ 1 h 15)

### S1.1 #12 — Identité par adaptateur

| # | Contrôle | Preuve attendue | OK |
|---|----------|-----------------|----|
| S1.1.1 | Windows et téléphone voient **`btmux` seul** (fenêtre `sources` ouverte via `btmuxctl`) ; **vue téléphone** (scan) jamais jouée en #23 | Captures « Bluetooth et appareils » ; scan téléphone | |
| S1.1.2 | Le casque voit **`btmux-hp`** (nom du rôle `headsets`), jamais `btmux` ; **`btmux-hp` non visible côté Windows** fenêtre `headsets` fermée | Capture / `bluetoothctl scan` côté casque ou journal d'appairage | |
| S1.1.3 | Classes **réelles** : `sources` = `0x6c0404` (bits Capturing/Telephony ajoutés par HFP, cible initiale `0x240404`), `headsets` = `0x6c010c` ; alias/classe par rôle = **acquis #23** (contrôle de cohérence seulement) | `bluetoothctl show` / `btmgmt info` par contrôleur ; écart à `0x240404` documenté | |
| S1.1.4 | **Permutation PHYSIQUE** des deux dongles (échange des ports 1-1.1 ↔ 1-1.2, **un à la fois**), **puis reboot** : les rôles suivent les **MAC**. Non joué en #23 (débranchement + permutation **logique** `--confirm` seulement) | Tableau MAC ↔ rôle ↔ port avant/après ; alias/classe restaurés par `btmux-adapters.service` ; reconnexion pilotée du casque et du PC (`btmuxctl device connect`) ; **état d'origine rétabli** ensuite (ports remis, un à la fois) | |
| S1.1.5 | Reboot : appairages conservés ; reconnexion **pilotée** par `btmuxctl device connect` (reconnexion auto non garantie) | `reboot_check.sh` ×2 ; `GET /api/controllers` | |
| S1.1.6 | Référence acquis #23 : débranchement/rebranchement d'un dongle → identité restaurée (2–3 s, jusqu'à 60–70 s si double ré-énumération) | Renvoi au rapport QA #23 ; limite « un dongle à la fois » citée dans `12-adapters.md` | |

### S1.2 #13 — Rôles par adaptateur

| # | Contrôle | Preuve attendue | OK |
|---|----------|-----------------|----|
| S1.2.1 | SDP/profils exposés par **chaque** adaptateur (`spikes/t32b/roles_report.sh` ; `sdptool browse local` inutilisable sur BlueZ 5.85) | Dump par `hciN` : `hci-src` = A2DP sink + HFP HF ; `hci-hp` = A2DP source + HFP AG ; comparé à `docs/spikes/05-exposure/sdp-20261023-090731.txt` | |
| S1.2.2 | Investigation WirePlumber 0.5 : propriété d'adaptateur matchable pour `bluez5.roles` ? Sinon fallback « filtrage par le daemon » prototypé (`spikes/13-roles/`) | Résultat documenté ; `roles.conf` modifié **seulement** si règle effective ; `wpctl status`, `pw-dump` | |
| S1.2.3 | Rôle parasite : l'enregistrement HFP étant global au démon BlueZ, HF **et** AG peuvent être annoncés sur les deux adaptateurs — constaté et consigné (risque fort connu) | Dump SDP ; profils effectivement négociés par appareil et par contrôleur | |
| S1.2.4 | `roles.conf` final (si règle effective) dans `config/wireplumber/` ; son **packaging `.deb`** = issue v0.3.0 (hors LOT-3) | Chemin + diff relu, ou « aucune règle effective » | |
| S1.2.5 | **Codecs** relevés des deux côtés : **SBC + aptX** (PC → Pi, téléphone → Pi, Pi → casque) ; **AAC non disponible** (`libspa` sans AAC) = « non disponible », pas un échec | `pw-dump` / `btmon` | |

### S1.3 #5 étapes 3–6 en bi (voir `05-exposure` §6)

- [ ] 05 §6.1 → §6.5 joués (PC + téléphone sur `hci-src`, casque sur `hci-hp`, audio 5 min, reboot) — colonne « UB500 bi » cochée

### S1.4 #7 critère 1 en bi (voir `07-routing` §6)

- [ ] 07 §6.1 → §6.7 joués : 2 sources réelles + casque, bascule réel ↔ réel ×10, **p95 < 1 s**, tenue 10 min, FL/FR, `restart pipewire wireplumber` BT connecté

### S1.5 Rapports S1

| # | Contrôle | OK |
|---|----------|----|
| S1.5.1 | `docs/spikes/12-adapters.md` et `13-roles.md` : sections Objectif · Matériel/versions · Protocole · Résultats · Limites · Décision/Verdict · À revalider ; **verdict explicite** (OUI/NON/RÉSERVES). #12 : **D5** — `scripts/btmux-adapters.sh` accepté comme livrable (pas de script jetable ; `spikes/12-adapters/README.md` de renvoi) | |
| S1.5.2 | § « Revalidation UB500 » ajoutée à `05` et `07`, statut provisoire levé ou maintenu, motivé | |
| S1.5.3 | Hub USB 2.0 partagé, **Wi-Fi actif**, alimentation/sous-tension (hwmon `rpi_volt`) cités dans les conditions de mesure | |
| S1.5.4 | Masquage avant commit (dépôt public) : `python spikes/common/mask_evidence.py --pi-mac <MAC> --check docs/spikes` retourne 0 ; `grep -rE '([0-9A-Fa-f]{2}[:_-]){5}[0-9A-Fa-f]{2}' docs/spikes` ne montre que les MAC du Pi/dongles | |

## S2 — Voix et mesures (≈ 1 h)

### S2.1 #6 — Double rôle HFP, double SCO (voir `06-hfp-dual-role` §6)

- [ ] 06 §6.1 → §6.8 joués : HF `hci-src` + AG `hci-hp`, double SCO, codecs, capacité SCO par dongle, 5 bascules Teams, 10 min
- [ ] **Décision backend** (natif / oFono / hybride) consignée ; **D6** : oFono installé **seulement en S2** si l'inventaire natif est insuffisant (essai du rôle HF documenté), puis **retiré** et état du Pi restauré (preuve : paquet absent)

### S2.2 #8 — Bascules et fiabilité du double saut

> **Latence bout en bout retirée** (D3) : plus d'impulsion/captation acoustique, ni de tableau `quantum` → latence ; reportée dans **#28** (v0.3.0).
> `08-latency.md` le mentionne comme « non mesuré, reporté (#28) » et ne porte **aucun verdict de latence** (le critère < 300 ms n'est ni validé ni infirmé).

| # | Contrôle | Preuve attendue | OK |
|---|----------|-----------------|----|
| S2.2.1 | Bascule source → source mesurée (consolide S1.4) | Médiane/p95 vs **< 1 s** | |
| S2.2.2 | Bascule A2DP → HFP (Teams) (consolide S2.1, 5 bascules) | Durée vs **< 2 s** | |
| S2.2.3 | Entrée A2DP **SBC et aptX** : comportement de chaque codec (forçage côté Pi) ; AAC « non disponible » | Codec effectif par configuration | |
| S2.2.4 | **Dropouts 2 × 30 min = S3 optionnelle, sans présence (D7)** : lancée en fin de S2 ; A2DP seul puis A2DP + HFP (`xrun_log.py --minutes 30`) ; arrêt et remise en état pilotés | Comptage `xrun`, `btmon`/`pw-top` ; si S3 non jouée : durée réelle (10 min) et limite consignées, critère « partiel » | |
| S2.2.5 | Conditions consignées : **Wi-Fi actif**, hub USB 2.0 unique, alimentation/sous-tension, codec A2DP/SCO | Dans `08-latency.md` | |

### S2.3 Rapports S2 et synthèse #19

| # | Contrôle | OK |
|---|----------|----|
| S2.3.1 | `06-hfp-dual-role.md` : sections obligatoires, **décision backend**, § bi-adaptateur (#15), statut provisoire levé/maintenu | |
| S2.3.2 | `08-latency.md` : bascules (1000 / 2000 ms) et dropouts vs `testing.perf`, **verdict bi explicite** (viable / réserves / insuffisant) ; latence bout en bout = « reportée (#28) », sans verdict | |
| S2.3.3 | `19-revalidation-ub500.md` (synthèse) : tableau récapitulatif de tous les contrôles « UB500 bi » (OK / KO / non joué), **verdict bi** global, statut de chaque ADR concerné | |
| S2.3.4 | Cohérence croisée 05/06/07/08/12/13/19 : aucun verdict contradictoire avec les preuves ; incidents (`tx timeout`, reset contrôleur) cités | |
| S2.3.5 | Masquage des preuves (même contrôle que S1.5.4) | |

## Critères de validation

- [ ] S1 et S2 : tous les contrôles OK, ou écarts documentés avec impact sur le verdict
- [ ] Décision **levée / maintenue** du statut « provisoire » écrite pour : rapports 05, 06, 07, 08 ; ADR 0001, 0003
- [ ] Verdict bi-adaptateur tranché (viable / réserves / insuffisant) et répercuté sur le backlog (#15)
- [ ] S3 : jouée (2 × 30 min) ou non jouée avec limite consignée — **jamais bloquante** (optionnelle)
- [ ] Pi remis en état d'origine : dongles dans leurs ports, rôles, fenêtres fermées, appareils déconnectés, oFono retiré
- [ ] Aucune modification hors `spikes/`, `docs/spikes/`, `config/wireplumber/`, preuves
- [ ] Verdict QA : [ ] VALIDATED  [ ] NOT VALIDATED — motif : ______

## Notes QA

