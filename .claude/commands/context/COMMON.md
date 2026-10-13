# COMMON.md — Adaptations projet Blue-Multiplex

> Compagnon de `COMMON.template.md` (§13) : lu après le template, les règles ci-dessous priment.
> Renseigne les commandes laissées en placeholder par le template (`{BUILD_VALIDATE_CMD}`,
> `{SERVER_*_CMD}`, `{VERSION_READ_CMD}`).

## 2.2 Validation du Build

```bash
ls dist/btmux-*.whl && uv run --isolated --with dist/btmux-*.whl python -c "import btmux; print(btmux.__version__)"
```

## 3. Contrôle du Serveur

`btmuxd` tourne sous systemd sur le Pi (qualif ou prod), jamais sur le poste de développement
(BlueZ/PipeWire réels requis). Les commandes s'exécutent sur le Pi (`ssh pi@btmux-qualif.local` /
`ssh pi@btmux.local`).

### 3.1 Arrêt gracieux

```bash
sudo systemctl stop btmuxd.service
```

### 3.2 Séquence redémarrage complète

```bash
sudo systemctl restart btmuxd.service
```

### 3.3 Vérification post-démarrage

```bash
systemctl is-active btmuxd.service \
  && curl -fsS -H "Authorization: Bearer $(sudo cat /etc/btmux/token)" http://localhost:8088/state
```

## 5. Lecture de la version (`{VERSION_READ_CMD}`)

```bash
grep -E '^version *= *"' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/'
```
