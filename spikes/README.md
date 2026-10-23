# spikes/ — code jetable d'exploration (phase 0, v0.1.0)

Scripts d'exploration technique, **hors `src/`** : non couverts par mypy/pytest/coverage, seulement lint `ruff`.
Chaque dossier `NN-nom/` correspond à une issue `spike`. Rien ici n'est destiné à la production.

> **Provisoire — à revalider avec dongle RTL8761B** : les premiers spikes tournent sur le Bluetooth interne du
> Pi 3 Model B (`pi-qualif`, BCM43430A1, HCI 4.2 sur UART, antenne partagée avec le Wi-Fi). Voir `docs/install-pi.md` §10.

Convention : l'adaptateur est identifié par sa **MAC** (`BTMUX_ADAPTER_MAC`, jamais `hci0` en dur dans la logique) ;
`common/resolve_adapter.py` traduit MAC → chemin D-Bus `/org/bluez/hciN` (index pour `btmgmt -i`).
Dépendance sur le Pi : `dbus-fast` dans un venv utilisateur (`~/spikes/.venv`), pas d'installation système.
