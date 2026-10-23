# Procédure QA — Spike #5 : exposition « casque générique » en mono-adaptateur

**Issue** : #5 · **Milestone** : v0.1.0 · **Tags** : `hardware` (manuel, jamais en CI) · **Testeur** : QA · **Date** : ____
**Cible** : pi-qualif (`ubuntu@<IP-du-Pi>`), `hci0` **Bluetooth interne** BCM43430A1, MAC `B8:27:EB:1A:2E:D6`, Wi-Fi actif, pas d'AAC.
**Pilotage** : la procédure de séance (étapes à faire par l'utilisateur) est dans `_work/handoff/dev-backend-spike05-*.md` ;
cette checklist **valide les preuves et le rapport** après la séance. Scripts : `spikes/05-exposure/`.

> **Mention obligatoire** : tous les résultats de ce spike sont **provisoires — à revalider avec dongle RTL8761B**
> (variante Bluetooth interne, `docs/install-pi.md` §10 : UART, antenne partagée avec le Wi-Fi, BT 4.2). Un PASS ici ne
> lève pas le risque pour la cible.

## Prérequis

- [ ] `docs/install-pi.md` §9 à jour (MAC, versions BlueZ/PipeWire/WirePlumber) ; service `btmuxd` indifférent (non requis)
- [ ] Un PC Windows (idéalement le PC pro verrouillé, appairage via l'interface standard — **aucun logiciel côté source**), un téléphone, un casque Bluetooth
- [ ] Dossier de preuves `_work/tmp/spike-05/` créé (captures, sorties de commandes, journaux horodatés)
- [ ] Fenêtre d'appairage ouverte **uniquement** pour la séance (`pairable`/`discoverable` avec timeout), refermée ensuite

## 1. Outillage (critère 1)

| # | Contrôle | Preuve attendue | OK ? |
|---|----------|-----------------|------|
| 1.1 | Résolution MAC → index hci | Sortie de `resolve_adapter.py B8:27:EB:1A:2E:D6` donne `hci0` / `/org/bluez/hci0` (via `Adapter1.Address`, pas de `hci0` codé en dur) | |
| 1.2 | Identité posée | `bluetoothctl show` : `Name: btmux`, `Class: 0x00240404`, `Pairable`/`Discoverable` conformes à la fenêtre | |
| 1.3 | Enregistrements SDP relevés | Fichier SDP (`sdptool browse local` ou `bluetoothctl show` + `btmon`) dans `_work/tmp/spike-05/` : UUIDs A2DP sink `110B`, source `110A`, AVRCP, HFP HF `111E`, HFP AG `111F` listés | |
| 1.4 | Scripts jetables et lisibles | `spikes/05-exposure/` exécutable ; aucun code dans `src/` ; `ruff` vert | |

## 2. Vue du PC Windows et du téléphone (critère 2)

| # | Contrôle | Preuve attendue | OK ? |
|---|----------|-----------------|------|
| 2.1 | Windows voit « btmux » comme **casque audio** | Capture « Bluetooth et appareils » : icône casque/audio, un **seul** appareil « btmux » | |
| 2.2 | Appairage standard Windows | Aboutit sans PIN exotique ni outil tiers ; `Device1` Paired/Trusted dans le journal `pair_watch.py` | |
| 2.3 | Services affichés par Windows | Capture « Périphériques et imprimantes » > Services (Audio Sink, Mains libres, télécommande…) ; **noter** tout service inattendu (AG / A2DP Source exposés) | |
| 2.4 | A2DP + HFP s'établissent (Windows) | Journal : `MediaTransport1` A2DP actif ; profil Mains libres connecté ; sortie audio Windows sélectionnable | |
| 2.5 | Comportement Windows : pas de double périphérique, pas de mauvais profil, pas de refus | Observation consignée (oui/non + capture si anomalie) | |
| 2.6 | Même vérification depuis le **téléphone** | Capture / note : « btmux » = casque, appairage OK, A2DP + HFP | |
| 2.7 | Lecture A2DP **entrante** | Audio du PC (puis du téléphone) joué vers le Pi : transport A2DP sink actif (`pw-dump`/`wpctl status`), niveau audible ou flux mesuré | |

## 3. Casque sur le même adaptateur (critère 3)

| # | Contrôle | Preuve attendue | OK ? |
|---|----------|-----------------|------|
| 3.1 | Source connectée (PC ou téléphone) avant l'étape | `bluetoothctl info <mac source>` : `Connected: yes` | |
| 3.2 | Casque appairé, **Pi initiateur** de la connexion | `bluetoothctl connect <mac casque>` réussit (journal `pair_watch.py`) ; le Pi, pas le casque, a initié | |
| 3.3 | Connexion **simultanée** source + casque | `bluetoothctl devices Connected` liste les deux ; la source reste connectée (pas de déconnexion/changement de rôle forcé) | |
| 3.4 | Lecture A2DP **sortante** vers le casque | Transport A2DP source actif vers le casque ; audio audible | |
| 3.5 | Source et casque tiennent ensemble ≥ 5 min | Aucune coupure ; sinon horodatage + cause suspectée (coexistence Wi-Fi 2,4 GHz notée) | |

## 4. Persistance après reboot (critère 4)

| # | Contrôle | Preuve attendue | OK ? |
|---|----------|-----------------|------|
| 4.1 | `sudo reboot` puis `reboot_check.sh` | Sortie dans `_work/tmp/spike-05/` | |
| 4.2 | Appairages conservés | `bluetoothctl devices Paired` : PC, téléphone, casque toujours listés | |
| 4.3 | `Trusted: yes` conservé | `bluetoothctl info <mac>` pour chaque appareil | |
| 4.4 | Reconnexion automatique observée | Au moins un appareil (source ou casque) se reconnecte seul ; délai relevé ; sinon constat explicite « pas de reconnexion auto » | |
| 4.5 | Identité restaurée | `Name`/`Class` toujours `btmux` / `0x240404` après reboot (ou écart signalé : réglage volatil à appliquer par btmuxd) | |

## 5. Contrôle du rapport `docs/spikes/05-exposure.md` (critère 5)

| # | Contrôle | OK ? |
|---|----------|------|
| 5.1 | Contient les sections : **Objectif · Matériel/versions · Protocole · Résultats · Limites · Décision/Verdict · À revalider en bi-adaptateur** | |
| 5.2 | Matériel/versions : Pi 3, BCM43430A1, MAC, noyau, BlueZ, PipeWire, WirePlumber, OS (cohérents avec `docs/install-pi.md` §9) | |
| 5.3 | Porte la mention **« provisoire — à revalider avec dongle RTL8761B »** (en tête et dans le verdict) | |
| 5.4 | Résultats : chaque contrôle des §2–§4 renvoie à une preuve (annexe ou `_work/tmp/spike-05/`) ; aucun résultat sans preuve | |
| 5.5 | **Verdict explicite** sur « casque générique » : `OUI` / `NON` / `RÉSERVES` (une seule valeur, justifiée) | |
| 5.6 | Recommandations : classe et nom, filtrage éventuel des enregistrements SDP, `bluez5.roles` | |
| 5.7 | Limites : BT interne (UART, antenne partagée Wi-Fi, BT 4.2), un seul contrôleur, SCO/HFP non testé si c'est le cas | |
| 5.8 | « À revalider en bi-adaptateur » : liste des points dépendant du dongle / de la v0.2.0 | |
| 5.9 | Annexes : captures Windows et sorties SDP jointes ou référencées par chemin | |
| 5.10 | Cohérence : verdict compatible avec les observations §2–§3 (pas de PASS affiché malgré un échec constaté) | |
| 5.11 | **Masquage avant commit** (dépôt public) : les preuves copiées sous `docs/spikes/` passent par `spikes/common/mask_evidence.py` ; `python spikes/common/mask_evidence.py --pi-mac <MAC du Pi> --check docs/spikes` retourne 0 et `grep -rE '([0-9A-Fa-f]{2}[:_-]){5}[0-9A-Fa-f]{2}' docs/spikes` ne montre que la MAC du Pi ; aucun appareil tiers du voisinage (scan) ni nom d'appareil personnel dans `pair.jsonl` | |

## 6. Revalidation UB500 bi — étapes 3–6 en bi-adaptateur (séance S1, `revalidation-ub500/`)

Colonne « UB500 bi » : PC + téléphone sur `hci-src` simultanément, puis casque sur `hci-hp` (= 3 liens ACL répartis sur 2 radios).

| # | Contrôle | Preuve attendue | OK UB500 bi |
|---|----------|-----------------|-------------|
| 6.1 | PC **et** téléphone connectés simultanément à `btmux` (`hci-src`) | `bluetoothctl devices Connected` : 2 sources ; chacun voit **un seul** casque `btmux` | |
| 6.2 | Casque connecté par le Pi sur `hci-hp` pendant que les 2 sources sont connectées | 3 liens ACL, aucun `tx timeout` ; le casque voit `btmux-hp` (source) | |
| 6.3 | Audio 5 min : source → Pi → casque | Aucune coupure | |
| 6.4 | Reboot : appairages (`Paired`/`Trusted`) conservés, reconnexion automatique, **alias et classe de chaque adaptateur restaurés** par `btmux-adapters.service` | `reboot_check.sh` ×2 | |
| 6.5 | Rapport `docs/spikes/05-exposure.md` § « Revalidation UB500 » : statut provisoire **levé ou maintenu**, preuves masquées (5.11) | | |

## Critères de validation

- [ ] §1 à §4 : tous les contrôles OK, ou écarts documentés dans le rapport avec impact sur le verdict
- [ ] §5 : rapport complet, verdict explicite, mention « provisoire » présente
- [ ] Aucune modification hors `spikes/05-exposure/`, `docs/spikes/05-exposure.md`, preuves ; fenêtre d'appairage refermée
- [ ] Verdict QA : [ ] VALIDATED  [ ] NOT VALIDATED — motif : ______

## Notes QA

