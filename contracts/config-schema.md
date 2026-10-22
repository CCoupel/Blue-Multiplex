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
    name: "btmux"                      # obligatoire — nom Bluetooth annoncé (1..248 octets UTF-8)
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
| V2 | `adapters` non vide ; `roles` sous-ensemble non vide de `{sources, headsets}`, sans doublon | `config: adapters[i].roles: unknown role '...'` |
| V3 | Chaque rôle `sources` et `headsets` porté par **exactement un** adaptateur | `config: role 'headsets' must be provided by exactly one adapter (found N)` |
| V4 | **v0.1.0** : `len(adapters) > 1` refusé (le schéma l'accepte, la politique refuse) | `config: multi-adapter configuration is planned for v0.2.0 (found N adapters, max 1)` |
| V5 | `devices[].alias` uniques ; `devices[].mac` uniques ; alias `^[a-z0-9][a-z0-9-]{0,31}$` | `config: devices: duplicate alias 'xm5'` |
| V6 | `kind ∈ {source, headset}` ; `priority` entier ≥ 0, optionnel, **autorisé seulement** pour `kind: source` (défaut 100) | `config: devices[2].priority: only allowed for kind 'source'` |
| V7 | `default_routes` : clé = alias d'un `headset` existant, valeur = alias d'une `source` existante | `config: default_routes: unknown headset alias '...'` |
| V8 | `api.listen` = `host:port` (port 1..65535) ; `api.token_file` chemin absolu | `config: api.listen: expected host:port` |
| V9 | Clés inconnues refusées à tous les niveaux (strict) | `config: unknown key '...' in devices[0]` |
| V10 | Fichier absent / YAML invalide → code 2, message `config: cannot read '<path>': ...` | |

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

## Évolution prévue (v0.2.0, #14)

Suppression de V4 uniquement ; `adapters` à deux entrées `roles: [sources]` / `roles: [headsets]`. Aucun autre changement.
