# Pas de `from __future__ import annotations` ici : dbus-fast interprète les annotations comme des signatures D-Bus.
"""Interface D-Bus `org.bluez.Agent1` : traduit les appels vers `btmux.bluez.agent.Agent`."""

# ruff: noqa: N802, F821, UP037
# mypy: ignore-errors

from typing import Any

from dbus_fast import DBusError
from dbus_fast.service import ServiceInterface, method

from btmux.bluez.errors import AgentRejected


def make_interface(agent: Any) -> Any:
    class AgentInterface(ServiceInterface):
        def __init__(self):
            super().__init__("org.bluez.Agent1")

        @staticmethod
        async def _run(coro):
            try:
                return await coro
            except AgentRejected as exc:
                raise DBusError("org.bluez.Error.Rejected", str(exc)) from exc

        @method()
        def Release(self):
            agent.release()

        @method()
        async def RequestAuthorization(self, device: "o"):
            await self._run(agent.request_authorization(device))

        @method()
        async def AuthorizeService(self, device: "o", uuid: "s"):
            await self._run(agent.authorize_service(device, uuid))

        @method()
        async def RequestConfirmation(self, device: "o", passkey: "u"):
            await self._run(agent.request_confirmation(device, passkey))

        @method()
        async def RequestPinCode(self, device: "o") -> "s":
            return await self._run(agent.request_pin_code(device))

        @method()
        async def RequestPasskey(self, device: "o") -> "u":
            return await self._run(agent.request_passkey(device))

        @method()
        def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
            return None

        @method()
        def DisplayPinCode(self, device: "o", pincode: "s"):
            return None

        @method()
        def Cancel(self):
            agent.cancel()

    return AgentInterface()
