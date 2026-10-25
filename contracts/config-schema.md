# Contrat — Schéma de configuration `/etc/btmux/config.yaml` (v0.1.0)

> Contrat « contract-first » du composant `config` (issue #4). Référence pour `dev-backend` (modèle typé,
> `btmuxd --check-config`), `test-writer` (tests de validation) et `config/config.example.yaml` (#2).
> Diverge volontairement de `docs/cadrage.md` §4.6 (`adapters: {sources:, headsets:}`) — décision du
> 2026-10-13 : liste à `roles`, même structure en mono (v0.1.0) et bi-adaptateur (v0.2.0, #14).
> Le cadrage est aligné en #11.

## Schéma

```yaml
adapters:                              # liste, 1 entrée en v0.1.0 (2 en v0.2.0)
  - mac: "AA:BB:CC:00:00:01"           # obligatoire — identification par MAC, jamais hci0/hci1
    name: "btmux"                      # obligatoire — nom Bluetooth annoncé (1..248 octets UTF-8, sans caractère de contrôle — V12)
    roles: [sources, headsets]         # obligatoire — sous-ensemble non vide de {sources, headsets}
devices:                               # liste, peut être vide
  - { mac: "...", alias: "pc-pro",    kind: source,  priority: 10 }
  - { mac: "...", alias: "tel-perso", kind: source,  priority: 20 }
  - { mac: "...", alias: "xm5",       kind: headset }
default_routes:                        # dict alias casque -> alias source ; peut être vide/absent
  xm5: pc-pro
api:                                   # optionnel ; défauts ci-dessous
  listen: "0.0.0.0:8088"               # défaut "0.0.0.0:8088" — forme host:port
  token_file: /etc/btmux/token         # défaut /etc/btmux/token — chemin absolu
mqtt:                                  # optionnel ; défaut { enabled: false }
  enabled: false
```

## Règles de validation (code retour `--check-config` = 2 si l'une échoue)

| # | Règle | Message attendu (préfixe, journald-friendly, une ligne) |
|---|-------|----------------------------------------------------------|
| V1 | `mac` (adaptateurs et appareils) : `^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$`, normalisée en majuscules | `config: adapters[0].mac: invalid MAC address '...'` |
| V2 | `adapters` liste (**peut être vide depuis #23** — rôles affectés ensuite par l'API) ; `roles` sous-ensemble non vide de `{sources, headsets}`, sans doublon | `config: adapters[i].roles: unknown role '...'` |
| V3 | Chaque rôle `sources` et `headsets` porté par **au plus un** adaptateur (**#23** : « exactement un » devient « au plus un » ; un rôle non couvert = daemon en état `role_unassigned`, appairage de ce rôle refusé 409) | `config: role 'headsets' must be provided by at most one adapter (found N)` |
| V4 | ~~v0.1.0 : `len(adapters) > 1` refusé~~ **Levée le 2026-10-23 (validée au GATE 2 v0.2.0)** : 1 **ou** 2 adaptateurs acceptés ; `len(adapters) > 2` refusé | `config: at most 2 adapters are supported (found N)` |
| V5 | `devices[].alias` uniques ; `devices[].mac` uniques ; alias `^[a-z0-9][a-z0-9-]{0,31}$` | `config: devices: duplicate alias 'xm5'` |
| V6 | `kind ∈ {source, headset}` ; `priority` entier ≥ 0, optionnel, **autorisé seulement** pour `kind: source` (défaut 100) | `config: devices[2].priority: only allowed for kind 'source'` |
| V7 | `default_routes` : clé = alias d'un `headset` existant, valeur = alias d'une `source` existante | `config: default_routes: unknown headset alias '...'` |
| V8 | `api.listen` = `host:port` (port 1..65535) ; `api.token_file` chemin absolu | `config: api.listen: expected host:port` |
| V9 | Clés inconnues refusées à tous les niveaux (strict) | `config: unknown key '...' in devices[0]` |
| V10 | Fichier absent / YAML invalide → code 2, message `config: cannot read '<path>': ...` | |
| V12 | `adapters[].mac` **uniques** entre adaptateurs ; `adapters[].name` : 1..248 octets UTF-8, **sans caractère de contrôle ni séparateur** (catégories Unicode `Cc Cf Cs Co Cn Zl Zp` refusées) — ajouté le 2026-10-23 (#14, f554edb) | `config: adapters[1].mac: duplicate adapter mac 'AA:..'` · `config: adapters[0].name: required, 1..248 bytes (UTF-8), no control characters` |

Toutes les erreurs sont collectées et affichées (une par ligne) avant de sortir en code 2 — pas d'arrêt à la première.

## Interface CLI

```
btmuxd --version                      # affiche "btmuxd <version>" ; code 0
btmuxd --config <path> --check-config # valide et sort : 0 (OK, affiche "config OK: <path>") / 2 (erreurs)
btmuxd --config <path>                # v0.1.0 : valide la config (invalide -> erreurs "config: ..." sur stderr, code 2,
                                      # sans démarrer) ; sinon affiche sur stdout
                                      # "btmuxd <version> started — no daemon logic yet (v0.3.0)" et RESTE VIVANT
                                      # (boucle asyncio en attente, aucun accès BlueZ/PipeWire/réseau) ;
                                      # SIGTERM/SIGINT -> affiche "btmuxd <version> stopped", code 0
btmuxctl                              # stub : affiche "btmuxctl: not implemented (v0.3.0)", code 1
```

Défaut de `--config` : `/etc/btmux/config.yaml`.

## Interface Python (module `btmux.config`)

```python
from btmux.config import load_config, ConfigError, Config

cfg: Config = load_config(
    path
)  # lève ConfigError(errors: list[str]) — jamais de dépendance BlueZ/PipeWire
cfg.adapters[0].mac  # "AA:BB:CC:00:00:01" (normalisée)
cfg.adapter_for_role("headsets")  # -> Adapter
cfg.sources / cfg.headsets  # listes triées par priority puis alias
```

## Forme bi-adaptateur (#14, activée en v0.1.0 — révision 2026-10-23)

```yaml
adapters:
  - { mac: "AA:BB:CC:00:00:01", name: "btmux",     roles: [sources]  }   # hci-src : vu comme casque par PC/téléphones
  - { mac: "AA:BB:CC:00:00:02", name: "btmux-src", roles: [headsets] }   # hci-hp  : vu comme source par les casques
```

V3 inchangée (chaque rôle porté par exactement un adaptateur) ; la forme mono (une entrée, deux rôles) reste valide.
`Config.adapter_for_role(role)` renvoie l'adaptateur du rôle ; `cfg.adapters` conserve l'ordre du fichier. Les noms `hci-src`/`hci-hp`
sont des **conventions de documentation** (rôle `sources` / `headsets`), jamais des index `hciN`.

## Clé `pairing` (v0.2.0 — #20/#21, validée au GATE 2 du 2026-10-23)

```yaml
pairing:                       # optionnel ; défauts ci-dessous
  default_duration: 60         # 1..300 s — durée par défaut d'une fenêtre d'appairage
  accept_incoming: true        # agent NoInputNoOutput : accepter les appairages entrants sur l'adaptateur `sources` PENDANT une fenêtre
```

Règle V11 : `default_duration` entier 1..300 ; `accept_incoming` booléen. Hors fenêtre, tout appairage entrant est refusé
quelle que soit la valeur. Rétrocompatible : absence de la clé = défauts.

## Comportement de `btmuxd --config <path>` (CHANGED v0.2.0, validé au GATE 2)

À partir de #20, `btmuxd --config` ne sort plus immédiatement : il valide la config, se connecte à BlueZ (code 3 si un adaptateur
de `adapters[]` est introuvable après 30 s), démarre l'API HTTP (#21) et reste en service jusqu'à SIGTERM/SIGINT (code 0).
`--check-config` est inchangé.

## Affectation des contrôleurs par l'API (#23 — validé au GATE 2 avenant du 2026-10-24 : D1 a, D2 a, D3 b, D4 a, D5 b)

**Fichier d'état** `/var/lib/btmux/adapters.yaml` (`StateDirectory=btmux`, propriétaire `BTMUX_USER`, mode 0640), **même schéma**
que la clé `adapters` de `config.yaml` (liste `{mac, name, roles}`, règles V1–V4, V12) :

```yaml
# écrit par btmuxd (PUT /api/controllers/roles) — ne pas éditer à la main pendant que btmuxd tourne
adapters:
  - { mac: "18:69:45:42:9D:E2", name: "btmux",    roles: [sources]  }
  - { mac: "18:69:45:42:B5:54", name: "btmux-hp", roles: [headsets] }
```

Règles :
- **Précédence** : si le fichier d'état existe et est valide, sa liste `adapters` **remplace** celle de `config.yaml` (`Roles.source = "state"`) ;
  sinon `config.yaml` s'applique (`"config"`) ; un fichier d'état **invalide** est ignoré avec le journal `state_invalid` (repli config, jamais
  d'arrêt). `btmuxd --check-config` valide les deux et affiche la liste effective et sa provenance ; `python -m btmux.config adapters
  [--config …] [--state …]` (utilisé par `btmux-adapters.sh`) imprime la même liste effective (défaut `--state` = `/var/lib/btmux/adapters.yaml`).
- **Écriture atomique** : fichier temporaire dans le même répertoire, `fsync`, `rename` ; jamais d'écriture dans `/etc/btmux/config.yaml`
  (reste propriété de l'administrateur, lecture seule pour le daemon — `ProtectSystem=strict`).
- **L'alias suit le rôle, pas le dongle** (décision utilisateur du 2026-10-24, remplace « repris de `config.yaml` si la MAC y figure ») :
  le `name` écrit dans l'état pour un contrôleur affecté est le **nom du rôle** — `name` de l'entrée de `config.yaml` qui porte ce rôle
  (unique par V3), sinon défaut **`btmux`** (sources) / **`btmux-hp`** (headsets) ; un contrôleur portant les deux rôles prend le nom du rôle
  `sources`. Après une permutation, le nouveau contrôleur `sources` s'annonce donc `btmux` quel que soit son MAC. `Controller.name`
  (API) reste l'alias BlueZ courant et reflète ce nom une fois l'identité appliquée.
- **Identité réappliquée au hotplug** (décision utilisateur du 2026-10-24 ; révision du 2026-10-25 après revue) : quand un contrôleur
  **affecté** réapparaît sur le bus (`InterfacesAdded` de `org.bluez.Adapter1` — rebranchement, reset USB, énumération tardive au boot), le daemon,
  non root, ne peut pas rétablir la classe : il inscrit la MAC dans **`/var/lib/btmux/identity.request`** (journal `identity_requested hci= mac=`) ;
  `btmux-adapters-identity.path` (`PathChanged=`) déclenche **`btmux-adapters-identity.service`** (root, oneshot) qui rejoue
  `btmux-adapters.sh --state … --config … --wait 5 --requests /var/lib/btmux/identity.request` (équivalent à un `--only <MAC>` par ligne valide)
  pour **chaque MAC en attente** : alias et classe du rôle sur les seuls contrôleurs
  réapparus, **sans redémarrage de `btmuxd`** ni coupure de l'API, et **sans toucher aux autres contrôleurs** (une fenêtre d'appairage ouverte
  par le daemon sur un autre contrôleur n'est pas refermée).
  - **Format du fichier** : UTF-8, **une ligne par MAC en attente**, champs séparés par une tabulation, chaque ligne terminée par `\n` :
    `<horodatage ISO-8601 UTC>\t<hciN>\t<MAC majuscules>` — ex. `2026-10-25T07:12:03Z\thci1\t18:69:45:42:B5:54`. **La MAC (3e champ) fait foi** ;
    `hciN` et l'horodatage sont informatifs. Le daemon **réécrit atomiquement l'ensemble des MAC non encore acquittées** (tmp voisin, fsync, rename ;
    débounce ≤ 1 s autorisé pour grouper une salve) : aucune requête n'est perdue quand deux contrôleurs apparaissent ensemble. Mode 0640,
    propriétaire `BTMUX_USER` ; le fichier **existe dès l'installation** (vide) pour que l'unité `.path` le surveille. Fichier vide = rien à faire.
  - **`--requests <fichier>`** (script, lu en root) : refuse tout ce qui n'est pas un **fichier régulier** (lien symbolique, répertoire, absent →
    avertissement, rien n'est traité, code 0) ; lecture bornée (4 Kio) ; lit toutes les lignes, **dédoublonne** les MAC, ignore les lignes invalides
    (avertissement « N ligne(s) invalide(s) » **sans reproduire le contenu**), traite chaque MAC valide comme un `--only`. Rien de valide : code 0.
    **Relecture en fin de passe** (écart QA `qa-20261025-100508` 1) : l'unité `.path` ne relance pas un service déjà actif ; une MAC écrite
    **pendant** la passe (dongles réapparus à quelques secondes d'écart) serait sinon traitée au rattrapage +60 s. Le script relit donc le fichier
    à la fin de chaque passe et, s'il contient des MAC **non encore traitées** dans cette exécution, refait une passe limitée à celles-ci —
    **3 relectures au plus** par exécution (jamais de boucle), MAC déjà traitées ignorées ; délai attendu pour une MAC arrivée en cours de passe :
    **≤ ~10 s** après son écriture.
  - **Codes de sortie et garantie « l'unité ne doit jamais échouer »** (comportement retenu le 2026-10-25, `infra-20261025-090759`) : le script
    garde ses codes — **2** sur configuration/état invalides (comme au boot et à l'`ExecStartPre`), **0** sinon (MAC absente, fichier vide ou
    illisible, `btmgmt` indisponible : avertissements). C'est **l'unité** `btmux-adapters-identity.service` qui porte la garantie :
    `SuccessExitStatus=2` (une configuration invalide est journalisée mais ne met pas l'unité en échec) et `StartLimitIntervalSec=0` (aucune
    limite de déclenchements).
  - **`--only <MAC>`** (répétable) : la passe ne traite que ces MAC (alias du rôle, classe, `bondable off`, `discov no` si la MAC est **affectée**
    dans la liste effective). MAC **non affectée** (hors liste) : seulement fermée (`bondable off`, `discov no`), ni alias ni classe — comme tout
    contrôleur sans rôle. MAC **absente** de `btmgmt info` après `--wait` (déjà redébranchée) ou **invalide** : avertissement une ligne, code **0**.
    Sans `--only`, le comportement complet (tous les contrôleurs) est inchangé (boot, `ExecStartPre`).
  - **Acquittement et vérification différée** (daemon) : une MAC est acquittée quand la classe observée (`PropertiesChanged Class`) est celle
    du rôle, ou abandonnée (voir ci-dessous). **À chaque acquittement ou abandon, le daemon réécrit atomiquement `identity.request` avec les
    seules MAC encore en attente — fichier vide si aucune** (écart QA 2). Cette réécriture déclenche l'unité `.path` : un fichier vide ou sans
    MAC nouvelle fait sortir le script en code 0 sans rien faire (pas de passe inutile, pas de boucle). Après chaque requête, le daemon **contrôle `Class` à +60 s** ; si elle diffère encore
    du rôle, il réémet une requête — **3 tentatives au plus par contrôleur et par épisode** (un épisode = une apparition), puis journal **ERROR
    `identity_giving_up hci= mac= attempts=3`** et abandon jusqu'à la prochaine apparition ou au prochain démarrage du daemon. **Aucune requête ni
    vérification pendant `roles.pending`** (le redémarrage piloté applique l'identité via l'`ExecStartPre`).
  Le daemon ferme lui-même (`Pairable/Discoverable=false`, `Powered=true`) le contrôleur dès son apparition, avant même la passe d'identité.
  Délai attendu rebranchement → classe rétablie : **≤ 10 s**. Garanties : la passe est idempotente ; aucune requête n'est émise au chargement
  initial ni pour un contrôleur non affecté ; pas de boucle (la passe modifie Alias/Class/Pairable ; seule la vérification différée bornée peut
  réémettre) ; un hotplug pendant un redémarrage piloté est couvert par l'`ExecStartPre`. Sans l'unité `.path` (absente/inactive), l'identité
  n'est rétablie qu'au prochain démarrage du daemon (journal `identity_request_failed` si l'écriture échoue — jamais fatal).
  - **Limite documentée** (revue du 2026-10-25, acceptée) : le nom du rôle est lu dans la liste **effective** ; après un `PUT` qui **libère** un
    rôle, l'état ne porte plus d'entrée pour ce rôle et une réaffectation ultérieure reprend le défaut `btmux` / `btmux-hp`, pas le nom
    personnalisé de `config.yaml`. Contournement : supprimer `/var/lib/btmux/adapters.yaml` puis redémarrer, ou nommer les rôles par défaut.
- **Application par redémarrage piloté du service (D3 b)** — séquence :
  1. `PUT` validé (no-op → 200 sans suite) → **écriture atomique** de l'état (échec → 500 `state_write_failed`, séquence abandonnée, rien n'est
     déconnecté, `pending` reste faux) → fenêtre d'appairage fermée, appareils déconnectés si `confirm` → réponse 202 + événement
     `roles {pending:true, restart_expected:true}` ; toute écriture ultérieure répond 409 `change_pending`.
  2. `btmux-adapters.path` (`PathChanged=/var/lib/btmux/adapters.yaml`) déclenche **`btmux-adapters-reload.service`** (root, oneshot), qui ne
     fait que `systemctl restart --no-block btmuxd.service` → arrêt propre (SIGTERM, code 0 ; `ExecStopPost` referme appairage et découverte)
     et relance immédiate (pas de `RestartSec`, ce n'est pas un échec ; `StartLimitBurst` inchangé). L'**identité des contrôleurs** (alias,
     classe, fermeture de **tous** les contrôleurs sans rôle, ≈ 4 s) est appliquée par l'`ExecStartPre` (root) de `btmuxd.service` :
     `btmux-adapters.sh --state … --config … --wait 0`, **à chaque démarrage du daemon** — redémarrage piloté comme repli code 4 (étape 3) ou
     boot. Elle n'est donc appliquée qu'une fois par cycle, et le SIGTERM arrive < 1 s après l'écriture : pas de course avec le repli.
  3. **Repli** : si le daemon n'a pas reçu SIGTERM **30 s** après l'écriture (unité path absente/inactive), il sort en code **4**
     (`RestartForceExitStatus=4` ; `RestartSec=30` s'applique alors — journal `restart_fallback`).
  Coupure attendue de l'API : ≈ 15–20 s (arrêt ≤ 2 s + `ExecStartPre` ≈ 4 s + démarrage ≈ 5–10 s, mesuré 9,5 s hors `ExecStartPre` en
  QUALIF 0.2.0.4, 16,9–18,3 s mesurés en QUALIF 0.2.0.5) ; les clients SSE
  reconnectent et reçoivent un `state` complet (`roles.pending:false`, `source:"state"`). `btmux-adapters.service` (démarrage) est inchangé.
- Un contrôleur configuré mais absent (`present:false`) n'empêche plus le démarrage : le code de sortie 3 (« adaptateur introuvable ») est
  **remplacé** par l'état `role_unassigned` + journal `adapter_missing` (CHANGED — permet de réaffecter via l'API/Web UI).
- `btmux-adapters.sh` lit la liste effective (état puis config) et ferme (`pairable off`, `discoverable no`) **tous** les autres contrôleurs.
