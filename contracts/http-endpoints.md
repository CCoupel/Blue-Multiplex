# Contrat — API HTTP `btmuxd` v0.2.0 (périmètre « appairages »)

> **Statut : validé au GATE 2 v0.2.0 (2026-10-23 17:12)** — contrat de référence pour LOT-2 « appairages + Web UI » (#20 #21 #16). Serveur aiohttp ; mise à jour en direct par SSE avec repli polling.

> Contract-first (#21). Serveur : `aiohttp` (asyncio natif, pas de pydantic côté serveur — décision GATE 2 du 2026-10-23). Écoute `api.listen` (défaut `0.0.0.0:8088`, LAN seul). **Auth** : `Authorization: Bearer <jeton>`,
> jeton lu dans `api.token_file` (`/etc/btmux/token`, mode 0600, généré à l'installation s'il manque). `GET /` et `/static/*`
> (Web UI) sont publics, tout `/api/*` exige le jeton (401 sinon). Réponses JSON UTF-8 ; erreurs `{ "error": "<code>", "message": "<texte>" }`.

| Méthode | Route | Rôle | Réponse |
|---------|-------|------|---------|
| GET | `/api/health` | vivacité (public) | 200 `{ "version": "0.2.0.0", "adapters": 2 }` |
| GET | `/api/state` | adaptateurs + appareils connus (modèles `models.md`) | 200 `State` |
| POST | `/api/pairing` | ouvrir la fenêtre d'appairage `{ "adapter": "sources"\|"headsets", "duration": 60 }` (1..300 s ; `discoverable+pairable` sur l'adaptateur du rôle ; pour `headsets` lance aussi `StartDiscovery`) | 202 `PairingWindow` ; 409 si une fenêtre est déjà ouverte |
| DELETE | `/api/pairing` | fermer la fenêtre → événement `pairing` `{open:false, reason:"closed"}` ; expiration → `reason:"expired"` ; réouverture sur l'autre adaptateur après 409 évitée (une seule fenêtre) | 204 (204 aussi si déjà fermée) |
| GET | `/api/discovered` | appareils vus pendant une fenêtre `headsets` (non appairés) | 200 `Discovered[]` |
| POST | `/api/devices/{mac}/pair` | appairage **initié par le Pi** (casques) : pair + trust + connect sur l'adaptateur `headsets` | 202 ; 404 si non découvert ; 409 si fenêtre fermée |
| POST | `/api/devices/{mac}/connect` | `Device1.Connect` (Pi initiateur) | 202 ; 404 inconnu |
| POST | `/api/devices/{mac}/disconnect` | `Device1.Disconnect` | 202 |
| POST | `/api/devices/{mac}/forget` | `Adapter1.RemoveDevice` (oubli des deux côtés à faire par l'utilisateur sur la source) → événement **`device.removed`** `{mac, adapter}`, puis `device` placeholder si l'appareil est dans la config | 204 |
| PATCH | `/api/devices/{mac}` | `{ "trusted": bool }` et/ou `{ "alias": "pc-pro" }` (alias btmux, pas l'alias BlueZ) | 200 `Device` |
| GET | `/api/events` | flux **SSE** (`text/event-stream`) : `adapter`, `device`, `pairing`, `discovered` avec le modèle complet en `data` ; `retry: 3000` | 200 |
| | | **Client** : `/api/events` exige le Bearer comme tout `/api/*` ; `EventSource` ne pouvant pas envoyer d'en-tête, la Web UI lit le flux par `fetch` streaming (`ReadableStream`) avec l'en-tête `Authorization`, gère elle-même `retry` et renvoie `Last-Event-ID` à la reconnexion ; le serveur honore `Last-Event-ID` (rejoue les événements manqués dans la limite d'un tampon de 100, sinon envoie un événement `state` complet). Ajouté le 2026-10-24 (#16/#21). | |

Codes : 400 (validation), 401 (jeton), 404, 409 (état), 502 (erreur BlueZ, message D-Bus en `message`), 503 (BlueZ indisponible).
Limites v0.2.0 : pas de routage, pas de volume, pas d'appel ; une seule fenêtre d'appairage à la fois ; les appairages
**entrants** (sources) sont acceptés automatiquement pendant la fenêtre `sources` (agent NoInputNoOutput), refusés hors fenêtre.
