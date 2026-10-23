# Pas de `from __future__ import annotations` ici : dbus-fast interprète les annotations comme des signatures D-Bus.
"""Interface D-Bus `org.bluez.Agent1` (NoInputNoOutput) — voir agent.py pour la politique d'acceptation."""

# ruff: noqa: N802, F821, UP037


def make_agent_class():
    from dbus_fast import DBusError
    from dbus_fast.service import ServiceInterface, method

    class Agent(ServiceInterface):
        def __init__(self, decide, on_accepted, log):
            super().__init__("org.bluez.Agent1")
            self._decide, self._on_accepted, self._log = decide, on_accepted, log

        async def _gate(self, kind, device):
            if not await self._decide(kind, device):
                self._log(f"REFUS {kind} {device}")
                raise DBusError(
                    "org.bluez.Error.Rejected",
                    f"{kind} refusé (fenêtre fermée ou appareil inconnu)",
                )
            self._log(f"ACCEPTÉ {kind} {device}")
            self._on_accepted(device)

        @method()
        def Release(self):
            self._log("agent relâché par BlueZ")

        @method()
        async def RequestAuthorization(self, device: "o"):
            await self._gate("RequestAuthorization", device)

        @method()
        async def AuthorizeService(self, device: "o", uuid: "s"):
            await self._gate(f"AuthorizeService {uuid}", device)

        @method()
        async def RequestConfirmation(self, device: "o", passkey: "u"):
            await self._gate("RequestConfirmation", device)

        @method()
        async def RequestPinCode(self, device: "o") -> "s":
            await self._gate("RequestPinCode", device)
            return "0000"

        @method()
        async def RequestPasskey(self, device: "o") -> "u":
            await self._gate("RequestPasskey", device)
            return 0

        @method()
        def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
            return None

        @method()
        def DisplayPinCode(self, device: "o", pincode: "s"):
            return None

        @method()
        def Cancel(self):
            self._log("opération annulée")

    return Agent
