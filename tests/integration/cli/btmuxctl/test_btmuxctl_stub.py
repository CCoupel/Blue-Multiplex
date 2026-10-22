"""LOT-1 / cli — `btmuxctl` est un stub en v0.1.0 (contracts/config-schema.md, Interface CLI)."""

from __future__ import annotations

from specsupport import output_of


def test_btmuxctl_stub_prints_not_implemented_and_exits_1(run_btmuxctl):
    proc = run_btmuxctl()
    assert proc.returncode == 1
    assert "btmuxctl: not implemented (v0.3.0)" in output_of(proc)
