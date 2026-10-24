"""Fichier d'état des affectations de contrôleurs (#23) : `/var/lib/btmux/adapters.yaml`.

Même schéma que la clé `adapters` de `config.yaml`. Il PRIME sur la configuration lorsqu'il existe
et est valide ; `config.yaml` n'est jamais réécrit par le daemon (lecture seule,
`ProtectSystem=strict`).
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

import yaml

from btmux.config.loader import load_config, parse_adapter_list
from btmux.config.models import DEFAULT_STATE_PATH, Adapter, Config, ConfigError
from btmux.log import kv

log = logging.getLogger("btmux.config")
HEADER = "# écrit par btmuxd (PUT /api/controllers/roles) — ne pas éditer à la main pendant que btmuxd tourne\n"  # noqa: E501


def load_state(path: str | Path) -> tuple[Adapter, ...] | None:
    """Liste `adapters` du fichier d'état ; `None` s'il n'existe pas ; `ConfigError` si invalide."""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError([f"state: cannot read '{path}': {exc}"]) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError([f"state: cannot read '{path}': {' '.join(str(exc).split())}"]) from exc
    if not isinstance(data, dict) or set(data) - {"adapters"}:
        raise ConfigError([f"state: '{path}': expected a mapping with the single key 'adapters'"])
    return parse_adapter_list(data.get("adapters"))


def load_effective(config_path: str | Path, state_path: str | Path = DEFAULT_STATE_PATH) -> Config:
    """Configuration effective : `adapters` de l'état s'il est valide, sinon de `config.yaml`."""
    config = load_config(config_path)
    try:
        adapters = load_state(state_path)
    except ConfigError as exc:
        log.error(kv("state_invalid", file=state_path, error=" | ".join(exc.errors)))
        adapters = None
    update: dict[str, object] = {"state_path": Path(state_path)}
    if adapters is not None:
        update.update(adapters=adapters, adapters_source="state")
    return config.model_copy(update=update)


def write_state_atomic(path: str | Path, adapters: Sequence[Adapter]) -> None:
    """Écrit le fichier d'état de façon atomique (temporaire voisin, fsync, rename), mode 0640."""
    file = Path(path)
    document = {
        "adapters": [{"mac": a.mac, "name": a.name, "roles": list(a.roles)} for a in adapters]
    }
    body = HEADER + yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".adapters.", suffix=".tmp", dir=file.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o640)
        os.replace(tmp, file)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    dir_fd = os.open(file.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
