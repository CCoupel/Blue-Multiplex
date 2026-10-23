# Publish — QUALIF — adaptations projet Blue-Multiplex (mecanisme : promote)

> Compagnon de `publish.qualif.template.md` : **prevaut** sur la procedure generique
> (`agents/deploy.md`, section « Fichiers d'Environnement »). Le template parle de
> `app-$VERSION.tar.gz` — **ce nom ne s'applique pas ici** : l'artefact Blue-Multiplex est le couple
> **wheel Python + lockfile de dependances runtime hache** (v0.2.0, #17) :
>
> | Fichier | Contenu |
> |---------|---------|
> | `btmux-$VERSION-py3-none-any.whl` | le code btmux |
> | `btmux-$VERSION.requirements.lock.txt` | dependances runtime figees avec hashes (`pip --require-hashes`) |
>
> Les deux sont produits par le **meme** BUILD et promus **ensemble** : une wheel sans son lockfile n'est
> pas deployable (l'installation QUALIF ne resout plus rien sur PyPI hors lockfile).

Promotion sans rebuild (BORE, `agents/infra.md` §3 (a)) : wheel et lockfile candidats sont copies tels
quels, octet pour octet, vers le dossier QUALIF. Aucun `uv build`, aucun `uv export` ici.

## Prerequis — sortie de la Tache BUILD

Rappel BUMP : `deployer` incremente `a` dans `pyproject.toml` **et** execute `uv lock` dans le **meme**
commit (`chore(version): X.Y.Z.a` — `pyproject.toml` + `uv.lock`). Sans cela, l'export ci-dessous echoue
(`--locked`) : c'est voulu, ne jamais le contourner par `--frozen` en BUILD.

`commands.build` = `uv build` ecrit par defaut dans `dist/` (wheel **et** sdist). BUILD l'execute avec une
sortie explicite, wheel seule, puis exporte le lockfile **depuis le meme commit** :

```bash
uv build --wheel --out-dir "$BUILD_DIR"
uv export --locked --no-dev --no-emit-project --hashes --format requirements-txt \
  -o "$BUILD_DIR/btmux-$VERSION.requirements.lock.txt"
# -> $BUILD_DIR/btmux-$VERSION-py3-none-any.whl                ex: build/candidate_v0.2.0/btmux-0.2.0.1-py3-none-any.whl
# -> $BUILD_DIR/btmux-$VERSION.requirements.lock.txt           ex: build/candidate_v0.2.0/btmux-0.2.0.1.requirements.lock.txt
```

- `--no-dev` : dependances runtime seules (ni pytest, ni ruff, ni mypy sur le Pi).
- `--no-emit-project` : btmux lui-meme n'est pas dans le lockfile — il est installe depuis la wheel
  (`--no-deps`), les deps depuis le lockfile (`--require-hashes`).
- Meme contenu que `dist/requirements.lock.txt` produit par `scripts/ci.sh` (T1.8, embarque dans le `.deb`
  PROD) ; seul le nom differe, **versionne** ici pour que chaque wheel QUALIF garde son lockfile (rollback).

`$VERSION` = version complete avec `a` lue dans `pyproject.toml` (`[project] version`, ex. `0.2.0.1`) —
PEP 440 conserve les 4 segments dans le nom de la wheel. `$DIR_VERSION` = `X.Y.Z` (sans `a`).

## Variables attendues

Aucune (copie locale). `$REPO_ROOT`, `$VERSION`, `$DIR_VERSION`, `$BUILD_DIR` heritees de BUILD.

```bash
# 1. Verification — la wheel et le lockfile exacts de ce build, jamais un glob « le plus recent »
WHEEL="btmux-$VERSION-py3-none-any.whl"
LOCK="btmux-$VERSION.requirements.lock.txt"
for f in "$WHEEL" "$LOCK"; do
  test -f "$BUILD_DIR/$f" || { echo "Candidat absent : $BUILD_DIR/$f — executer /build d'abord"; exit 1; }
done
# Lockfile exploitable : chaque exigence porte au moins un hash, btmux n'y figure pas
grep -q -- '--hash=sha256:' "$BUILD_DIR/$LOCK" || { echo "Lockfile sans hash : $LOCK"; exit 1; }
! grep -qiE '^btmux([=<> ]|$)' "$BUILD_DIR/$LOCK" || { echo "btmux present dans le lockfile (--no-emit-project manquant)"; exit 1; }

# 2. Promotion — dossier SANS `a`, artefacts AVEC `a` (memes noms, memes octets)
TARGET_DIR="$REPO_ROOT/build/qualif_v$DIR_VERSION"
mkdir -p "$TARGET_DIR"
for f in "$WHEEL" "$LOCK"; do
  cp "$BUILD_DIR/$f" "$TARGET_DIR/$f"
  cmp "$BUILD_DIR/$f" "$TARGET_DIR/$f"          # zero rebuild : identite bit a bit
done
( cd "$TARGET_DIR" && sha256sum "$WHEEL" "$LOCK" > "btmux-$VERSION.sha256" \
  && sha256sum "$WHEEL" > "$WHEEL.sha256" )      # .whl.sha256 conserve (compatibilite rollback 0.1.0.x)

# 3. Notification
echo "Publication QUALIF terminee - $VERSION -> $TARGET_DIR/{$WHEEL,$LOCK}"
```

Le rapport PUBLISH cite les **deux** sha256 (wheel, lockfile).

## Echec

- Wheel ou lockfile candidat absent -> `dev-backend` (BUILD a echoue ou a ecrit ailleurs, ex. `dist/`).
- `uv export --locked` en echec en BUILD -> `uv.lock` non regenere au bump : refaire le commit de bump
  (`deployer`), jamais `--frozen`.
- Copie impossible (droits, disque) -> `infra`.

Format `PUBLISH FAILED` : celui du template.

## Rollback

```bash
rm -f "$TARGET_DIR/$WHEEL" "$TARGET_DIR/$LOCK" "$TARGET_DIR/$WHEEL.sha256" "$TARGET_DIR/btmux-$VERSION.sha256"
```

## Note R2 (packaging PROD)

La wheel QUALIF porte 4 segments (`0.2.0.1`), le paquet `.deb` PROD est en `X.Y.Z` : la correspondance
est geree par `scripts/build-deb.sh` (glob strict `btmux-${VERSION}*`). Rien ici ne doit imposer un nom
de wheel a 3 segments. Le `.deb` n'est **pas** publie en QUALIF (livrable PROD uniquement).
