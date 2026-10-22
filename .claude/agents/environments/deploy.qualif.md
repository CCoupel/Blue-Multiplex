# Deploy — QUALIF — adaptations projet Blue-Multiplex (mecanisme : vps)

> Compagnon de `deploy.qualif.template.md` : **prevaut** sur la procedure generique. Le template
> (`app-*.tar.gz`, `systemctl restart app`, `/health`) ne s'applique pas : toute l'installation est
> portee par `scripts/deploy.sh` (interface fixee, T1.7).

Installation pure de la wheel deja publiee par PUBLISH QUALIF — aucun build, aucune publication
(BORE). Cible : `pi@btmux-qualif.local:/opt/btmux` (venv), unite systeme `btmuxd` (`User=pi`,
`XDG_RUNTIME_DIR=/run/user/1000`, linger active — decision D2).

## Variables attendues

Chargees par `deployer` depuis `.claude/agents/environments/qualif.env` (modele : `qualif.env.example`),
et relues par `scripts/deploy.sh` lui-meme.

| Variable | Usage |
|----------|-------|
| `SSH_KEY_PATH` | Cle privee `ssh`/`scp` vers le Pi de qualif (aussi utilisee par `commands.smoke`) |
| `DEPLOY_HOST` | `user@host` cible (ex. `pi@192.168.1.176`, valeur dans `qualif.env`) — aussi utilisee par `commands.smoke`, qui source `qualif.env` lui-meme |

Variable absente -> STOP, remonter au teamleader (ne jamais coder de valeur).

```bash
# 1. Verification — la wheel publiee pour CETTE version
WHEEL="$REPO_ROOT/build/qualif_v$DIR_VERSION/btmux-$VERSION-py3-none-any.whl"
test -f "$WHEEL" \
  || { echo "Aucune publication QUALIF pour $VERSION — executer /publish qualif d'abord"; exit 1; }
( cd "$(dirname "$WHEEL")" && sha256sum -c "$(basename "$WHEEL").sha256" )
test -x scripts/deploy.sh || { echo "scripts/deploy.sh absent (T1.7)"; exit 1; }
: "${SSH_KEY_PATH:?absent de qualif.env}" "${DEPLOY_HOST:?absent de qualif.env}"

# 2. Install — scp, venv /opt/btmux, unite systemd, config d'exemple, daemon-reload, restart
scripts/deploy.sh qualif "$WHEEL"

# 3. Verification post-deploy — commands.smoke (D5)
SMOKE_CMD=$(jq -r '.commands.smoke // empty' .claude/project-config.json)
test -n "$SMOKE_CMD" || { echo "commands.smoke vide"; exit 1; }
bash -c "$SMOKE_CMD"

# 4. Notification
echo "Deploiement QUALIF termine - $VERSION"
```

## Echec

```bash
ssh -i "$SSH_KEY_PATH" "$DEPLOY_HOST" "journalctl -u btmuxd --since '5 min ago' --no-pager"
```

Echec d'installation (BUILD et PUBLISH ont reussi) -> rapport au teamleader, aucune correction
autonome : `scripts/deploy.sh`/unite systemd -> `dev-backend` ; SSH/reseau/Pi -> `infra`.

## Rollback

Reinstaller la wheel QUALIF precedente (toujours presente dans `build/qualif_v$DIR_VERSION/`) :

```bash
scripts/deploy.sh qualif "$REPO_ROOT/build/qualif_v$DIR_VERSION/btmux-$PREVIOUS_VERSION-py3-none-any.whl"
```
