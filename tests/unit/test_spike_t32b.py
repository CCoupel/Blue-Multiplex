"""Fonctions pures de spikes/t32b et de la résolution par adaptateur, sans matériel."""

import array
import math
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
T32B = ROOT / "spikes" / "t32b"
sys.path.insert(0, str(ROOT / "spikes" / "07-routing"))
sys.path.insert(0, str(T32B))
import analyze_latency  # noqa: E402
import impulse_track  # noqa: E402
import profile_watch  # noqa: E402
import pw_graph  # noqa: E402
import router  # noqa: E402
import xrun_log  # noqa: E402


def _graph() -> pw_graph.Graph:
    g = pw_graph.Graph()
    g.devices[10] = pw_graph.Device(
        10, {"api.bluez5.path": "/org/bluez/hci0/dev_84_7B_57_AA_BB_CC"}
    )
    g.devices[11] = pw_graph.Device(
        11, {"api.bluez5.path": "/org/bluez/hci1/dev_28_11_A5_DD_EE_FF"}
    )
    g.nodes[1] = pw_graph.Node(
        1,
        {
            "node.name": "bluez_input.84_7B_57_AA_BB_CC.0",
            "media.class": "Stream/Output/Audio",
            "device.id": 10,
        },
    )
    g.nodes[2] = pw_graph.Node(
        2,
        {
            "node.name": "bluez_output.28_11_A5_DD_EE_FF.1",
            "media.class": "Audio/Sink",
            "device.id": 11,
        },
    )
    g.nodes[3] = pw_graph.Node(3, {"node.name": "virt-srcB", "media.class": "Stream/Output/Audio"})
    return g


def test_resolve_node_by_adapter_and_class() -> None:
    g = _graph()
    assert g.adapter_of(g.nodes[1]) == "hci0" and g.adapter_of(g.nodes[2]) == "hci1"
    assert g.adapter_of(g.nodes[3]) == ""  # nœud virtuel : aucun adaptateur
    assert router.resolve_node(g, "@hci1:Audio/Sink").id == 2
    assert router.resolve_node(g, "@hci0").id == 1
    assert router.resolve_node(g, "@hci0:Stream/Output/Audio:84_7B").id == 1
    assert (
        router.resolve_node(g, "@hci0:Audio/Sink") is None
    )  # mauvais adaptateur pour cette classe
    assert router.resolve_node(g, "virt-srcB").id == 3  # nom exact


def test_switch_times_a2dp_to_hfp() -> None:
    events = [
        (0.0, "a2dp", "running"),
        (5.0, "a2dp", "idle"),  # dernier signe d'activité A2DP
        (6.4, "hfp", "running"),
        (20.0, "hfp", "gone"),
        (20.9, "a2dp", "running"),
    ]
    times = profile_watch.switch_times(events)
    assert [(t["from"], t["to"]) for t in times] == [("a2dp", "hfp"), ("hfp", "a2dp")]
    assert round(float(times[0]["ms"])) == 1400 and round(float(times[1]["ms"])) == 900
    assert profile_watch.profile_of("mSBC") == "hfp" and profile_watch.profile_of("aptx") == "a2dp"
    assert profile_watch.profile_of("") == ""


def _write_stereo(
    path: Path, delay_ms: float, rate: int = 48000, clicks: int = 6, period: float = 1.0
) -> None:
    reference = impulse_track.make_clicks(clicks, period, rate)
    shift = int(rate * delay_ms / 1000)
    delayed = array.array("h", [0] * shift) + reference[: len(reference) - shift]
    inter = array.array("h")
    for a, b in zip(reference, delayed, strict=True):
        inter.extend([a, b])
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(inter.tobytes())


def test_latency_analysis_recovers_known_delay(tmp_path: Path) -> None:
    rec = tmp_path / "rec.wav"
    _write_stereo(rec, 180.0)
    result = analyze_latency.analyze(str(rec))
    assert result["n"] == 6
    assert math.isclose(result["median"], 180.0, abs_tol=2.0)
    assert result["max"] - result["min"] < 3.0


def test_impulse_track_cli_writes_expected_clicks(tmp_path: Path) -> None:
    out = tmp_path / "clicks.wav"
    subprocess.run(
        [
            sys.executable,
            str(T32B / "impulse_track.py"),
            "--out",
            str(out),
            "--count",
            "4",
            "--period",
            "0.5",
        ],
        check=True,
        capture_output=True,
    )
    with wave.open(str(out), "rb") as wav:
        data = array.array("h")
        data.frombytes(wav.readframes(wav.getnframes()))
        rate = wav.getframerate()
    assert len(analyze_latency.onsets(list(data), rate)) == 4


HEADER = "S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR FORMAT  NAME \n"


def test_parse_pw_top_reads_err_per_node() -> None:
    row = "R 55 512 16000 50.3us 286.0us 0.00 0.01 {err} S16LE 1 16000 + bluez_input.84_7B\n"
    sample = HEADER + row.format(err=4) + HEADER + row.format(err=7)
    assert xrun_log.parse_pw_top(sample) == {"bluez_input.84_7B": 7}


def test_session_dry_run_prints_plan_without_starting_anything(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin:/bin", "BTMUX_OUT": str(tmp_path), "HOME": str(tmp_path)}
    proc = subprocess.run(
        ["bash", str(T32B / "session.sh"), "s2", "--dry-run"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (
        "DRY-RUN" in proc.stdout
        and "watch_hci.sh" in proc.stdout
        and "link_guard.py" in proc.stdout
    )
    assert "voice_links.py" in proc.stdout and "analyze_latency.py" in proc.stdout
    assert not list(tmp_path.glob("*.pid"))


def test_preflight_fails_cleanly_without_hardware() -> None:
    proc = subprocess.run(
        ["bash", str(T32B / "preflight.sh")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 1
    assert "ECHEC" in proc.stdout
