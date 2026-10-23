"""Garde-fou du spike #7 (watch_uart.sh) et erreurs pw-cli du routeur, sans matériel."""

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPIKE = ROOT / "spikes" / "07-routing"
WATCH = SPIKE / "watch_uart.sh"

sys.path.insert(0, str(SPIKE))
import router  # noqa: E402


def _fake_tools(tmp_path: Path) -> dict[str, str]:
    dmesg_file = tmp_path / "dmesg.txt"
    dmesg_file.write_text("")
    fake_dmesg = tmp_path / "fake-dmesg"
    fake_dmesg.write_text(f'#!/bin/sh\ncat "{dmesg_file}"\n')
    fake_btctl = tmp_path / "fake-btctl"
    fake_btctl.write_text(
        f'#!/bin/sh\necho "$@" >> "{tmp_path}/btctl.log"\n'
        'if [ "$1" = devices ]; then echo "Device AA:BB:CC:00:00:01 Casque"; fi\n'
    )
    for tool in (fake_dmesg, fake_btctl):
        tool.chmod(0o755)
    return {
        "BTMUX_DMESG": str(fake_dmesg),
        "BTMUX_BTCTL": str(fake_btctl),
        "BTMUX_OUT": str(tmp_path),
        "BTMUX_REARM_PAUSE": "0",
    }


def _wait_for(predicate, timeout: float = 8.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_watch_stops_router_by_pid_disconnects_and_rearms(tmp_path: Path) -> None:
    env = {**os.environ, **_fake_tools(tmp_path)}
    # faux router : processus dont les arguments contiennent « router.py », PID dans out/router.pid
    dummy = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", "router.py"],
        start_new_session=True,
    )
    (tmp_path / "router.pid").write_text(str(dummy.pid))
    log = tmp_path / "watch.log"
    with log.open("w") as out:
        watcher = subprocess.Popen(
            ["bash", str(WATCH), "0.1"], env=env, stdout=out, stderr=out, start_new_session=True
        )
    try:
        assert _wait_for(lambda: "watch_uart :" in log.read_text())
        # 1) erreurs de trame isolées : seulement consignées
        dmesg = tmp_path / "dmesg.txt"
        dmesg.write_text(
            "2026-01-01T00:00:00,0+00:00 Bluetooth: hci0: Frame reassembly failed (-84)\n"
        )
        assert _wait_for(lambda: "info : 1 Frame reassembly" in log.read_text())
        assert dummy.poll() is None and "ALERTE" not in log.read_text()
        # 2) un tx timeout : alerte, router arrêté par son PID, appareils déconnectés, ré-armement
        with dmesg.open("a") as fh:
            fh.write("2026-01-01T00:00:05,0+00:00 Bluetooth: hci0: command 0x0406 tx timeout\n")
        assert _wait_for(lambda: "ré-armé" in log.read_text())
        assert "ALERTE UART (tx timeout" in log.read_text()
        assert _wait_for(lambda: dummy.poll() is not None)
        assert "disconnect AA:BB:CC:00:00:01" in (tmp_path / "btctl.log").read_text()
        assert watcher.poll() is None  # le garde-fou continue de surveiller
        # 3) un nouveau timeout après ré-armement déclenche une 2e alerte
        with dmesg.open("a") as fh:
            fh.write("2026-01-01T00:00:09,0+00:00 Bluetooth: hci0: command 0x0c24 tx timeout\n")
        assert _wait_for(lambda: log.read_text().count("ALERTE UART") == 2)
    finally:
        for proc in (watcher, dummy):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)


def test_watch_does_not_kill_unrelated_pid(tmp_path: Path) -> None:
    """Un router.pid périmé qui pointe un autre programme ne doit pas être tué."""
    env = {**os.environ, **_fake_tools(tmp_path)}
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    (tmp_path / "router.pid").write_text(str(other.pid))
    log = tmp_path / "watch.log"
    with log.open("w") as out:
        watcher = subprocess.Popen(
            ["bash", str(WATCH), "0.1"], env=env, stdout=out, stderr=out, start_new_session=True
        )
    try:
        assert _wait_for(lambda: "watch_uart :" in log.read_text())
        with (tmp_path / "dmesg.txt").open("a") as fh:
            fh.write("2026-01-01T00:00:05,0+00:00 Bluetooth: hci0: command 0x0406 tx timeout\n")
        assert _wait_for(lambda: "ré-armé" in log.read_text())
        assert other.poll() is None
    finally:
        other.kill()
        os.killpg(watcher.pid, signal.SIGKILL)


def test_pwcli_error_line_is_parsed() -> None:
    line = (
        "remote 0: error id:57 seq:112 res:-22 (Invalid argument): "
        "link-factory: unknown output port 99999"
    )
    match = router.ERROR_RE.search(line)
    assert match is not None
    assert match[2] == "-22" and "unknown output port" in match[4]


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for line in self._lines:
            yield line


def test_pwcli_session_reports_async_errors() -> None:
    session = router.PwCliSession(graph=None)  # type: ignore[arg-type]

    class _Proc:
        stdout = _FakeStdout(
            [
                b"1 = @proxy:57\n",
                b"remote 0: error id:57 seq:1 res:-22 (Invalid argument): link-factory: bad port\n",
            ]
        )
        returncode = None

    session.proc = _Proc()  # type: ignore[assignment]
    asyncio.run(session._drain())
    try:
        session.check()
    except RuntimeError as exc:
        assert "bad port" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("check() aurait dû lever")
    session.check()  # les erreurs sont consommées


def test_pwcli_send_on_dead_session_is_explicit() -> None:
    session = router.PwCliSession(graph=None)  # type: ignore[arg-type]

    class _Dead:
        returncode = 0
        stdin = None

    session.proc = _Dead()  # type: ignore[assignment]
    try:
        asyncio.run(session._send("x\n"))
    except RuntimeError as exc:
        assert "liens qu'elle portait sont perdus" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("_send() aurait dû lever")
