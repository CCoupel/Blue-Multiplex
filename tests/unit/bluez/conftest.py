from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from fakes import FakeBus, bi_objects

from btmux.bluez.daemon import BluezService
from btmux.config import Config, parse_config

BI_CONFIG = {
    "adapters": [
        {"mac": "AA:BB:CC:00:00:01", "name": "btmux", "roles": ["sources"]},
        {"mac": "AA:BB:CC:00:00:02", "name": "btmux-hp", "roles": ["headsets"]},
    ],
    "devices": [
        {"mac": "11:22:33:44:55:01", "alias": "pc-pro", "kind": "source"},
        {"mac": "11:22:33:44:55:02", "alias": "bose", "kind": "headset"},
    ],
}


@pytest.fixture
def config() -> Config:
    return parse_config(BI_CONFIG)


@pytest.fixture
def bus() -> FakeBus:
    return FakeBus(bi_objects())


@pytest.fixture
def service(config: Config, bus: FakeBus) -> BluezService:
    return BluezService(config, bus, adapter_wait=0.3, retry_interval=0.02)


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> Any:
    """Exécute les tests `async def` avec asyncio.run (pas de plugin pytest-asyncio dans le projet)."""
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(asyncio.wait_for(pyfuncitem.obj(**kwargs), timeout=20))
        return True
    return None
