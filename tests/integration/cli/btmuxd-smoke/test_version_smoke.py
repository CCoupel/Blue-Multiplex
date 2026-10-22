"""LOT-1 / cli — scenario `smoke` : `btmuxd --version` (verifie qu'une version demarre)."""

from __future__ import annotations

import re

import pytest
from specsupport import output_of


@pytest.mark.smoke
def test_btmuxd_version_prints_name_and_version_exit_0(run_btmuxd):
    proc = run_btmuxd("--version")
    assert proc.returncode == 0, output_of(proc)
    assert re.fullmatch(r"btmuxd \S+", output_of(proc).strip())


@pytest.mark.smoke
def test_btmuxd_version_matches_package_metadata(run_btmuxd):
    from importlib.metadata import version

    proc = run_btmuxd("--version")
    assert output_of(proc).strip() == f"btmuxd {version('btmux')}"
