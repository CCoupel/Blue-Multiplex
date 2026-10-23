"""packaging — export deterministe du lockfile runtime (#17).

Commande : `uv export --no-dev --frozen --hashes`.

Plan v0.2.0 T1.8 : ci.sh produit dist/requirements.lock.txt, utilise par le postinst
(`pip install --require-hashes --no-deps -r`). Ces tests verifient l'export, sans reseau.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess

import pytest
from specsupport import REPO_ROOT

UV = shutil.which("uv")
pytestmark = pytest.mark.skipif(UV is None, reason="uv absent du PATH")

DEV_ONLY = {"ruff", "mypy", "pytest", "pytest-cov", "pip-audit", "types-pyyaml", "coverage"}
RUNTIME = {"pydantic", "pyyaml", "dbus-fast"}


def _export(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [UV, "export", "--no-dev", "--frozen", "--hashes", "--no-emit-project", *extra],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _requirements(text: str) -> dict[str, str]:
    """name -> bloc complet (ligne + continuation `--hash=...`)."""
    blocks: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==", line)
        if m:
            current = m.group(1).lower().replace("_", "-")
            blocks[current] = line
        elif current:
            blocks[current] += "\n" + line
    return blocks


@pytest.fixture(scope="module")
def exported() -> str:
    proc = _export()
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_export_succeeds_with_frozen(exported):
    assert exported.strip()


def test_every_requirement_is_pinned_with_hashes(exported):
    reqs = _requirements(exported)
    assert reqs, "aucune dependance exportee"
    for name, block in reqs.items():
        assert "==" in block.splitlines()[0], f"{name} non epinglee"
        assert "--hash=sha256:" in block, f"{name} sans hash"


def test_runtime_dependencies_are_present(exported):
    names = set(_requirements(exported))
    assert names >= RUNTIME, f"manquantes : {RUNTIME - names}"


def test_dev_dependencies_are_excluded(exported):
    names = set(_requirements(exported))
    assert not (DEV_ONLY & names), f"dependances de dev exportees : {DEV_ONLY & names}"


def test_no_editable_or_local_path_in_runtime_export(exported):
    assert "-e " not in exported
    assert not re.search(r"^\s*file:|@ file://", exported, re.M)


def test_export_is_deterministic():
    a, b = _export(), _export()
    assert a.returncode == b.returncode == 0
    assert a.stdout == b.stdout


def test_frozen_export_does_not_modify_uv_lock():
    lock = REPO_ROOT / "uv.lock"
    before = hashlib.sha256(lock.read_bytes()).hexdigest()
    assert _export().returncode == 0
    assert hashlib.sha256(lock.read_bytes()).hexdigest() == before


def test_uv_lock_is_in_sync_with_pyproject():
    """Rappel BUILD : `uv lock` dans le commit de bump (la version change a chaque build)."""
    proc = subprocess.run(
        [UV, "lock", "--check", "--offline"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_ci_script_exports_the_lockfile():
    """scripts/ci.sh (T1.8) produit dist/requirements.lock.txt avec l'export epingle et hashe."""
    text = (REPO_ROOT / "scripts" / "ci.sh").read_text()
    if "requirements.lock.txt" not in text:
        pytest.xfail(
            "T1.8 #17 (dev-backend, Batch 2) non livre : ci.sh n'exporte pas encore le lockfile"
        )
    assert "--no-dev" in text and "--frozen" in text and "--hashes" in text
