"""btmux — multiplexeur audio Bluetooth."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("btmux")
except PackageNotFoundError:  # pragma: no cover - paquet non installe
    __version__ = "0.0.0"

__all__ = ["__version__"]
