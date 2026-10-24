"""Erreurs typées de la couche BlueZ ; `status` est le code HTTP correspondant (contrat http-endpoints)."""

from __future__ import annotations


class BluezError(Exception):
    """Erreur renvoyée par BlueZ (message D-Bus conservé) — HTTP 502."""

    code = "bluez_error"
    status = 502


class BluezUnavailable(BluezError):
    """BlueZ / bus système injoignable, adaptateur absent — HTTP 503."""

    code = "bluez_unavailable"
    status = 503


class InvalidRequest(BluezError):
    code = "invalid_request"
    status = 400


class NotFound(BluezError):
    """Appareil ou adaptateur inconnu — HTTP 404."""

    code = "not_found"
    status = 404


class WindowClosed(BluezError):
    """Opération qui exige une fenêtre d'appairage ouverte — HTTP 409."""

    code = "window_closed"
    status = 409


class WindowOpen(BluezError):
    """Une fenêtre d'appairage est déjà ouverte — HTTP 409."""

    code = "window_open"
    status = 409


class BondStale(BluezError):
    """Appairage périmé (clé perdue d'un côté) : oublier des deux côtés puis réappairer — HTTP 409."""

    code = "bond_stale"
    status = 409


class AgentRejected(BluezError):
    """Demande de l'agent refusée (traduite en `org.bluez.Error.Rejected`)."""

    code = "rejected"
    status = 403


class AdaptersNotFound(Exception):
    """Adaptateur(s) de la configuration absent(s) de BlueZ après le délai d'attente (code de sortie 3)."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__("adapter not found: " + ", ".join(missing))
        self.missing = missing
