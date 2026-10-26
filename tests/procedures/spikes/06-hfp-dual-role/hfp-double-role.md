# Procédure QA — Spike #6 : double rôle HFP (HF + AG) sur un adaptateur

**Issue** : #6 · **Milestone** : v0.1.0 · **Tags** : `hardware` (manuel, jamais en CI) · **Testeur** : QA · **Date** : ____
**Cible** : pi-qualif (`ubuntu@<IP-du-Pi>`), `hci0` **BT interne** BCM43430A1.
**Séance (utilisateur)** : `_work/handoff/dev-backend-spike06-*.md`. Code : `spikes/06-hfp-dual-role/`. Rapport : `docs/spikes/06-hfp-dual-role.md`.

> **Mention obligatoire** : **provisoire — à revalider avec dongle UB500 (T3.2b)**. Version **réduite** jouée maintenant :
> inventaire de l'API téléphonie, RFCOMM HF + AG simultanés (≤ 2 liens ACL : PC en HFP + casque en HFP AG), **un seul lien
> SCO à la fois**. Le **double SCO simultané** est reporté en T3.2b. Wi-Fi conservé, pas d'Ethernet (condition de mesure).
> Condition « SCO over HCI » : le routage SCO du Pi 3 est HCI (compteur `sco:` en hausse via l'UART, `docs/spikes/05-exposure.md`
> § Résultats ; commande `0x3f 0x1d` dans `docs/install-pi.md` §10) — **qualité de la voix non testée avant ce spike**.

**Colonnes** : « Interne » = jouable maintenant ; « UB500 » = reporté en T3.2b (`⏭` reporté, `—` sans objet).

## Prérequis et garde-fous

- [ ] ≤ 2 liens ACL à tout moment (PC + casque) ; `dmesg -w` surveillé, **arrêt au premier `tx timeout` / `Frame reassembly`**
- [ ] Aucune étape avec **deux SCO simultanés** en BT interne (interdit)
- [ ] Preuves dans `_work/tmp/spike-06/` ; routage SCO d'origine (`0x3f 0x1d`) relevé avant et **restauré** après tout essai de modification (volatil)
- [ ] oFono installé **seulement** si l'inventaire natif est jugé insuffisant (sinon `⏭`/N/A, justifié)

## 1. Critère 1 — Scénario HF (source) + AG (casque), voix

| # | Contrôle | Preuve attendue | Interne | UB500 bi | OK int. | OK UB500 bi |
|---|----------|-----------------|---------|-------|---------|----------|
| 1.1 | PC connecté en HFP (HF côté `btmux`) et casque connecté en HFP AG, **sans audio** | `bluetoothctl devices Connected` = 2 ; RFCOMM HF + AG établis (journal `btmon`/spike) | ✔ | ✔ | | |
| 1.2 | **SCO PC seul** : micro Teams ouvert, parler/écouter | Lien SCO ouvert (`btmon`), voix compréhensible dans les deux sens (boucle locale PipeWire), **codec relevé** (mSBC ou CVSD) | ✔ | ✔ | | |
| 1.3 | **SCO casque seul** : profil `headset-head-unit` forcé côté Pi, voix test | Lien SCO ouvert, voix audible, codec relevé | ✔ | ✔ | | |
| 1.4 | **Double SCO simultané** : voix bout en bout PC ↔ casque via lien PipeWire manuel | Voix dans les deux sens, deux codecs relevés | ⏭ | ✔ | | |
| 1.5 | Qualité de la voix évaluée (note subjective + artefacts : coupures, écho) | Note + remarques dans le rapport ; un échec en interne est relevé sans valoir verdict définitif | ✔ | ✔ | | |

## 2. Critère 2 — Capacité SCO

| # | Contrôle | Preuve attendue | Interne | UB500 bi | OK int. | OK UB500 bi |
|---|----------|-----------------|---------|-------|---------|----------|
| 2.1 | `sco_capacity.sh` exécuté (`btmgmt info`, `btmon`, compteurs `hciconfig`) | Sortie archivée ; SCO MTU, route SCO (HCI/PCM, `0x3f 0x1d`) relevés | ✔ | ✔ | | |
| 2.2 | Nombre de liens SCO tenus **en parallèle** | Valeur mesurée et méthode | ⏭ (1 seul essayé) | ✔ | | |

## 3. Critère 3 — Stabilité et bascules

| # | Contrôle | Preuve attendue | Interne | UB500 bi | OK int. | OK UB500 bi |
|---|----------|-----------------|---------|-------|---------|----------|
| 3.1 | Stabilité ≥ 10 min en HFP | Aucune erreur HCI, aucune coupure | ⏭ | ✔ | | |
| 3.2 | 5 bascules A2DP ↔ HFP déclenchées par Windows (ouverture/fermeture micro Teams) | Journal des 5 transitions, durées | ⏭ | ✔ | | |

## 4. Critère 4 — Inventaire de l'API téléphonie (backend natif)

