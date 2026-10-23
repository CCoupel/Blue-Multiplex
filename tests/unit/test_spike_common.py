"""Logique pure des outils de séance spikes/common (sans D-Bus ni matériel)."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "spikes" / "common"
sys.path.insert(0, str(COMMON))
import agent  # noqa: E402
import link_guard  # noqa: E402


def test_link_policy_blocks_excess_per_adapter() -> None:
    policy = link_guard.LinkPolicy({"/org/bluez/hci0": 2}, default_cap=1)
    assert policy.on_connected("/org/bluez/hci0", "/org/bluez/hci0/dev_A") is None
    assert policy.on_connected("/org/bluez/hci0", "/org/bluez/hci0/dev_B") is None
    assert (
        policy.on_connected("/org/bluez/hci0", "/org/bluez/hci0/dev_C") == "/org/bluez/hci0/dev_C"
    )
    # autre adaptateur : plafond par défaut 1, indépendant du premier
    assert policy.on_connected("/org/bluez/hci1", "/org/bluez/hci1/dev_D") is None
    assert (
        policy.on_connected("/org/bluez/hci1", "/org/bluez/hci1/dev_E") == "/org/bluez/hci1/dev_E"
    )
    # une déconnexion libère une place ; reconnexion du même appareil = pas de doublon
    policy.on_disconnected("/org/bluez/hci0", "/org/bluez/hci0/dev_A")
    assert policy.on_connected("/org/bluez/hci0", "/org/bluez/hci0/dev_C") is None
    assert policy.on_connected("/org/bluez/hci0", "/org/bluez/hci0/dev_C") is None


def test_parse_caps() -> None:
    assert link_guard.parse_caps(["sources=2", "headsets=1"]) == {"sources": 2, "headsets": 1}
    for bad in ("sources", "sources=0", "sources=x", "=2"):
        with pytest.raises(ValueError):
            link_guard.parse_caps([bad])


def test_pairing_policy_window_and_adapter() -> None:
    now = [100.0]
    policy = agent.PairingPolicy(sources_adapter="/org/bluez/hci1", clock=lambda: now[0])
    assert not policy.accept_pairing("/org/bluez/hci1")  # fenêtre fermée
    policy.open_window(60)
    assert policy.accept_pairing("/org/bluez/hci1")
    assert not policy.accept_pairing("/org/bluez/hci0")  # mauvais adaptateur (pas `sources`)
    now[0] = 161.0
    assert not policy.accept_pairing("/org/bluez/hci1")  # fenêtre expirée


def test_pairing_policy_window_file(tmp_path: Path) -> None:
    flag = tmp_path / "window.open"
    policy = agent.PairingPolicy(window_file=flag)
    assert not policy.window_open()
    flag.write_text("")
    assert policy.window_open() and policy.accept_pairing(
        "/org/bluez/hci9"
    )  # pas d'adaptateur imposé
    flag.unlink()
    assert not policy.window_open()


def test_service_authorization_only_for_trusted() -> None:
    assert agent.PairingPolicy.accept_service(True)
    assert not agent.PairingPolicy.accept_service(False)


# --- watch_hci.sh : par contrôleur, relançable, sans pkill -f ---
WATCH = COMMON / "watch_hci.sh"


def _wait_for(predicate, timeout: float = 8.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_watch_hci_alerts_only_the_faulty_controller(tmp_path: Path) -> None:
    sysfs = tmp_path / "sys"
    for hci, port in (("hci0", "1-1.2"), ("hci1", "1-1.3")):
        dev = sysfs / "devices" / "usb1" / port / f"{port}:1.0"
        dev.mkdir(parents=True)
        (sysfs / "class" / "bluetooth").mkdir(parents=True, exist_ok=True)
        (sysfs / "class" / "bluetooth" / hci).mkdir()
        (sysfs / "class" / "bluetooth" / hci / "device").symlink_to(dev)
    dmesg = tmp_path / "dmesg.txt"
    dmesg.write_text("")
    fake_dmesg = tmp_path / "fake-dmesg"
    fake_dmesg.write_text(f'#!/bin/sh\ncat "{dmesg}"\n')
    fake_hcitool = tmp_path / "fake-hcitool"
    fake_hcitool.write_text(
        '#!/bin/sh\nif [ "$2" = hci1 ]; then\n'
        '  echo "< ACL AA:BB:CC:00:00:09 handle 12 state 1 lm CENTRAL"\nfi\n'
    )
    fake_btctl = tmp_path / "fake-btctl"
    fake_btctl.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/btctl.log"\n')
    for tool in (fake_dmesg, fake_hcitool, fake_btctl):
        tool.chmod(0o755)
    env = {
        **os.environ,
        "BTMUX_DMESG": str(fake_dmesg),
        "BTMUX_SYSFS": str(sysfs),
        "BTMUX_HCITOOL": str(fake_hcitool),
        "BTMUX_BTCTL": str(fake_btctl),
        "BTMUX_OUT": str(tmp_path),
        "BTMUX_REARM_PAUSE": "0",
    }
    log = tmp_path / "watch.log"
    with log.open("w") as out:
        watcher = subprocess.Popen(
            ["bash", str(WATCH), "--interval", "0.1"],
            env=env,
            stdout=out,
            stderr=out,
            start_new_session=True,
        )
    try:
        assert _wait_for(lambda: log.read_text().count("watch_hci :") == 2)
        assert "port USB='1-1.3'" in log.read_text()
        with dmesg.open("a") as fh:  # erreur dure sur hci1 seulement
            fh.write("[ 10.0] Bluetooth: hci1: command 0x0406 tx timeout\n")
        assert _wait_for(lambda: "ré-armé pour hci1" in log.read_text())
        assert "ALERTE hci1" in log.read_text() and "ALERTE hci0" not in log.read_text()
        assert "disconnect AA:BB:CC:00:00:09" in (tmp_path / "btctl.log").read_text()
        assert watcher.poll() is None  # relançable : continue après l'alerte
        with dmesg.open("a") as fh:  # erreur USB sur le port de hci0
            fh.write("[ 20.0] usb 1-1.2: USB disconnect, device number 5\n")
        assert _wait_for(lambda: "ré-armé pour hci0" in log.read_text())
    finally:
        os.killpg(watcher.pid, signal.SIGKILL)
