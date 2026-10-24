# Mock de l'API `btmuxd` v0.2.0 (appairages)

Serveur **stdlib** (aucune dépendance) qui rejoue `contracts/http-endpoints.md` + `contracts/models.md`, pour développer la
Web UI (#16) et tester le client sans BlueZ. Les tests `tests/integration/api/mock/` vérifient que le mock respecte le contrat.

```bash
python tests/fixtures/api-mock/server.py --port 8099 --scenario default --token mock-token \
    --static-dir src/btmux/api/static            # affiche {"url": ..., "token": ...}
```

- Jeton : `Authorization: Bearer <token>` sur tout `/api/*` sauf `/api/health` ; sinon `401 {"error","message"}`.
- `GET /` et `/static/*` : servis depuis `--static-dir` (publics) ; sans `--static-dir` → 404.
- `--time-scale 10` : le temps virtuel passe 10× plus vite (fenêtres, délais d'appairage).
- Python : `from server import MockApi` (ou chargement par chemin) → `MockApi("default", token="t").start()` ; `.url`, `.stop()`.

## Scénarios (`scenarios/*.json`, `--scenario <nom>` ou chemin)

| Nom | Contenu |
|-----|---------|
| `default` | 2 adaptateurs ; pc-pro (connecté), tel-perso, xm5 ; 2 casques découvrables (Bose QC45 après 1 s, JBL Tune 760 après 2,5 s) |
| `empty` | aucun appareil connu |
| `window-open` | fenêtre `sources` déjà ouverte (42 s restantes) |
| `stale-bond` | `pair` du JBL (`AA:11:22:33:44:66`) → `409 stale_bond` jusqu'à `forget` |
| `bluez-error` | toute action sur le Bose (`AA:11:22:33:44:55`) → `502 bluez_error` |
| `bluez-down` | tout sauf `/api/health` → `503 bluez_unavailable` |

Champs : `adapters`, `devices`, `discoverable_headsets[{mac,name,rssi,class,reveal_after_s}]`, `pairing`, `stale_bond_macs`,
`bluez_error_macs`, `bluez_unavailable`, `pair_delay_s`, `connect_delay_s`.

## Comportement

- `POST /api/pairing {adapter, duration}` : 400 si adapter/duration invalides, **409 `pairing_open`** si une fenêtre existe, 202
  `PairingWindow` sinon. Compte à rebours `remaining_s` calculé à chaque lecture ; expiration automatique (événement `pairing`).
  Fenêtre `headsets` : les casques de `discoverable_headsets` apparaissent (`GET /api/discovered`, événement `discovered`).
- `POST /api/devices/{mac}/pair` : 404 `not_discovered`, **409 `pairing_closed`** (fenêtre `headsets` fermée), **409 `stale_bond`**,
  502 ; sinon 202 puis, après `pair_delay_s`, l'appareil est appairé/approuvé/connecté (événement `device`).
- `connect`/`disconnect` : 202 puis événement `device` après `connect_delay_s` ; `forget` : 204 (appareil retiré, ou `paired:false`
  s'il est dans la config) ; `PATCH` : `{trusted}` et/ou `{alias}` (400 sinon).
- `GET /api/events` : SSE, `retry: 3000`, `event:`/`id:`/`data:` ; ping `: ping` toutes les 15 s ; `Last-Event-ID` honoré.

## Pilotage hors contrat (`/__mock__/*`, sans jeton)

| Route | Effet |
|-------|-------|
| `GET /__mock__/state` | état complet (+ découverts) |
| `POST /__mock__/reset?scenario=<nom>` | recharge un scénario |
| `POST /__mock__/incoming {mac,name}` | appairage **entrant** (PC/téléphone) : accepté pendant une fenêtre `sources`, sinon 409 `pairing_refused` |
| `POST /__mock__/event {event,data}` | injecte un événement SSE arbitraire |
| `POST /__mock__/fail {bluez_unavailable,stale_bond_macs,bluez_error_macs}` | change les pannes à chaud |
| `POST /__mock__/close-streams` | ferme les flux SSE (test du repli/reconnexion) |

## Contrat SSE (arbitrage planner, contrats 3db8c3c) rejoué par le mock

- `State.pairing` et l'événement `pairing` : **objet** `{open:true, adapter, opened_at, expires_at, remaining_s}` ouvert ;
  fermé = `{open:false, adapter, closed_at, reason: "closed"|"expired"}` (`{open:false, adapter:null, closed_at:null, reason:null}`
  tant qu'aucune fenêtre n'a existé) — **jamais `null`**.
- `DELETE /api/pairing` idempotent (204 même sans fenêtre).
- `forget` : événement `device.removed {mac, adapter}`, puis `device` placeholder (`in_config:true`, `paired/trusted/connected:false`,
  `name:null`, `uuids:[]`) si l'appareil est dans la config ; sinon l'appareil disparaît de `State.devices`.
- Premier événement de toute connexion SSE : `state` (State complet, `id` = dernier id courant), puis les événements.
- `pair` deux fois sur le même appareil pendant l'opération → 409 `operation_in_progress` ; en-têtes de sécurité (CSP, nosniff, DENY, no-referrer, no-store) sur toutes les réponses.
- `Last-Event-ID` : le mock garde un tampon de 100 événements ; un id couvert rejoue les manqués, un id hors tampon envoie un
  événement `state` (State complet).
- Auth du flux : en-tête `Authorization` uniquement (pas de `?token=`) ; le front lit le SSE par `fetch` streaming.
- Codes d'erreur applicatifs (`error`) non fixés par le contrat (seuls les statuts le sont) : `unauthorized`, `invalid_*`,
  `pairing_open`, `pairing_closed`, `stale_bond`, `not_discovered`, `unknown_device`, `bluez_error`, `bluez_unavailable`, `not_found`.
