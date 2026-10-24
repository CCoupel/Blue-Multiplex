"""Fixtures des tests d'API : cible `mock` (tests/fixtures/api-mock) ou `real` (btmux.api + FakeBus).

BTMUX_API_TARGET=mock (defaut) | real. La cible `real` attend le harnais de l'application reelle
(T2.3, dev-backend) : tant qu'il manque, ces tests sont skippes — pas d'echec.
"""

from __future__ import annotations

import pytest
from apisupport import TARGET, TOKEN, Client, mock_mod


@pytest.fixture
def api_factory():
    """`api_factory(scenario="default", time_scale=20)` -> Client ; arrete les serveurs a la fin."""
    started = []

    def _make(scenario="default", time_scale=20.0):
        if TARGET != "mock":
            pytest.skip("cible `real` : harnais de l'application reelle (T2.3) non disponible")
        api = mock_mod.MockApi(scenario, token=TOKEN, time_scale=time_scale).start()
        started.append(api)
        return Client(api)

    yield _make
    for a in started:
        a.stop()


@pytest.fixture
def api(api_factory):
    return api_factory("default")
