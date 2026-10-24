"""api — #23 contrôleurs et affectation des rôles (contrats http-endpoints + models, avenant).

Cible `mock` aujourd'hui (BTMUX_API_TARGET=real à venir). Scénarios du mock : `default`
(UART + 2 USB, sources/headsets affectés, pc-pro et xm5 connectés), `swap-ready`
(aucun appareil connecté),
`unassigned`, `uart-only`, `restart-pending`.
"""

from __future__ import annotations

import pytest
from apisupport import TARGET, wait_for

# Coupure de service simulee : jouable sur le mock seulement (pas de systemd en CI) ;
# la preuve reelle passe par la procedure materielle de redemarrage pilote.
mock_only = pytest.mark.skipif(
    TARGET == "real", reason="coupure de service simulee : cible mock uniquement"
)

SRC = "AA:BB:CC:00:00:01"
HP = "AA:BB:CC:00:00:02"
UART = "B8:27:EB:1A:2E:D6"
CONTROLLER_KEYS = {
    "mac",
    "hci",
    "name",
    "bus",
    "usb_id",
    "role",
    "powered",
    "pairable",
    "discoverable",
    "connected_devices",
    "present",
}
ROLES_KEYS = {"sources", "headsets", "source", "pending", "restart_expected"}


@pytest.fixture
def swap(api_factory):
    """Aucun appareil connecte ; redemarrage rapide (temps virtuel x100)."""
    return api_factory("swap-ready", time_scale=100.0)


# --- lecture --------------------------------------------------------------------------------
def test_get_controllers_lists_all_controllers_and_roles(api):
    status, body = api.call("GET", "/api/controllers")
    assert status == 200 and set(body) == {"controllers", "roles"}
    assert len(body["controllers"]) == 3
    for c in body["controllers"]:
        assert set(c) == CONTROLLER_KEYS
        assert c["bus"] in {"usb", "uart", "unknown"}
        assert c["role"] in {"sources", "headsets", None}
    assert set(body["roles"]) == ROLES_KEYS
    assert body["roles"]["pending"] is False and body["roles"]["restart_expected"] is False


def test_unassigned_controller_is_closed(api):
    uart = next(
        c for c in api.call("GET", "/api/controllers")[1]["controllers"] if c["mac"] == UART
    )
    assert uart["role"] is None and uart["pairable"] is False and uart["discoverable"] is False


def test_state_carries_controllers_and_roles(api):
    st = api.call("GET", "/api/state")[1]
    assert {"controllers", "roles"} <= set(st)
    assert st["roles"]["sources"] == SRC and st["roles"]["headsets"] == HP


def test_controllers_require_auth(api):
    assert api.call("GET", "/api/controllers", token=None)[0] == 401
    assert api.call("PUT", "/api/controllers/roles", {}, token=None)[0] == 401


# --- validation (400) -----------------------------------------------------------------------
@pytest.mark.critical
def test_same_controller_for_both_roles_is_rejected(swap):
    status, body = swap.call(
        "PUT", "/api/controllers/roles", {"sources": SRC, "headsets": SRC, "confirm": True}
    )
    assert status == 400 and "error" in body
    assert swap.call("GET", "/api/controllers")[1]["roles"]["pending"] is False


@pytest.mark.critical
def test_same_uart_controller_for_both_roles_is_rejected(swap):
    assert swap.call("PUT", "/api/controllers/roles", {"sources": UART, "headsets": UART})[0] == 400


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"sources": SRC},
        {"sources": SRC, "headsets": "not-a-mac"},
        {"sources": SRC, "headsets": "FF:FF:FF:FF:FF:FF"},
        {"sources": 1, "headsets": HP},
        {"sources": SRC, "headsets": HP, "confirm": "yes"},
        {"sources": SRC, "headsets": HP, "force": True},
    ],
)
def test_invalid_role_change_is_400(swap, body):
    assert swap.call("PUT", "/api/controllers/roles", body)[0] == 400


def test_uart_controller_is_assignable_without_force(swap):
    """D5 : l'interne UART est affectable comme un dongle (pas de 400 « UART sans force »)."""
    status, roles = swap.call("PUT", "/api/controllers/roles", {"sources": UART, "headsets": HP})
    assert status == 202 and roles["sources"] == UART


def test_absent_controller_cannot_be_assigned(api_factory):
    c = api_factory("swap-ready", time_scale=100.0)
    c.call(
        "POST",
        "/__mock__/controllers",
        {"action": "update", "mac": UART, "props": {"present": False}},
        token=None,
    )
    assert c.call("PUT", "/api/controllers/roles", {"sources": UART, "headsets": HP})[0] == 400


