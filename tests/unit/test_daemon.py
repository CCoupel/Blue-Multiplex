import asyncio
import os
import signal
from pathlib import Path

import pytest

from btmux import daemon
from btmux.cli import btmuxd


def test_serve_waits_then_stops(capsys: pytest.CaptureFixture[str]) -> None:
    async def scenario() -> int:
        stop = asyncio.Event()
        task = asyncio.create_task(daemon.serve(stop))
        await asyncio.sleep(0.05)
        assert not task.done()
        stop.set()
        return await task

    assert asyncio.run(scenario()) == 0
    out = capsys.readouterr().out
    assert "started — no daemon logic yet (v0.3.0)" in out
    assert "stopped" in out


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_run_stops_on_signal(sig: signal.Signals) -> None:
    def fire() -> None:
        os.kill(os.getpid(), sig)

    original = daemon._run

    async def patched() -> int:
        asyncio.get_running_loop().call_later(0.1, fire)
        return await original()

    daemon._run = patched  # type: ignore[assignment]
    try:
        assert daemon.run() == 0
    finally:
        daemon._run = original  # type: ignore[assignment]


def test_invalid_config_does_not_start_daemon(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon, "run", lambda: pytest.fail("daemon démarré"))
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("adapters: []\n")
    assert btmuxd.main(["--config", str(cfg)]) == 2
    assert "config:" in capsys.readouterr().err
