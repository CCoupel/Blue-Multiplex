import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "mask_evidence", Path(__file__).resolve().parents[2] / "spikes" / "common" / "mask_evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
mask = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mask)

PI = "B8:27:EB:1A:2E:D6"


def test_masks_all_forms_but_keeps_pi() -> None:
    text = f"{PI} aa:bb:cc:11:22:33 dev_AA_BB_CC_11_22_33 AA-BB-CC-11-22-33 bc:93:07:00:00:01"
    out = mask.mask_text(text, PI)
    assert PI in out
    assert "11:22:33" not in out and "11_22_33" not in out and "00:00:01" not in out
    assert "aa:bb:cc:xx:xx:xx" in out and "dev_AA_BB_CC_xx_xx_xx" in out


def test_jsonl_drops_third_party_devices_keeps_session_ones() -> None:
    lines = [
        {"event": "start", "path": "/org/bluez/hci0"},
        {"event": "added", "path": "/org/bluez/hci0/dev_11_22_33_44_55_66", "Name": "PC"},
        {"event": "added", "path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF", "Name": "Voisin"},
        {"event": "changed", "path": "/org/bluez/hci0/dev_11_22_33_44_55_66/fd0"},
    ]
    text = "\n".join(json.dumps(x) for x in lines)
    out = mask.filter_jsonl(text, {"112233445566"})
    kept = [json.loads(x) for x in out.splitlines()]
    assert [k["event"] for k in kept] == ["start", "added", "changed"]
    assert "Voisin" not in out


def test_check_flags_unmasked_mac(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text(f"ok {PI}\nmauvais 11:22:33:44:55:66\n")
    assert mask.check(tmp_path, PI) == 1
    (tmp_path / "a.txt").write_text(f"ok {PI}\nmasqué 11:22:33:xx:xx:xx\n")
    assert mask.check(tmp_path, PI) == 0