# --- conflits (409) -------------------------------------------------------------------------
def test_devices_connected_is_409_with_the_list_in_details(api):
    status, body = api.call("PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC})
    assert status == 409 and body["error"] == "devices_connected"
    macs = {d["mac"] for d in body["details"]}
    assert "11:22:33:44:55:01" in macs and "11:22:33:44:55:03" in macs
    assert api.call("GET", "/api/controllers")[1]["roles"]["pending"] is False


def test_confirm_true_disconnects_then_accepts(api_factory):
    c = api_factory("default", time_scale=100.0)
    status, roles = c.call(
        "PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC, "confirm": True}
    )
    assert status == 202 and roles["pending"] is True
    devices = {d["mac"]: d for d in c.call("GET", "/api/state")[1]["devices"]}
    assert devices["11:22:33:44:55:01"]["connected"] is False  # deconnectes avant l'ecriture
    assert devices["11:22:33:44:55:03"]["connected"] is False


def test_pairing_open_blocks_the_role_change(swap):
    swap.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    status, body = swap.call("PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC})
    assert status == 409 and body["error"] == "pairing_open"


def test_noop_is_200_even_when_a_pairing_window_is_open(swap):
    """Affectation identique : 200 prioritaire sur pairing_open (fenetre intacte)."""
    swap.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    status, roles = swap.call("PUT", "/api/controllers/roles", {"sources": SRC, "headsets": HP})
    assert status == 200 and roles["pending"] is False
    assert swap.call("GET", "/api/state")[1]["pairing"]["open"] is True


def test_noop_is_200_even_while_a_change_is_pending(api_factory):
    """Ordre : 400 -> no-op 200 -> change_pending : l'affectation en cours re-soumise reste 200."""
    c = api_factory("swap-ready", time_scale=1.0)
    assert c.call("PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC})[0] == 202
    status, roles = c.call("PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC})
    assert status == 200 and roles["pending"] is True
    other = c.call("PUT", "/api/controllers/roles", {"sources": SRC, "headsets": HP})
    assert other[0] == 409 and other[1]["error"] == "change_pending"


def test_invalid_body_is_400_even_while_a_change_is_pending(api_factory):
    c = api_factory("swap-ready", time_scale=1.0)
    c.call("PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC})
    assert c.call("PUT", "/api/controllers/roles", {"sources": SRC})[0] == 400


def test_pairing_open_precedes_devices_connected(api_factory):
    c = api_factory("default", time_scale=20.0)
    c.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    status, body = c.call("PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC})
    assert status == 409 and body["error"] == "pairing_open"


def test_state_write_failure_is_500_without_disconnect_nor_pending(api_factory):
    """Echec d'ecriture du fichier d'etat : 500 state_write_failed, ni deconnexion ni pending."""
    c = api_factory("state-write-error")
    before = c.call("GET", "/api/state")[1]
    status, body = c.call(
        "PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC, "confirm": True}
    )
    assert status == 500 and body["error"] == "state_write_failed"
    after = c.call("GET", "/api/state")[1]
    assert after["roles"]["pending"] is False and after["roles"]["restart_expected"] is False
    assert (after["roles"]["sources"], after["roles"]["headsets"]) == (SRC, HP)
    assert [d["connected"] for d in after["devices"]] == [d["connected"] for d in before["devices"]]
    assert any(d["connected"] for d in after["devices"])
    assert c.call("POST", "/api/pairing", {"adapter": "sources", "duration": 5})[0] == 202


def test_unassigned_role_refuses_pairing_and_actions(api_factory):
    c = api_factory("unassigned")
    for role in ("sources", "headsets"):
        status, body = c.call("POST", "/api/pairing", {"adapter": role, "duration": 60})
        assert status == 409 and body["error"] == "role_unassigned"
    assert c.call("POST", "/api/devices/AA:11:22:33:44:55/pair")[0] == 409


def test_partial_assignment_leaves_the_other_role_unassigned(api_factory):
    c = api_factory("uart-only")
    assert c.call("POST", "/api/pairing", {"adapter": "headsets", "duration": 60})[0] == 409
    assert c.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})[0] == 202


@pytest.mark.critical
def test_controller_without_role_stays_closed_even_if_a_window_opens_elsewhere(api):
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60})
    uart = next(
        c for c in api.call("GET", "/api/controllers")[1]["controllers"] if c["mac"] == UART
    )
    assert uart["role"] is None and uart["pairable"] is False and uart["discoverable"] is False


# --- application : 202, ecritures refusees, coupure, retour --------------------------------
def test_accepted_change_is_202_pending_and_events_are_emitted(swap):
    _, lines = swap.sse(
        2,
        trigger=lambda: swap.call(
            "PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC}
        ),
    )
    text = "".join(lines)
    assert "event: controllers" in text and "event: roles" in text
    assert '"pending": true' in text and '"restart_expected": true' in text


def test_change_pending_blocks_every_write_but_not_reads(api_factory):
    c = api_factory("swap-ready", time_scale=1.0)  # delai d'arret de 3 s virtuelles
    assert c.call("PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC})[0] == 202
    for method, path, body in [
        ("POST", "/api/pairing", {"adapter": "sources", "duration": 60}),
        ("DELETE", "/api/pairing", None),
        ("POST", "/api/devices/11:22:33:44:55:02/connect", None),
        ("POST", "/api/devices/11:22:33:44:55:02/forget", None),
        ("PATCH", "/api/devices/11:22:33:44:55:02", {"trusted": False}),
        ("PUT", "/api/controllers/roles", {"sources": SRC, "headsets": HP}),
    ]:
        status, err = c.call(method, path, body)
        assert status == 409 and err["error"] == "change_pending", (method, path)
    assert c.call("GET", "/api/state")[0] == 200
    assert c.call("GET", "/api/controllers")[1]["roles"]["restart_expected"] is True


@mock_only
def test_service_goes_down_then_comes_back_with_the_new_roles(swap):
    assert swap.call("PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC})[0] == 202

    def down():
        try:
            swap.call("GET", "/api/state")
        except OSError:
            return True
        return False

    assert wait_for(down, timeout=10), "l'API aurait du etre coupee pendant le redemarrage"

    def back():
        try:
            return swap.call("GET", "/api/controllers")[1]["roles"]["pending"] is False
        except OSError:
            return False

    assert wait_for(back, timeout=20), "l'API n'est pas revenue"
    roles = swap.call("GET", "/api/controllers")[1]["roles"]
    assert (roles["sources"], roles["headsets"], roles["source"]) == (HP, SRC, "state")
    assert roles["pending"] is False and roles["restart_expected"] is False
    adapters = {a["role"]: a["mac"] for a in swap.call("GET", "/api/state")[1]["adapters"]}
    assert adapters == {"sources": HP, "headsets": SRC}


@mock_only
def test_after_restart_writes_work_again(swap):
    swap.call("PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC})

    def writable():
        try:
            return (
                swap.call("POST", "/api/pairing", {"adapter": "sources", "duration": 5})[0] == 202
            )
        except OSError:
            return False

    assert wait_for(writable, timeout=25)


@mock_only
def test_sse_resyncs_with_a_full_state_and_restarted_ids_after_the_restart(swap):
    swap.call("PUT", "/api/controllers/roles", {"sources": HP, "headsets": SRC})

    def back():
        try:
            return swap.call("GET", "/api/health", token=None)[0] == 200
        except OSError:
            return False

    wait_for(lambda: not back(), timeout=10)
    assert wait_for(back, timeout=25)
    _, lines = swap.sse(1, keep_state=True)
    assert lines[0].startswith("event: state")
    assert "id: 0" in "".join(lines)  # compteur reparti de zero : le client doit se resynchroniser


def test_restart_pending_scenario_reports_pending_at_start(api_factory):
    c = api_factory("restart-pending", time_scale=1.0)
    roles = c.call("GET", "/api/controllers")[1]["roles"]
    assert roles["pending"] is True and roles["restart_expected"] is True


def test_restart_pending_scenario_ends_with_the_service_coming_back(api_factory):
    """Le scenario simule aussi la fin du redemarrage (coupure puis retour, pending retombe)."""
    c = api_factory("restart-pending", time_scale=100.0)

    def back():
        try:
            return c.call("GET", "/api/controllers")[1]["roles"]["pending"] is False
        except OSError:
            return False

    assert wait_for(back, timeout=20)
    roles = c.call("GET", "/api/controllers")[1]["roles"]
    assert roles["restart_expected"] is False and roles["source"] == "state"


def test_same_assignment_again_is_a_noop(swap):
    status, roles = swap.call("PUT", "/api/controllers/roles", {"sources": SRC, "headsets": HP})
    assert status == 200 and roles["pending"] is False


def test_releasing_a_role_with_null_is_accepted(swap):
    status, roles = swap.call("PUT", "/api/controllers/roles", {"sources": SRC, "headsets": None})
    assert status == 202 and roles["headsets"] is None


def test_hotplug_emits_a_controllers_event(api):
    new = {"mac": "AA:BB:CC:00:00:09", "hci": "hci3", "name": "usb3", "bus": "usb"}
    _, lines = api.sse(
        1,
        trigger=lambda: api.call(
            "POST", "/__mock__/controllers", {"action": "add", "controller": new}, token=None
        ),
    )
    assert "event: controllers" in "".join(lines) and "AA:BB:CC:00:00:09" in "".join(lines)
