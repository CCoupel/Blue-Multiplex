# Web UI btmux (statique)

HTML/CSS/JS vanilla, sans dépendance ni build. Servie par `btmuxd` (`GET /` et `/static/*`, publics ; `/api/*` exige le jeton).

- `index.html` · `app.js` (état + rendu) · `api.js` (client HTTP, SSE via `fetch` avec en-tête Bearer) · `style.css`
- Jeton : saisi dans l'en-tête de la page, conservé en `localStorage` (clé `btmux.token`).
- Mise à jour : SSE `/api/events` ; repli polling `GET /api/state` toutes les 5 s si le flux tombe.

## Lancement contre l'API simulée

L'API simulée (`tests/fixtures/api-mock/`, fournie par test-writer) sert ces fichiers et rejoue `contracts/models.md` :

    python tests/fixtures/api-mock/server.py --port 8088   # commande/port à confirmer avec test-writer
    # puis ouvrir http://127.0.0.1:8088/ et saisir le jeton affiché par le mock

À défaut du mock : `python -m http.server -d src/btmux/api/static 8000` n'affiche que l'interface (les appels `/api/*` échouent).

## Tests

    node --test src/btmux/api/static/api.test.mjs   # client SSE/HTTP, sans dépendance (hors CI pytest)