| # | Contrôle | Preuve attendue | Interne | UB500 bi | OK int. | OK UB500 bi |
|---|----------|-----------------|---------|-------|---------|----------|
| 4.1 | `inventory_telephony.py` : propriétés/événements D-Bus BlueZ et PipeWire disponibles | Fichier `out/inventory.*` (propriétés, signaux, indicateurs d'appel, commandes AT accessibles) | ✔ | — | | |
| 4.2 | Jugement **« suffisant pour #10 : OUI / NON »**, justifié par l'inventaire | Conclusion dans le rapport, avec manques listés | ✔ | — | | |
| 4.3 | Si NON : même scénario avec **oFono** (rôle HF) | Résultat consigné ; si OUI → `N/A` motivé | ✔ si requis | ✔ si requis | | |

## 5. Contrôle du rapport `docs/spikes/06-hfp-dual-role.md` (critère 5)

| # | Contrôle | OK ? |
|---|----------|------|
| 5.1 | Sections : **Objectif · Matériel/versions · Protocole · Résultats · Limites · Décision/Verdict · À revalider avec le dongle (UB500)** | |
| 5.2 | Mention **« provisoire — à revalider avec dongle UB500 (T3.2b) »** en tête et dans la décision | |
| 5.3 | **Décision explicite** : `natif` / `oFono` / `hybride` (une seule valeur), fondée sur l'inventaire + un SCO par côté, marquée provisoire | |
| 5.4 | § « À revalider avec le dongle » **explicite** : double SCO simultané, stabilité ≥ 10 min, 5 bascules A2DP ↔ HFP, nombre de liens SCO du RTL8761BU, et ce qui est à revalider en bi-adaptateur (#15) | |
| 5.5 | La condition **« SCO over HCI »** est citée avec sa **source** (relevé `sco:` / `0x3f 0x1d`, `docs/spikes/05-exposure.md`, `docs/install-pi.md` §10) et son statut (audio testé : oui/non) | |
| 5.6 | Rapport **partiel accepté** par QA seulement si 5.4 et 5.5 sont satisfaits | |
| 5.7 | Codec SCO relevé de chaque côté (mSBC/CVSD) ou « non relevé » justifié | |
| 5.8 | Limites : UART, ≤ 2 ACL, antenne partagée Wi-Fi 2,4 GHz, BT 4.2, un seul SCO à la fois | |
| 5.9 | Cohérence décision ↔ observations (incident `tx timeout` éventuel cité) | |
| 5.10 | Entrées pour #10 et ADR 0001 (politique de profils HFP) identifiées | |
| 5.11 | **Masquage avant commit** (dépôt public) : `python spikes/common/mask_evidence.py --pi-mac <MAC du Pi> --check docs/spikes` retourne 0 ; `grep -rE '([0-9A-Fa-f]{2}[:_-]){5}[0-9A-Fa-f]{2}' docs/spikes` ne montre que la MAC du Pi ; aucun nom d'appareil personnel ni appareil tiers | |

## 6. Revalidation UB500 bi — double SCO (séance S2, `revalidation-ub500/`)

Topologie : PC (Teams) en HFP sur `hci-src` (rôle **HF** côté `btmux`) ; casque en HFP **AG** sur `hci-hp`. 1 SCO par radio.

**Conditions (LOT-3)** : Pi 4, `btmuxd` résident (fenêtres via `btmuxctl` uniquement), **Wi-Fi actif** (D2, consigné), sous-tension
surveillée via hwmon `rpi_volt`. Décision **D6** : oFono peut être installé sur pi-qualif **uniquement en S2** si l'inventaire natif
est insuffisant, puis **retiré** en fin de séance (état d'origine vérifié). Corps de l'issue #6 amendé (bi-adaptateur ; mono = repli non éprouvé).

| # | Contrôle | Preuve attendue | OK UB500 bi |
|---|----------|-----------------|-------------|
| 6.1 | Voix bout en bout **PC ↔ casque** via lien PipeWire manuel, deux SCO simultanés | Voix dans les deux sens ; deux liens SCO (`btmon`, un par `hciN`) | |
| 6.2 | Codec SCO relevé de chaque côté | mSBC ou CVSD pour `hci-src` et `hci-hp` | |
| 6.3 | Nombre de liens SCO tenus par dongle (`sco_capacity.sh` sur chaque `hciN`) | Valeur mesurée par radio ; lever R1 (1 seul SCO/RTL8761BU) | |
| 6.4 | eSCO mSBC (`hci-hp`) + A2DP sortant simultanés sur le même `hci-hp` | Comportement observé et consigné (R1) | |
| 6.5 | Stabilité ≥ 10 min en HFP | 0 coupure, 0 erreur HCI | |
| 6.6 | 5 bascules A2DP ↔ HFP déclenchées par Windows (micro Teams) | Journal des 5 transitions, durées | |
| 6.7 | Inventaire API téléphonie complété (indicateurs d'appel, AT), à vide puis pendant l'appel ; **oFono** (D6) testé **seulement** si l'inventaire natif est insuffisant, puis **désinstallé** (`dpkg -l ofono` vide) | `out/inventory.*` ; décision ; état Pi restauré | |
| 6.8 | Rapport `docs/spikes/06-hfp-dual-role.md` : **décision backend définitive** (natif / oFono / hybride) ou provisoire maintenue, motivée ; suites reportées en **v0.3.0** (ex-#15 remplacé par #19) | | |

## Critères de validation

- [ ] Colonne « Interne » : tous les contrôles jouables OK ou écarts documentés
- [ ] Colonne « UB500 » : cases `⏭` toutes reprises dans le rapport § « À revalider » (non bloquant pour le GATE du LOT-2.2)
- [ ] §5 complet ; aucune modification hors `spikes/06-hfp-dual-role/`, `docs/spikes/06-hfp-dual-role.md`, preuves
- [ ] Verdict QA : [ ] VALIDATED (provisoire)  [ ] NOT VALIDATED — motif : ______

## Notes QA

