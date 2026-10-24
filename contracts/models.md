# Contrat — Modèles JSON de l'API `btmuxd` v0.2.0

> **Statut : validé au GATE 2 v0.2.0 (2026-10-23 17:12)** — contrat de référence pour LOT-2 « appairages + Web UI » (#20 #21 #16). Serveur aiohttp ; mise à jour en direct par SSE avec repli polling.

```jsonc
State      { "version": "0.2.0.0", "adapters": [Adapter], "devices": [Device], "pairing": PairingWindow }   // toujours un objet, jamais null
Adapter    { "role": "sources" | "headsets", "mac": "AA:..", "alias": "btmux", "hci": "hci1", "powered": true,
             "discoverable": false, "pairable": false, "class": "0x6c0404" }
Device     { "mac": "..", "adapter": "sources" | "headsets", "alias": "pc-pro" | null,     // alias config (devices[].alias) ou null
             "name": "MSI-PC", "kind": "source" | "headset" | "unknown",                    // config si connu, sinon déduit de la classe/UUIDs
             "paired": true, "trusted": true, "connected": false, "blocked": false,
             "uuids": ["0000110b-..."], "profiles": ["a2dp_sink","hfp_hf"], "last_seen": "2026-10-23T15:50:00Z" | null,
             "in_config": true }
Discovered { "mac": "..", "adapter": "headsets", "name": "Bose QC45", "rssi": -60, "class": "0x240404" }
PairingWindow { "open": true,  "adapter": "sources" | "headsets", "opened_at": "ISO-8601", "expires_at": "ISO-8601", "remaining_s": 42 }
           |  { "open": false, "adapter": "sources" | "headsets" | null, "closed_at": "ISO-8601" | null,
                "reason": "expired" | "closed" | "replaced" | "startup" | null }                       // fermée : objet explicite, JAMAIS null
DeviceRemoved { "mac": "..", "adapter": "sources" | "headsets" }
Event (SSE) event: adapter|device|pairing|discovered|device.removed|state   data: <modèle complet>   id: <compteur>
  - `pairing` : PairingWindow complet à chaque transition (ouverture, tick optionnel, fermeture avec `open:false` + `reason`)
  - `device.removed` (après `forget`, ou disparition d'un appareil non appairé) : DeviceRemoved ; le client retire la ligne.
    Si l'appareil est dans `config.yaml`, le serveur émet ensuite un `device` « placeholder » (`in_config:true`, `paired:false`,
    `trusted:false`, `connected:false`, `name:null`, `uuids:[]`) : la ligne réapparaît comme « connu de la config, non appairé ».
  - `state` : State complet (après `Last-Event-ID` hors tampon, ou au premier événement de la connexion)
```
Règles : MAC normalisée majuscules ; `kind` = `devices[].kind` si l'appareil est dans la config, sinon déduction
(classe majeure 0x04 audio + UUID A2DP sink → `headset`, UUID A2DP source/HFP AG → `source`), `unknown` sinon.
Les appareils non présents dans `config.yaml` apparaissent avec `in_config: false` (la config n'est **pas** réécrite par l'API en v0.2.0).
