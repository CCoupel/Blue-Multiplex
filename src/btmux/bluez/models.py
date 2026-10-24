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


def deduce_kind(cls: int | None, uuids: list[str]) -> KindName:
    """Déduction hors config (models.md) : classe majeure 0x04 audio + A2DP sink → headset ;
    A2DP source / HFP AG → source."""
    lowered = {u.lower() for u in uuids}
    if lowered & {UUID_A2DP_SOURCE, UUID_HFP_AG, UUID_HSP_AG}:
        return "source"
    if cls is not None and (cls >> 8) & 0x1F == 0x04 and UUID_A2DP_SINK in lowered:
        return "headset"
    return "unknown"


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
    name: str
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
    adapter: RoleName
    opened_at: str
    expires_at: str
    remaining_s: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "opened_at": self.opened_at,
            "expires_at": self.expires_at,
            "remaining_s": self.remaining_s,
        }
