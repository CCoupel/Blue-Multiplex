# Contrat — Modèles JSON de l'API `btmuxd` v0.2.0

> **Statut : validé au GATE 2 v0.2.0 (2026-10-23 17:12)** — contrat de référence pour LOT-2 « appairages + Web UI » (#20 #21 #16). Serveur aiohttp ; mise à jour en direct par SSE avec repli polling.

```jsonc
State      { "version": "0.2.0.0", "adapters": [Adapter], "devices": [Device], "pairing": PairingWindow,   // pairing : toujours un objet
             "controllers": [Controller], "roles": Roles }                                                 // #23 (validé GATE 2 avenant 2026-10-24)
Controller { "mac": "18:69:45:42:9D:E2", "hci": "hci1", "name": "btmux", "bus": "usb" | "uart" | "unknown",   // #23
             "usb_id": "2357:0604" | null, "role": "sources" | "headsets" | null, "powered": true, "pairable": false,
             "discoverable": false, "connected_devices": 0, "present": true }           // present:false = MAC affectée mais absente ; tout contrôleur présent est affectable (UART compris)
Roles      { "sources": "MAC" | null, "headsets": "MAC" | null, "source": "state" | "config",             // #23 : provenance de l'affectation
             "pending": false, "restart_expected": false }                              // pending:true + restart_expected:true = état écrit, redémarrage du service imminent (D3)
RoleChange { "sources": "MAC" | null, "headsets": "MAC" | null, "confirm": false }                        // corps de PUT /api/controllers/roles
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
Event (SSE) event: adapter|device|pairing|discovered|device.removed|state|controllers|roles   data: <modèle complet>   id: <compteur>
  - `controllers` (#23) : Controller[] complet à chaque apparition/disparition/changement d'un contrôleur (hotplug USB, powered…)
  - `roles` (#23) : Roles `pending:true, restart_expected:true` juste après l'écriture de l'état (dernier événement avant la coupure) ; après le
    redémarrage, le premier événement de toute connexion est un `state` complet (`roles.pending:false`, `source:"state"`). Le compteur `id`
    repart de 1 au redémarrage : un client qui reçoit un `state` ou un `id` inférieur à son `Last-Event-ID` réinitialise sa vue.
  - `pairing` : PairingWindow complet à chaque transition (ouverture, tick optionnel, fermeture avec `open:false` + `reason`)
  - `device.removed` (après `forget`, ou disparition d'un appareil non appairé) : DeviceRemoved ; le client retire la ligne.
    Si l'appareil est dans `config.yaml`, le serveur émet ensuite un `device` « placeholder » (`in_config:true`, `paired:false`,
    `trusted:false`, `connected:false`, `name:null`, `uuids:[]`) : la ligne réapparaît comme « connu de la config, non appairé ».
  - `state` : State complet (après `Last-Event-ID` hors tampon, ou au premier événement de la connexion)
```
Règles : MAC normalisée majuscules ; `kind` = `devices[].kind` si l'appareil est dans la config, sinon déduction
(classe majeure 0x04 audio + UUID A2DP sink → `headset`, UUID A2DP source/HFP AG → `source`), `unknown` sinon.
Les appareils non présents dans `config.yaml` apparaissent avec `in_config: false` (la config n'est **pas** réécrite par l'API en v0.2.0).
