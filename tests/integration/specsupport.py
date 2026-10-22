"""Utilitaires partages des tests d integration (tests/integration est sur sys.path)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def assert_has_error(errors: list[str], fragment: str) -> None:
    """Au moins une erreur contient `fragment` (le message exact vient du contrat)."""
    assert any(fragment in e for e in errors), f"{fragment!r} absent de {errors!r}"


def output_of(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr
