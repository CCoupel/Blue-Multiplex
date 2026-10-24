"""LOT-1 / cli — `btmuxctl` est un stub en v0.1.0 (contracts/config-schema.md, Interface CLI)."""

from __future__ import annotations

import pytest
from specsupport import output_of


def test_btmuxctl_stub_prints_not_implemented_and_exits_1(run_btmuxctl):
    proc = run_btmuxctl()
    if "not implemented" not in output_of(proc):
        pytest.skip("btmuxctl implemente (v0.2.0 T2.3) : voir test_btmuxctl_commands.py")
    assert proc.returncode == 1
    assert "btmuxctl: not implemented (v0.3.0)" in output_of(proc)
