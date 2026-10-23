# Contrat — Modèles JSON de l'API `btmuxd` v0.2.0

> **Statut : DRAFT** — brouillon contract-first v0.2.0, sous réserve de validation au GATE 2 (LOT-2 « appairages + Web UI »). Non implémenté.

```jsonc
State      { "version": "0.2.0.0", "adapters": [Adapter], "devices": [Device], "pairing": PairingWindow | null }
Adapter    { "role": "sources" | "headsets", "mac": "AA:..", "alias": "btmux", "hci": "hci1", "powered": true,
             "discoverable": false, "pairable": false, "class": "0x6c0404" }
Device     { "mac": "..", "adapter": "sources" | "headsets", "alias": "pc-pro" | null,     // alias config (devices[].alias) ou null
             "name": "MSI-PC", "kind": "source" | "headset" | "unknown",                    // config si connu, sinon déduit de la classe/UUIDs
             "paired": true, "trusted": true, "connected": false, "blocked": false,
             "uuids": ["0000110b-..."], "profiles": ["a2dp_sink","hfp_hf"], "last_seen": "2026-10-23T15:50:00Z" | null,
             "in_config": true }
Discovered { "mac": "..", "adapter": "headsets", "name": "Bose QC45", "rssi": -60, "class": "0x240404" }
PairingWindow { "adapter": "sources" | "headsets", "opened_at": "ISO-8601", "expires_at": "ISO-8601", "remaining_s": 42 }
Event (SSE) event: adapter|device|pairing|discovered   data: <modèle complet>   id: <compteur>
```
Règles : MAC normalisée majuscules ; `kind` = `devices[].kind` si l'appareil est dans la config, sinon déduction
(classe majeure 0x04 audio + UUID A2DP sink → `headset`, UUID A2DP source/HFP AG → `source`), `unknown` sinon.
Les appareils non présents dans `config.yaml` apparaissent avec `in_config: false` (la config n'est **pas** réécrite par l'API en v0.2.0).
