"""Utilitaires partages des tests d integration (tests/integration est sur sys.path)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def assert_has_error(errors: list[str], fragment: str) -> None:
    """Au moins une erreur contient `fragment` (le message exact vient du contrat)."""
    assert any(fragment in e for e in errors), f"{fragment!r} absent de {errors!r}"


def output_of(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


# v0.2.0 LOT-1 : tant que dev-backend n'a pas livre T1.1 (#14 V4 max 2, V11 pairing), ces tests sont
# attendus en echec. xfail non strict : un XPASS ne casse pas la CI. A LEVER (supprimer le marqueur)
# au DONE de dev-backend T1.1.
XFAIL_T11 = pytest.mark.xfail(
    reason="T1.1 #14 (dev-backend) non livre : V4 max 2 adaptateurs / cle pairing (V11)",
    strict=False,
)
