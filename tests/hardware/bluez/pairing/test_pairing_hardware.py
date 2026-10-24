"""hardware / bluez / pairing — #20 sur le Pi reel (UB500, ou BT interne SANS audio).

Scenarios du GATE 4 LOT-2, joues par QA avec l'utilisateur :
  1. fenetre `sources` ouverte -> un telephone s'appaire et est accepte ;
  2. fenetre fermee -> l'appairage entrant est refuse ;
  3. fenetre `headsets` -> un casque (mode appairage) est decouvert puis appaire par le Pi ;
  4. `forget` -> l'appareil n'est plus appaire.
Garde-fous : <= BTMUX_HW_MAX_LINKS liens ACL (defaut 1), aucun audio, watch_hci/link_guard actifs.
Jamais en CI : tag `hardware` ; `pytest -s tests/hardware/bluez/pairing` sur le Pi.
"""

from __future__ import annotations

import pytest
from hwsupport import operator, operator_confirms, wait_for


@pytest.fixture(autouse=True)
def clean_window(hw):
    hw.close_window()
    yield
    hw.close_window()


def test_00_api_state_lists_both_adapters(hw):
    st = hw.state()
    assert st["adapters"]
    assert {a["role"] for a in st["adapters"]} <= {"sources", "headsets"}
    assert all(a["powered"] for a in st["adapters"])


def test_01_sources_window_accepts_incoming_phone_pairing(hw):
    hw.assert_link_budget(extra=1)
    before = set(hw.devices())
    status, w = hw.call("POST", "/api/pairing", {"adapter": "sources", "duration": 120})
    assert status == 202 and w["adapter"] == "sources"
    operator("Sur le TELEPHONE : Parametres > Bluetooth > appairer le casque 'btmux' (accepter).")
    new = wait_for(lambda: set(hw.devices()) - before, timeout=120)
    assert new, "aucun nouvel appareil apres l'appairage"
    dev = hw.devices()[next(iter(new))]
    assert dev["adapter"] == "sources" and dev["paired"] and dev["trusted"]
    operator("Sur le TELEPHONE : ne lancer AUCUN audio ; deconnecter le Bluetooth du telephone.")
    hw.call("POST", f"/api/devices/{dev['mac']}/disconnect")


def test_02_outside_window_incoming_pairing_is_refused(hw):
    before = set(hw.devices())
    st = hw.state()
    assert st["pairing"] is None and all(not a["pairable"] for a in st["adapters"])
    operator("Sur un TELEPHONE (ou un autre appareil) : essayer d'appairer 'btmux' maintenant.")
    assert set(hw.devices()) == before, "un appairage a abouti hors fenetre"
    assert operator_confirms("L'appareil a-t-il bien ete REFUSE (ou 'btmux' invisible) ?")


def test_03_headset_is_discovered_then_paired_by_the_pi(hw):
    hw.assert_link_budget(extra=1)
    status, w = hw.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 120})
    assert status == 202 and w["adapter"] == "headsets"
    operator("Mettre le CASQUE en mode appairage (voyant clignotant).")
    found = wait_for(lambda: hw.call("GET", "/api/discovered")[1], timeout=60)
    assert found, "aucun casque decouvert en 60 s"
    mac = found[0]["mac"]
    status, _ = hw.call("POST", f"/api/devices/{mac}/pair")
    assert status == 202
    dev = wait_for(
        lambda: (d := hw.devices().get(mac)) and d["paired"] and d["connected"] and d, 60
    )
    assert dev, "le casque n'est pas appaire+connecte (connexion initiee par le Pi)"
    assert dev["adapter"] == "headsets" and dev["trusted"] is True
    hw.call("POST", f"/api/devices/{mac}/disconnect")
    wait_for(lambda: not hw.devices()[mac]["connected"], timeout=30)


def test_04_forget_removes_the_pairing(hw):
    paired = [m for m, d in hw.devices().items() if d["paired"]]
    if not paired:
        pytest.skip("aucun appareil appaire (jouer test_01/test_03 avant)")
    mac = paired[0]
    assert hw.call("POST", f"/api/devices/{mac}/forget")[0] == 204
    gone = wait_for(lambda: mac not in hw.devices() or not hw.devices()[mac]["paired"], timeout=15)
    assert gone, "l'appareil est toujours appaire apres forget"
    operator(f"Sur l'appareil {mac} : supprimer aussi 'btmux' de ses appareils Bluetooth connus.")


def test_05_second_window_while_open_is_409(hw):
    assert hw.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})[0] == 202
    assert hw.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 60})[0] == 409


def test_06_unauthenticated_request_is_401(hw):
    status, _ = hw.call("GET", "/api/state", token="invalide")
    assert status == 401
