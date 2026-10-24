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
- `name` d'un contrôleur nouvellement affecté : repris de `config.yaml` si la MAC y figure, sinon défaut `btmux` (sources) / `btmux-hp` (headsets).
- **Application par redémarrage piloté du service (D3 b)** — séquence :
  1. `PUT` validé (no-op → 200 sans suite) → **écriture atomique** de l'état (échec → 500 `state_write_failed`, séquence abandonnée, rien n'est
     déconnecté, `pending` reste faux) → fenêtre d'appairage fermée, appareils déconnectés si `confirm` → réponse 202 + événement
     `roles {pending:true, restart_expected:true}` ; toute écriture ultérieure répond 409 `change_pending`.
  2. `btmux-adapters.path` (`PathChanged=/var/lib/btmux/adapters.yaml`) déclenche **`btmux-adapters-reload.service`** (root, oneshot) :
     `btmux-adapters.sh --state … --config …` (alias, classe, fermeture de **tous** les contrôleurs sans rôle, ≈ 4 s) puis
     `ExecStartPost=systemctl restart --no-block btmuxd.service` → arrêt propre (SIGTERM, code 0) et relance immédiate (pas de `RestartSec`,
     ce n'est pas un échec ; `StartLimitBurst` inchangé).
  3. **Repli** : si le daemon n'a pas reçu SIGTERM **30 s** après l'écriture (unité path absente/inactive), il sort en code **4**
     (`RestartForceExitStatus=4` ; `RestartSec=30` s'applique alors — journal `restart_fallback`).
  Coupure attendue de l'API : ≈ 10–15 s (arrêt ≤ 2 s + démarrage ≈ 5–10 s, mesuré 9,5 s en QUALIF 0.2.0.4) ; les clients SSE
  reconnectent et reçoivent un `state` complet (`roles.pending:false`, `source:"state"`). `btmux-adapters.service` (démarrage) est inchangé.
- Un contrôleur configuré mais absent (`present:false`) n'empêche plus le démarrage : le code de sortie 3 (« adaptateur introuvable ») est
  **remplacé** par l'état `role_unassigned` + journal `adapter_missing` (CHANGED — permet de réaffecter via l'API/Web UI).
- `btmux-adapters.sh` lit la liste effective (état puis config) et ferme (`pairable off`, `discoverable no`) **tous** les autres contrôleurs.
