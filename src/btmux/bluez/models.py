"""Modèles de l'API (contracts/models.md) ; `to_dict()` produit le JSON exact du contrat."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RoleName = Literal["sources", "headsets"]
KindName = Literal["source", "headset", "unknown"]

UUID_A2DP_SOURCE = "0000110a-0000-1000-8000-00805f9b34fb"
UUID_A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"
UUID_HFP_HF = "0000111e-0000-1000-8000-00805f9b34fb"
UUID_HFP_AG = "0000111f-0000-1000-8000-00805f9b34fb"
UUID_HSP_HS = "00001108-0000-1000-8000-00805f9b34fb"
UUID_HSP_AG = "00001112-0000-1000-8000-00805f9b34fb"
UUID_AVRCP_TG = "0000110c-0000-1000-8000-00805f9b34fb"
UUID_AVRCP_CT = "0000110e-0000-1000-8000-00805f9b34fb"

PROFILE_NAMES = {
    UUID_A2DP_SINK: "a2dp_sink",
    UUID_A2DP_SOURCE: "a2dp_source",
    UUID_HFP_HF: "hfp_hf",
    UUID_HFP_AG: "hfp_ag",
    UUID_HSP_HS: "hsp_hs",
    UUID_HSP_AG: "hsp_ag",
    UUID_AVRCP_TG: "avrcp_tg",
    UUID_AVRCP_CT: "avrcp_ct",
}


def format_class(value: int | None) -> str | None:
    return None if value is None else f"0x{value:06x}"


def profiles_from_uuids(uuids: list[str]) -> list[str]:
    return [PROFILE_NAMES[u.lower()] for u in uuids if u.lower() in PROFILE_NAMES]


def deduce_kind(cls: int | None, uuids: list[str], origin: KindName | None = None) -> KindName:
    """Déduction hors config (models.md).

    Classe majeure 0x04 (audio) avec A2DP sink (ou UUID pas encore connus) → headset ; ordinateur 0x01 /
    téléphone 0x02 → source ; à défaut les UUID (sink seul → headset, source/AG seul → source). Un casque
    annonce souvent A2DP source ET sink : la classe prime. `origin` (appairé par `pair` du Pi → headset,
    par la fenêtre `sources` → source) arbitre les cas restants.
    """
    lowered = {u.lower() for u in uuids}
    has_sink = UUID_A2DP_SINK in lowered
    has_source = bool(lowered & {UUID_A2DP_SOURCE, UUID_HFP_AG, UUID_HSP_AG})
    major = (cls >> 8) & 0x1F if cls is not None else None
    if major == 0x04 and (has_sink or not lowered):
        return "headset"
    if major in (0x01, 0x02):
        return "source"
    if has_sink and not has_source:
        return "headset"
    if has_source and not has_sink:
        return "source"
    return origin or "unknown"


@dataclass(frozen=True)
class AdapterModel:
    role: RoleName
    mac: str
    alias: str
    hci: str
    powered: bool
    discoverable: bool
    pairable: bool
    class_: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "mac": self.mac,
            "alias": self.alias,
            "hci": self.hci,
            "powered": self.powered,
            "discoverable": self.discoverable,
            "pairable": self.pairable,
            "class": self.class_,
        }


@dataclass(frozen=True)
class DeviceModel:
    mac: str
    adapter: RoleName
    alias: str | None
    name: str | None
    kind: KindName
    paired: bool
    trusted: bool
    connected: bool
    blocked: bool
    uuids: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    last_seen: str | None = None
    in_config: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mac": self.mac,
            "adapter": self.adapter,
            "alias": self.alias,
            "name": self.name,
            "kind": self.kind,
            "paired": self.paired,
            "trusted": self.trusted,
            "connected": self.connected,
            "blocked": self.blocked,
            "uuids": list(self.uuids),
            "profiles": list(self.profiles),
            "last_seen": self.last_seen,
            "in_config": self.in_config,
        }


@dataclass(frozen=True)
class DiscoveredModel:
    mac: str
    adapter: RoleName
    name: str
    rssi: int | None
    class_: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mac": self.mac,
            "adapter": self.adapter,
            "name": self.name,
            "rssi": self.rssi,
            "class": self.class_,
        }


@dataclass(frozen=True)
class PairingWindowModel:
    """Fenêtre d'appairage : ouverte (`open=True`) ou objet explicite fermé (jamais `null`)."""

    open: bool
    adapter: RoleName | None
    opened_at: str | None = None
    expires_at: str | None = None
    remaining_s: int | None = None
    closed_at: str | None = None
    reason: str | None = None  # expired | closed | replaced | startup | None

    def to_dict(self) -> dict[str, Any]:
        if self.open:
            return {
                "open": True,
                "adapter": self.adapter,
                "opened_at": self.opened_at,
                "expires_at": self.expires_at,
                "remaining_s": self.remaining_s,
            }
        return {
            "open": False,
            "adapter": self.adapter,
            "closed_at": self.closed_at,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DeviceRemovedModel:
    mac: str
    adapter: RoleName

    def to_dict(self) -> dict[str, Any]:
        return {"mac": self.mac, "adapter": self.adapter}
