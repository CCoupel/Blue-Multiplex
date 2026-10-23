# Publish — QUALIF — adaptations projet Blue-Multiplex (mecanisme : promote)

> Compagnon de `publish.qualif.template.md` : **prevaut** sur la procedure generique
> (`agents/deploy.md`, section « Fichiers d'Environnement »). Le template parle de
> `app-$VERSION.tar.gz` — **ce nom ne s'applique pas ici** : l'artefact Blue-Multiplex est la wheel
> Python `btmux-<X.Y.Z.a>-py3-none-any.whl`.

Promotion sans rebuild (BORE, `agents/infra.md` §3 (a)) : la wheel candidate produite par BUILD est
copiee telle quelle, octet pour octet, vers le dossier QUALIF. Aucun `uv build` ici.

## Prerequis — sortie de la Tache BUILD

`commands.build` = `uv build` ecrit par defaut dans `dist/` (wheel **et** sdist). Pour que le candidat
soit au chemin attendu, BUILD l'execute avec une sortie explicite, wheel seule :

```bash
uv build --wheel --out-dir "$BUILD_DIR"
# -> $BUILD_DIR/btmux-$VERSION-py3-none-any.whl   ex: build/candidate_v0.1.0/btmux-0.1.0.1-py3-none-any.whl
```

`$VERSION` = version complete avec `a` lue dans `pyproject.toml` (`[project] version`, ex. `0.1.0.1`) —
PEP 440 conserve les 4 segments dans le nom de la wheel. `$DIR_VERSION` = `X.Y.Z` (sans `a`).

## Variables attendues

Aucune (copie locale). `$REPO_ROOT`, `$VERSION`, `$DIR_VERSION`, `$BUILD_DIR` heritees de BUILD.

```bash
# 1. Verification — la wheel exacte de ce build, jamais un glob « la plus recente »
WHEEL="btmux-$VERSION-py3-none-any.whl"
test -f "$BUILD_DIR/$WHEEL" \
  || { echo "Candidat absent : $BUILD_DIR/$WHEEL — executer /build d'abord"; exit 1; }

# 2. Promotion — dossier SANS `a`, artefact AVEC `a` (meme nom, memes octets)
TARGET_DIR="$REPO_ROOT/build/qualif_v$DIR_VERSION"
mkdir -p "$TARGET_DIR"
cp "$BUILD_DIR/$WHEEL" "$TARGET_DIR/$WHEEL"
( cd "$TARGET_DIR" && sha256sum "$WHEEL" > "$WHEEL.sha256" )
cmp "$BUILD_DIR/$WHEEL" "$TARGET_DIR/$WHEEL"   # zero rebuild : identite bit a bit

# 3. Notification
echo "Publication QUALIF terminee - $VERSION -> $TARGET_DIR/$WHEEL"
```

## Echec

- Wheel candidate absente -> `dev` (BUILD a echoue ou a ecrit ailleurs, ex. `dist/`).
- Copie impossible (droits, disque) -> `infra`.

Format `PUBLISH FAILED` : celui du template.

## Rollback

```bash
rm -f "$TARGET_DIR/$WHEEL" "$TARGET_DIR/$WHEEL.sha256"
```

## Note R2 (packaging PROD)

La wheel QUALIF porte 4 segments (`0.1.0.1`), le paquet `.deb` PROD est en `X.Y.Z` : la correspondance
est geree par `scripts/build-deb.sh` (glob `btmux-${VERSION}*`, T1.6). Rien ici ne doit imposer un nom
de wheel a 3 segments.
