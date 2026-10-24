"""Erreurs typées de la couche BlueZ ; `status` est le code HTTP correspondant (contrat http-endpoints)."""

from __future__ import annotations


class BluezError(Exception):
    """Erreur renvoyée par BlueZ (message D-Bus conservé) — HTTP 502."""

    code = "bluez_error"
    status = 502


class ApiError(BluezError):
    """Erreur typée avec `details` optionnel (champ du corps d'erreur, contracts/http-endpoints.md)."""

    def __init__(self, message: str, details: list[dict[str, object]] | None = None) -> None:
        super().__init__(message)
        self.details = details


class BluezUnavailable(BluezError):
    """BlueZ / bus système injoignable, adaptateur absent — HTTP 503."""

    code = "bluez_unavailable"
    status = 503


class InvalidRequest(BluezError):
    code = "invalid_request"
    status = 400


class InvalidMac(InvalidRequest):
    code = "invalid_mac"


class NotFound(BluezError):
    """Appareil ou adaptateur inconnu — HTTP 404."""

    code = "not_found"
    status = 404


class UnknownDevice(NotFound):
    """Appareil inconnu de BlueZ et de la configuration."""

    code = "unknown_device"


class NotDiscovered(NotFound):
    """Appareil non vu sur l'adaptateur `headsets` (appairage Pi → casque)."""

    code = "not_discovered"


class RoleUnassigned(BluezError):
    """Le rôle visé n'a pas de contrôleur affecté ou présent (#23) — HTTP 409."""

    code = "role_unassigned"
    status = 409


class ChangePending(ApiError):
    """Changement de rôles accepté, redémarrage imminent : toute écriture est refusée — HTTP 409."""

    code = "change_pending"
    status = 409


class DevicesConnected(ApiError):
    """Des appareils sont connectés sur les rôles modifiés (`confirm:true` pour les déconnecter) — HTTP 409."""

    code = "devices_connected"
    status = 409


class ControllerError(InvalidRequest):
    """Validation de `PUT /api/controllers/roles` — HTTP 400, `code` propre à chaque cas."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OperationInProgress(BluezError):
    """Une opération est déjà en cours sur cet appareil — HTTP 409."""

    code = "operation_in_progress"
    status = 409


class WindowClosed(BluezError):
    """Opération qui exige une fenêtre d'appairage ouverte — HTTP 409."""

    code = "pairing_closed"
    status = 409


class WindowOpen(BluezError):
    """Une fenêtre d'appairage est déjà ouverte — HTTP 409."""

    code = "pairing_open"
    status = 409


class BondStale(BluezError):
    """Appairage périmé (clé perdue d'un côté) : oublier des deux côtés puis réappairer — HTTP 409."""

    code = "stale_bond"
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
