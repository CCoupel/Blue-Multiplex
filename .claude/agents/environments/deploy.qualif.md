# Deploy — QUALIF — adaptations projet Blue-Multiplex (mecanisme : vps)

> Compagnon de `deploy.qualif.template.md` : **prevaut** sur la procedure generique. Le template
> (`app-*.tar.gz`, `systemctl restart app`, `/health`) ne s'applique pas : toute l'installation est
> portee par `scripts/deploy.sh` (interface fixee : `deploy.sh <env> <wheel>`).

Installation pure de la wheel et de son lockfile deja publies par PUBLISH QUALIF — aucun build, aucune
publication, aucune resolution de dependances hors lockfile (BORE). Unite systeme `btmuxd` (utilisateur de
service via drop-in `btmux-set-user.sh` / `BTMUX_USER`, defaut = partie utilisateur de `DEPLOY_HOST`,
linger active — decision D2).

## Cible — garde-fous (bloquants, avant toute action distante)

| Element | Valeur attendue |
|---------|-----------------|
| `DEPLOY_HOST` (`qualif.env`) | `user@host` du Pi de qualification (Ubuntu 26.04 LTS) — valeur uniquement dans `qualif.env`, jamais en clair dans le depot |
| `hostname` distant | `pi-qualif` |
| Hotes **interdits** | `FORBIDDEN_HOSTS` (`qualif.env`, liste separee par des virgules ; contient le Pi « piClock », en service) — jamais de `ssh`/`scp`, quel que soit le contexte |

`qualif.env` est en **CRLF** : le lire avec `tr -d '\r'`, ne jamais le reecrire.

## Variables attendues

Chargees par `deployer` depuis `.claude/agents/environments/qualif.env` (modele : `qualif.env.example`),
et relues par `scripts/deploy.sh` lui-meme.

| Variable | Usage |
|----------|-------|
| `SSH_KEY_PATH` | Cle privee `ssh`/`scp` vers le Pi de qualif (aussi utilisee par `commands.smoke`) |
| `DEPLOY_HOST` | `user@host` cible — aussi utilisee par `commands.smoke`, qui source `qualif.env` lui-meme |
| `BTMUX_USER` | optionnel — utilisateur de service de `btmuxd` |

Variable absente -> STOP, remonter au teamleader (ne jamais coder de valeur).

## Interface attendue de `scripts/deploy.sh` (T1.8, `dev-backend`)

`scripts/deploy.sh <env> <wheel>` — inchange. Le lockfile **n'est pas un argument** : `deploy.sh` le
trouve a cote de la wheel, par convention de nom (meme dossier, meme version) :

```
<dir>/btmux-<V>-py3-none-any.whl  ->  <dir>/btmux-<V>.requirements.lock.txt
```

Lockfile absent -> `deploy.sh` sort en erreur (rc 1) **avant** tout `ssh`. Sequence distante attendue
(meme que le `postinst` du `.deb`) : `mktemp -d` distant, `python3 -m venv /opt/btmux` (sans
`--upgrade-deps`), `pip install --require-hashes --no-deps -r <lock>`, puis wheel
`pip install --no-index --no-deps --force-reinstall <wheel>`, unites (`btmuxd.service`,
`btmux-adapters.service`), policy D-Bus, `/etc/btmux/token` (0600) genere s'il manque, `daemon-reload`,
`restart`. Ce companion ne decrit que l'orchestration ; le detail appartient au script.

## Procedure

