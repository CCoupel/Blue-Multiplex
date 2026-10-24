import asyncio
import os
import signal

import pytest
from fakes import FakeBus, adapter_obj

from btmux import daemon
from btmux.bluez.daemon import BluezService
from btmux.config import Config, parse_config

CFG = {
    "adapters": [{"mac": "AA:BB:CC:00:00:01", "name": "btmux", "roles": ["sources", "headsets"]}]
}


@pytest.fixture
def config() -> Config:
    return parse_config(CFG)


def test_run_without_system_bus_exits_3(
    config: Config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sans bus système (CI) : l'adaptateur reste introuvable -> code 3 après BTMUX_ADAPTER_WAIT."""
    monkeypatch.setenv("BTMUX_ADAPTER_WAIT", "0.3")
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", "unix:path=/nonexistent/btmux-test-bus")
    assert daemon.run(config) == 3
    assert "adapter not found" in capsys.readouterr().err


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_run_stops_on_signal(
    sig: signal.Signals, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un service BlueZ prêt reste vivant jusqu'au signal, puis sort en 0."""
    bus = FakeBus({"/org/bluez/hci0": adapter_obj("AA:BB:CC:00:00:01")})
    original = BluezService.__init__

    def init(self: BluezService, cfg: Config, *a: object, **kw: object) -> None:
        original(self, cfg, bus, adapter_wait=1, retry_interval=0.02)

    monkeypatch.setattr(BluezService, "__init__", init)

    async def scenario() -> int:
        asyncio.get_running_loop().call_later(0.3, os.kill, os.getpid(), sig)
        return await daemon._run(config)

    assert asyncio.run(scenario()) == 0
