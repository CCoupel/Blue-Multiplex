"""Packaging déterministe (#17) : btmux-configure.sh, build-deb.sh, unité, lockfile."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIGURE = ROOT / "scripts" / "btmux-configure.sh"
BUILD_DEB = ROOT / "scripts" / "build-deb.sh"


def _share(tmp_path: Path) -> Path:
    share = tmp_path / "share"
    share.mkdir(exist_ok=True)
    shutil.copy(ROOT / "config" / "config.example.yaml", share)
    shutil.copy(ROOT / "config" / "dbus" / "btmux.conf.in", share / "btmux.conf.in")
    shutil.copy(ROOT / "config" / "wireplumber" / "51-btmux-no-seat.conf", share)
    shutil.copy(ROOT / "config" / "wireplumber" / "roles.conf", share)
    return share


def _configure(
    tmp_path: Path, user: str = "alice", template: str | None = "keep"
) -> subprocess.CompletedProcess[str]:
    """`template` : "keep" = gabarit réel ; None = absent ; autre = contenu imposé."""
    fake_root = tmp_path / "root"
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "BTMUX_ROOT": str(fake_root),
        "BTMUX_UID": "1234",
        "BTMUX_HOME": str(home),
    }
    share = _share(tmp_path)
    if template is None:
        (share / "btmux.conf.in").unlink()
    elif template != "keep":
        (share / "btmux.conf.in").write_text(template)
    return subprocess.run(
        ["sh", str(CONFIGURE), "--user", user, "--share", str(share)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_configure_installs_config_policy_token_and_dropin(tmp_path: Path) -> None:
    proc = _configure(tmp_path)
    assert proc.returncode == 0, proc.stderr
    root = tmp_path / "root"
    assert (root / "etc/btmux/config.yaml").read_text() == (
        ROOT / "config/config.example.yaml"
    ).read_text()
    policy = (root / "etc/dbus-1/system.d/btmux.conf").read_text()
    assert 'user="alice"' in policy and "@BTMUX_USER@" not in policy and 'user="*"' not in policy
    token = root / "etc/btmux/token"
    assert oct(token.stat().st_mode & 0o777) == "0o600" and len(token.read_text()) == 64
    dropin = (root / "etc/systemd/system/btmuxd.service.d/user.conf").read_text()
    assert "User=alice" in dropin and "ReadWritePaths=-/run/user/1234" in dropin
    assert (tmp_path / "home/.config/wireplumber/wireplumber.conf.d/51-btmux-no-seat.conf").exists()
    for script in ("btmux-adapters.sh", "btmux-configure.sh", "btmux-set-user.sh"):
        assert os.access(root / "usr/lib/btmux" / script, os.X_OK)


def test_configure_is_idempotent_and_keeps_token_and_config(tmp_path: Path) -> None:
    assert _configure(tmp_path).returncode == 0
    root = tmp_path / "root"
    token = (root / "etc/btmux/token").read_text()
    (root / "etc/btmux/config.yaml").write_text("# modifiée par l'administrateur\n")
    proc = _configure(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert (root / "etc/btmux/token").read_text() == token  # jeton non régénéré
    assert (root / "etc/btmux/config.yaml").read_text().startswith("# modifiée")  # config conservée


def test_configure_rejects_root_and_bad_user(tmp_path: Path) -> None:
    for bad in ("root", "a;b", "-x"):
        assert _configure(tmp_path, bad).returncode == 2


# --- build-deb.sh ---------------------------------------------------------------------------------
needs_dpkg = pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="dpkg-deb absent")


def _build(tmp_path: Path, version: str, wheels: list[str], lock: bool = True):
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    for name in wheels:
        (dist / name).write_bytes(b"wheel")
    if lock:
        (dist / "requirements.lock.txt").write_text("pyyaml==6.0 \\\n    --hash=sha256:abc\n")
    env = {**os.environ, "BTMUX_DIST": str(dist), "BUILD_TMPDIR": str(tmp_path / "stage")}
    return subprocess.run(
        ["bash", str(BUILD_DEB), version],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    ), dist


@needs_dpkg
def test_build_deb_contents_and_maintainer_scripts(tmp_path: Path) -> None:
    proc, dist = _build(tmp_path, "0.2.0", ["btmux-0.2.0.1-py3-none-any.whl"])
    assert proc.returncode == 0, proc.stderr
    deb = dist / "btmux_0.2.0_all.deb"
    contents = subprocess.run(
        ["dpkg-deb", "--contents", str(deb)], capture_output=True, text=True
    ).stdout
    for expected in (
        "usr/share/btmux/btmux-0.2.0.1-py3-none-any.whl",
        "usr/share/btmux/requirements.lock.txt",
        "lib/systemd/system/btmuxd.service",
        "lib/systemd/system/btmux-adapters.service",
        "usr/lib/btmux/btmux-adapters.sh",
        "usr/lib/btmux/btmux-configure.sh",
        "usr/share/btmux/wireplumber/51-btmux-no-seat.conf",
        "usr/share/btmux/wireplumber/roles.conf",
        "etc/dbus-1/system.d/btmux.conf",
    ):
        assert expected in contents, expected
    ctrl = tmp_path / "ctrl"
    subprocess.run(["dpkg-deb", "-e", str(deb), str(ctrl)], check=True)
    for script in ("postinst", "prerm", "postrm"):
        assert subprocess.run(["sh", "-n", str(ctrl / script)]).returncode == 0
    postinst = (ctrl / "postinst").read_text()
    assert 'case "$1" in' in postinst and "configure)" in postinst
    assert "--upgrade-deps" not in postinst
    assert (
        "pip install --quiet --only-binary=:all: --require-hashes --no-deps -r "
        "/usr/share/btmux/requirements.lock.txt" in postinst
    )
    assert "--no-index --no-deps --force-reinstall /usr/share/btmux/btmux-*.whl" in postinst
    assert (
        "purge)" in (ctrl / "postrm").read_text()
        and "remove|upgrade|deconfigure" in (ctrl / "prerm").read_text()
    )


@needs_dpkg
def test_build_deb_prefers_tag_wheel_and_rejects_other_versions(tmp_path: Path) -> None:
    proc, dist = _build(
        tmp_path, "0.2.1", ["btmux-0.2.10-py3-none-any.whl"]
    )  # 0.2.10 n'est pas 0.2.1
    assert proc.returncode == 1 and "introuvable" in proc.stderr
    proc, dist = _build(
        tmp_path, "0.2.1", ["btmux-0.2.1-py3-none-any.whl", "btmux-0.2.1.4-py3-none-any.whl"]
    )
    assert proc.returncode == 0, proc.stderr
    contents = subprocess.run(
        ["dpkg-deb", "--contents", str(dist / "btmux_0.2.1_all.deb")],
        capture_output=True,
        text=True,
    ).stdout
    assert "btmux-0.2.1-py3-none-any.whl" in contents and "btmux-0.2.1.4" not in contents


def test_build_deb_requires_lockfile_with_hashes(tmp_path: Path) -> None:
    proc, _ = _build(tmp_path, "0.2.0", ["btmux-0.2.0.1-py3-none-any.whl"], lock=False)
    assert proc.returncode == 1 and "requirements.lock.txt" in proc.stderr


def test_btmuxd_unit_is_hardened() -> None:
    unit = (ROOT / "systemd" / "btmuxd.service").read_text()
    for line in (
        "RestartPreventExitStatus=2\n",
        "RestartSec=30",
        "StartLimitBurst=30",
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "ProtectHome=read-only",
        "PrivateTmp=yes",
        "ReadWritePaths=-/run/user/1000",
    ):
        assert line in unit, line
    assert "RestartPreventExitStatus=2 3" not in unit  # code 3 (adaptateur absent) : on réessaie


def test_ci_exports_hashed_runtime_lockfile() -> None:
    text = (ROOT / "scripts" / "ci.sh").read_text()
    assert "uv export --no-dev --frozen --hashes --no-emit-project" in text
    assert "dist/requirements.lock.txt" in text


def test_configure_fails_cleanly_without_dbus_template(tmp_path: Path) -> None:
    proc = _configure(tmp_path, template=None)
    assert proc.returncode != 0
    assert "btmux.conf.in" in proc.stderr
    system_d = tmp_path / "root" / "etc" / "dbus-1" / "system.d"
    assert not (system_d / "btmux.conf").exists()
    assert not list(system_d.glob(".btmux.conf.*"))  # pas de temporaire résiduel


def test_configure_rejects_empty_dbus_template_and_keeps_policy(tmp_path: Path) -> None:
    assert _configure(tmp_path).returncode == 0
    policy = tmp_path / "root" / "etc" / "dbus-1" / "system.d" / "btmux.conf"
    before = policy.read_text()
    proc = _configure(tmp_path, template="")
    assert proc.returncode != 0 and "policy D-Bus" in proc.stderr
    assert policy.read_text() == before and before.strip()
    assert not list(policy.parent.glob(".btmux.conf.*"))


def test_deploy_and_deb_use_the_same_dbus_template_name() -> None:
    for script in ("deploy.sh", "build-deb.sh", "btmux-configure.sh"):
        text = (ROOT / "scripts" / script).read_text()
        assert "btmux.conf.in" in text and "dbus-btmux.conf.in" not in text