```bash
set -euo pipefail
ENV_FILE=.claude/agents/environments/qualif.env
set -a; . <(tr -d '\r' < "$ENV_FILE"); set +a
: "${SSH_KEY_PATH:?absent de qualif.env}" "${DEPLOY_HOST:?absent de qualif.env}"
SSH=(ssh -i "$SSH_KEY_PATH" -o BatchMode=yes -- "$DEPLOY_HOST")

# 0. Garde-fous cible
: "${FORBIDDEN_HOSTS:?absent de qualif.env}"
IFS=, read -ra _forbidden <<< "$FORBIDDEN_HOSTS"
for h in "${_forbidden[@]}"; do
  [ -n "$h" ] && case "$DEPLOY_HOST" in *"$h"*) echo "REFUS : hote interdit ($h)"; exit 1 ;; esac
done
test "$("${SSH[@]}" hostname)" = pi-qualif || { echo "hostname distant != pi-qualif"; exit 1; }

# 1. Verification — wheel ET lockfile publies pour CETTE version, sommes de controle
PUB="$REPO_ROOT/build/qualif_v$DIR_VERSION"
WHEEL="$PUB/btmux-$VERSION-py3-none-any.whl"
LOCK="$PUB/btmux-$VERSION.requirements.lock.txt"
for f in "$WHEEL" "$LOCK"; do
  test -f "$f" || { echo "Aucune publication QUALIF complete pour $VERSION ($f) — /publish qualif"; exit 1; }
done
( cd "$PUB" && sha256sum -c "btmux-$VERSION.sha256" )
test -x scripts/deploy.sh || { echo "scripts/deploy.sh absent"; exit 1; }
```

### 2. Bluetooth integre desactive (`disable-bt`) — pose a LOT-1 v0.2.0, une seule fois

A partir de v0.2.0, le Pi de qualif n'utilise **plus** le Bluetooth integre (cible : 2 × UB500,
`docs/install-pi.md` §6). `dtoverlay=disable-bt` est pose des LOT-1, **avant** reception des dongles.
`disable-wifi` n'est **pas** pose ici (SSH par Wi-Fi ; reporte a T3.2b, apres branchement Ethernet).

```bash
CFG=/boot/firmware/config.txt
if ! "${SSH[@]}" "grep -q '^dtoverlay=disable-bt' $CFG"; then
  # Sauvegarde horodatee puis ajout en fin de fichier sous un [all] explicite (une section [all]
  # supplementaire est sans effet de bord). Idempotent : ne s'execute que si la ligne est absente.
  "${SSH[@]}" "sudo cp -a $CFG $CFG.btmux-\$(date +%Y%m%d%H%M%S) \
    && printf '\n[all]\ndtoverlay=disable-bt\n' | sudo tee -a $CFG >/dev/null"
  "${SSH[@]}" "sudo systemctl disable --now hciuart.service 2>/dev/null || true"   # absent sous Ubuntu : ignore
  "${SSH[@]}" "sudo systemctl reboot" || true
  # Attente du retour SSH (max 3 min), puis re-controle du hostname
  for i in $(seq 1 36); do sleep 5; "${SSH[@]}" true 2>/dev/null && break; done
  test "$("${SSH[@]}" hostname)" = pi-qualif || { echo "Pi non revenu apres reboot"; exit 1; }
fi
# Verification : plus aucun controleur UART (BT integre)
"${SSH[@]}" "grep -q '^dtoverlay=disable-bt' $CFG" || { echo "disable-bt absent"; exit 1; }
# Chaque hciN restant doit etre USB (chemin sysfs du device contenant /usb) — 0 controleur UART
"${SSH[@]}" 'for h in /sys/class/bluetooth/hci*; do [ -e "$h" ] || continue; readlink -f "$h/device" | grep -q /usb || exit 1; done' \
  || { echo "controleur Bluetooth non-USB (UART integre) encore present"; exit 1; }
```

**Adaptateurs absents (tolere tant que les UB500 ne sont pas branches)** : apres `disable-bt` et sans
dongle, `/sys/class/bluetooth/` est vide. C'est l'etat attendu de LOT-1 ; seules les verifications radio
sont sautees. **Quand les UB500 sont branches** (campagne, T3.x) : relancer le script de controle de
`docs/install-pi.md` §8 avec `BTMUX_BT_MODE=dongle` (defaut) — attendu : **2 controleurs USB, 0 UART** —
et l'inclure au rapport DEPLOY.

### 3. Installation

