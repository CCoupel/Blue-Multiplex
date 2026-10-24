"""tests/hardware — jamais en CI (tag `hardware`, execute sur le Pi de qualif par /qa).

Prerequis : btmuxd v0.2.0 en marche sur le Pi (BlueZ reel) et variables :
  BTMUX_API_URL    ex. http://127.0.0.1:8088          BTMUX_API_TOKEN   contenu de /etc/btmux/token
  BTMUX_HW_GUARDS=1  (l'operateur confirme que `watch_hci.sh` et `link_guard.py` tournent)
  BTMUX_HW_MAX_LINKS  plafond de liens ACL simultanes (defaut 1 : UB500 ou BT interne SANS audio)
Etapes manuelles (appairer un telephone...) : confirmation au clavier, lancer avec `-s`.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/hardware/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.hardware)


@pytest.fixture(scope="session")
def hw():
    from hwsupport import HardwareApi

    url, token = os.environ.get("BTMUX_API_URL"), os.environ.get("BTMUX_API_TOKEN")
    if not url or not token:
        pytest.skip("BTMUX_API_URL / BTMUX_API_TOKEN non definis : tests hardware non joues")
    if os.environ.get("BTMUX_HW_GUARDS") != "1":
        pytest.skip(
            "garde-fous non confirmes : lancer watch_hci.sh + link_guard.py puis BTMUX_HW_GUARDS=1"
        )
    api = HardwareApi(url, token)
    api.assert_reachable()
    return api
