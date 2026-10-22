# dev-frontend — Web UI minimale (HTML/CSS/JS vanilla)

> Compagnon de `dev-frontend.template.md` (base `dev-generic`). Repris de l'ancien agent `dev-frontend`
> (derive de `dev-frontend-react`, pas de modele vanilla dans le template).

## Stack

HTML5 semantique, CSS moderne (variables, grid/flex, `prefers-color-scheme`), JavaScript ES2022+ natif
(modules ES, `fetch`, `EventSource`/WebSocket si l'API l'expose). Aucun framework, aucun bundler, aucun CDN :
fichiers statiques servis par le daemon Python `btmuxd` (`src/btmux/api/static/`). Cible : navigateur, usage
telephone comme PC. UI prevue plus tard, pas en v1.

## Toolchain et commandes

Aucun build ni bundler. Pas de lint JS dedie.
- Tests : verification manuelle decrite dans la procedure QA ; tests de l'API cote backend (`uv run pytest`).
- Lancement : servir `src/btmux/api/static/` via l'API `btmuxd`.

## Perimetre

- `src/btmux/api/static/**`

```
src/btmux/api/static/
├── index.html          # Page unique : etat, routage par casque, appairage
├── app.js              # Logique (appels API, rendu)
├── api.js              # Client HTTP (jeton dans l'en-tete Authorization)
└── style.css
```

## Conventions

- Contrats `contracts/` consultes (jamais modifies) ; attendre le backend si de nouveaux endpoints sont impliques
  (`GET /state`, `POST /route`, `POST /pairing`, `POST /devices/{mac}/forget`).
- Jeton API : jamais en dur dans les sources ; saisi par l'utilisateur et conserve en `localStorage`.
- Rendu par petites fonctions pures `render<Bloc>(state)` ; pas de manipulation DOM dispersee.
- Rafraichissement : polling `GET /state` (intervalle configurable) ou flux serveur si disponible.
- Erreurs API affichees dans la page, jamais via `alert()`.
- Accessibilite de base (labels, focus, contrastes) ; lisible sur ecran de telephone ; aucun JS tiers ni CDN.
