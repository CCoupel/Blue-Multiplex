"""api — authentification par jeton Bearer (contracts/http-endpoints.md) : scenarios `critical`."""

from __future__ import annotations

import pytest
from specsupport import REPO_ROOT

PROTECTED = [
    ("GET", "/api/state"),
    ("GET", "/api/discovered"),
    ("POST", "/api/pairing"),
    ("DELETE", "/api/pairing"),
    ("POST", "/api/devices/11:22:33:44:55:01/connect"),
    ("POST", "/api/devices/11:22:33:44:55:01/forget"),
    ("PATCH", "/api/devices/11:22:33:44:55:01"),
]


@pytest.mark.critical
@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_reject_missing_token(api, method, path):
    status, body = api.call(method, path, {}, token=None)
    assert status == 401
    assert set(body) >= {"error", "message"}


@pytest.mark.critical
@pytest.mark.parametrize(
    "header",
    ["Bearer wrong", "Bearer ", "Basic dDBrM25f", "t0k3n", "Bearer t0k3n-extra", "Bearer  t0k3n"],
)
def test_malformed_or_wrong_credentials_rejected(api, header):
    status, _ = api.call("GET", "/api/state", token=None, headers={"Authorization": header})
    assert status == 401


@pytest.mark.critical
def test_valid_token_is_accepted(api):
    assert api.call("GET", "/api/state")[0] == 200


@pytest.mark.critical
def test_unauthorized_request_does_not_change_state(api):
    api.call("POST", "/api/pairing", {"adapter": "sources", "duration": 60}, token=None)
    assert api.call("GET", "/api/state")[1]["pairing"] is None


@pytest.mark.critical
def test_query_string_token_is_not_accepted_on_regular_routes(api):
    status, _ = api.call("GET", "/api/state?token=t0k3n", token=None)
    assert status == 401


@pytest.mark.critical
def test_health_is_public_and_leaks_no_secret(api):
    status, body = api.call("GET", "/api/health", token=None)
    assert status == 200 and set(body) == {"version", "adapters"}


def test_401_error_body_does_not_echo_the_token(api):
    _, body = api.call(
        "GET", "/api/state", token=None, headers={"Authorization": "Bearer leaky-secret"}
    )
    assert "leaky-secret" not in str(body)


@pytest.mark.critical
def test_real_implementation_compares_token_in_constant_time():
    """Revue du code produit : `hmac.compare_digest` (pas de `==`) dans le module d'auth."""
    auth = REPO_ROOT / "src" / "btmux" / "api" / "auth.py"
    if not auth.exists():
        pytest.skip("src/btmux/api/auth.py absent (T2.3, dev-backend)")
    text = auth.read_text()
    assert "compare_digest" in text
