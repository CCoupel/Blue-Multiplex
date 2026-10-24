"""Lecture sysfs du transport d'un contrôleur Bluetooth (`bus`, `usb_id`) — contracts/models.md `Controller`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

BusName = Literal["usb", "uart", "unknown"]
Probe = Callable[[str], tuple[BusName, str | None]]
SYS_BLUETOOTH = Path("/sys/class/bluetooth")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii").strip().lower()
    except (OSError, UnicodeDecodeError):
        return None


def probe_controller(hci: str, root: Path = SYS_BLUETOOTH) -> tuple[BusName, str | None]:
    """`(bus, usb_id)` de `hciN` : `usb` (`idVendor:idProduct` d'un ancêtre), `uart` (parent `serial`/`platform`).

    `unknown` si sysfs est absent, illisible ou ne permet pas de conclure (jamais d'exception).
    """
    try:
        real = (root / hci).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return "unknown", None
    for folder in (real, *real.parents):
        vendor, product = _read(folder / "idVendor"), _read(folder / "idProduct")
        if vendor and product:
            return "usb", f"{vendor}:{product}"
    if any("serial" in part or part == "platform" for part in real.parts):
        return "uart", None
    return "unknown", None
