"""Journal structuré `clé=valeur` pour journald (jamais de secret : le jeton d'API n'est jamais journalisé)."""

from __future__ import annotations

import logging
import os
import sys

_SYSLOG = {
    logging.DEBUG: 7,
    logging.INFO: 6,
    logging.WARNING: 4,
    logging.ERROR: 3,
    logging.CRITICAL: 2,
}
_SENSITIVE = ("token", "secret", "password", "authorization")


def kv(event: str, **fields: object) -> str:
    """`event=pair_ok mac=AA:.. adapter=headsets` ; les champs sensibles sont masqués."""
    parts = [f"event={event}"]
    for key, value in fields.items():
        text = "***" if any(s in key.lower() for s in _SENSITIVE) else str(value)
        if " " in text or not text:
            text = '"' + text.replace('"', "'") + '"'
        parts.append(f"{key}={text}")
    return " ".join(parts)


class _JournalFormatter(logging.Formatter):
    """Préfixe `<N>` (priorité syslog) lorsque la sortie est lue par journald."""

    def __init__(self, prefix: bool) -> None:
        super().__init__("%(name)s %(message)s")
        self._prefix = prefix

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        return f"<{_SYSLOG.get(record.levelno, 6)}>{text}" if self._prefix else text


def configure(level: str | None = None) -> None:
    """Configure le logger `btmux` (stderr ; niveau `BTMUX_LOG_LEVEL`, défaut INFO)."""
    logger = logging.getLogger("btmux")
    name = (level or os.environ.get("BTMUX_LOG_LEVEL", "INFO")).upper()
    logger.setLevel(getattr(logging, name, logging.INFO))
    if not any(getattr(h, "_btmux", False) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JournalFormatter(prefix="JOURNAL_STREAM" in os.environ))
        handler._btmux = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.propagate = False