```bash
scripts/deploy.sh qualif "$WHEEL"          # lockfile trouve a cote de la wheel
```

### 4. Verification post-deploy

```bash
# 4a. Identite des adaptateurs (oneshot) — sortie 0 obligatoire ; sans adaptateur : avertissement tolere
"${SSH[@]}" "systemctl show -p Result,ExecMainStatus btmux-adapters.service"
# attendu : Result=success, ExecMainStatus=0
"${SSH[@]}" "journalctl -u btmux-adapters.service -b --no-pager -n 20"
# LOT-1 sans dongle : un avertissement « adaptateur absent » est attendu et NON bloquant (consigne au rapport)

# 4b. Dependances = lockfile (aucune dependance hors lockfile, environnement coherent)
"${SSH[@]}" "/opt/btmux/bin/pip check"

# 4c. Smoke — commands.smoke (D5)
SMOKE_CMD=$(jq -r '.commands.smoke // empty' .claude/project-config.json)
test -n "$SMOKE_CMD" || { echo "commands.smoke vide"; exit 1; }
bash -c "$SMOKE_CMD"

# 5. Notification
echo "Deploiement QUALIF termine - $VERSION"
```

Smoke LOT-1 (`commands.smoke` actuel) : `systemctl is-active btmuxd && btmuxd --version && btmuxd
--config /etc/btmux/config.yaml --check-config`. Si `btmuxd` refuse de demarrer **uniquement** faute
d'adaptateur (etat LOT-1 attendu), ce n'est pas un ecart infra : rapport au teamleader, `dev-backend`.

Le rapport DEPLOY cite : sha256 wheel + lockfile, etat `disable-bt` (pose a ce deploiement / deja
present), resultat `btmux-adapters.service` (+ avertissement eventuel), `pip check`, sortie du smoke.

## Apres LOT-2 (#21, API HTTP) — smoke `/api/health`

Quand T2.3 est livre, `commands.smoke` est remplace (par `infra`, sur ordre du teamleader) par un controle
HTTP **execute sur le Pi** (le jeton ne quitte jamais le Pi) :

```bash
"${SSH[@]}" 'set -e
  systemctl is-active btmuxd
  curl -fsS http://127.0.0.1:8088/api/health                       # public : 200 {"version":..,"adapters":..}
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8088/api/state)
  test "$code" = 401                                                  # sans jeton : refuse
  curl -fsS -o /dev/null -H "Authorization: Bearer $(sudo cat /etc/btmux/token)" \
    http://127.0.0.1:8088/api/state                                   # avec jeton : 200'
```

Verifier en plus que `version` renvoye par `/api/health` = `$VERSION`. Port = `api.listen` de
`/etc/btmux/config.yaml` (defaut `0.0.0.0:8088`, `contracts/http-endpoints.md`).

## Echec

```bash
"${SSH[@]}" "journalctl -u btmuxd -u btmux-adapters --since '5 min ago' --no-pager"
```

Echec d'installation (BUILD et PUBLISH ont reussi) -> rapport au teamleader, aucune correction
autonome : `scripts/deploy.sh`/unites systemd/lockfile -> `dev-backend` ; SSH/reseau/Pi/`config.txt` -> `infra`.
Pi injoignable apres le reboot `disable-bt` -> `BLOQUE` au teamleader (intervention physique : retirer la
ligne depuis la carte SD, sauvegarde `config.txt.btmux-*`).

## Rollback

Reinstaller la version QUALIF precedente (wheel **et** lockfile toujours presents dans
`build/qualif_v$DIR_VERSION/`) :

```bash
scripts/deploy.sh qualif "$REPO_ROOT/build/qualif_v$DIR_VERSION/btmux-$PREVIOUS_VERSION-py3-none-any.whl"
```

Une version anterieure a v0.2.0 (sans lockfile) n'est pas redeployable par ce companion. `disable-bt`
n'est **pas** annule par un rollback logiciel (retour BT integre : `docs/install-pi.md` §10, decision
utilisateur).
