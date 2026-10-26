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


# --- #23 D3 : redémarrage piloté (unités .path / -reload, StateDirectory, code 4) -----------------
STATE = "/var/lib/btmux/adapters.yaml"
D3_UNITS = (
    "btmuxd.service",
    "btmux-adapters.service",
    "btmux-adapters.path",
    "btmux-adapters-reload.service",
    "btmux-adapters-identity.path",
    "btmux-adapters-identity.service",
)


def _unit(name: str) -> str:
    return (ROOT / "systemd" / name).read_text()


def test_path_unit_watches_the_state_file_and_triggers_reload() -> None:
    unit = _unit("btmux-adapters.path")
    assert f"PathChanged={STATE}\n" in unit
    assert "Unit=btmux-adapters-reload.service\n" in unit
    assert "WantedBy=multi-user.target" in unit


def test_reload_unit_only_restarts_btmuxd_without_blocking() -> None:
    unit = _unit("btmux-adapters-reload.service")
    assert "Type=oneshot" in unit and "User=" not in unit  # root : systemctl restart
    assert "ExecStart=/usr/bin/systemctl restart --no-block btmuxd.service\n" in unit
    # identité appliquée une seule fois, par l'ExecStartPre de btmuxd (pas de double application) ;
    # pas d'ExecStartPost : le SIGTERM part aussitôt, sans course avec le repli code 4.
    assert "btmux-adapters.sh --" not in unit
    assert "\nExecStartPost=" not in unit
    assert "\n[Install]" not in unit  # déclenchée uniquement par btmux-adapters.path
    assert "RemainAfterExit" not in unit  # chaque changement doit pouvoir la relancer


def test_btmuxd_unit_reapplies_controller_identity_on_every_start() -> None:
    """Repli code 4 : Restart= ne rejoue pas btmux-adapters.service (oneshot déjà active)."""
    unit = _unit("btmuxd.service")
    pre = (
        f"ExecStartPre=-+/usr/lib/btmux/btmux-adapters.sh --state {STATE} "
        "--config /etc/btmux/config.yaml --wait 0\n"
    )
    assert pre in unit  # '-' : jamais bloquant ; '+' : root hors bac à sable
    assert unit.count("ExecStartPre=") == 1
    assert unit.index(pre) < unit.index("ExecStart=/opt/btmux/bin/btmuxd")
    assert "--reset" not in pre
    assert "TimeoutStartSec=90\n" in unit  # couvre ExecStartPre (btmgmt plafonné à 10 s par appel)
    assert "RestartSec=30\n" in unit and "RestartForceExitStatus=4\n" in unit
    assert "30 s" in unit and "20 s" not in unit  # délai de repli du daemon (RESTART_TIMEOUT_S)


def test_d3_units_and_deploy_document_the_30s_fallback() -> None:
    assert "30 s" in _unit("btmux-adapters.path") and "20 s" not in _unit("btmux-adapters.path")
    deploy = (ROOT / "scripts" / "deploy.sh").read_text()
    assert "repli code 4 après 30 s" in deploy and "repli code 4 après 20 s" not in deploy


def test_btmuxd_unit_has_state_directory_fallback_code_and_path_dependency() -> None:
    unit = _unit("btmuxd.service")
    for line in (
        "StateDirectory=btmux\n",
        "StateDirectoryMode=0750\n",
        "RestartForceExitStatus=4\n",
        "Wants=btmux-adapters.path\n",
        "Restart=on-failure\n",
    ):
        assert line in unit, line
    assert (
        f"ExecStopPost=-+/usr/lib/btmux/btmux-adapters.sh --state {STATE} "
        "--config /etc/btmux/config.yaml --reset --wait 0\n" in unit
    )
    assert "RestartPreventExitStatus=2 4" not in unit  # le repli code 4 doit relancer


def test_boot_adapters_unit_reads_the_effective_list() -> None:
    unit = _unit("btmux-adapters.service")
    assert f"--state {STATE} --config /etc/btmux/config.yaml --wait 30" in unit


def test_configure_installs_all_units_and_state_directory(tmp_path: Path) -> None:
    fake_root = tmp_path / "root"
    env = {
        **os.environ,
        "BTMUX_ROOT": str(fake_root),
        "BTMUX_UID": "1234",
        "BTMUX_HOME": str(tmp_path / "home"),
    }
    (tmp_path / "home").mkdir()
    proc = subprocess.run(
        [
            "sh",
            str(CONFIGURE),
            "--user",
            "alice",
            "--share",
            str(_share(tmp_path)),
            "--units",
            str(ROOT / "systemd"),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    for name in D3_UNITS:
        assert (fake_root / "etc/systemd/system" / name).read_text() == _unit(name), name
    state_dir = fake_root / "var/lib/btmux"
    assert state_dir.is_dir() and oct(state_dir.stat().st_mode & 0o777) == "0o750"


def test_configure_keeps_an_existing_state_file(tmp_path: Path) -> None:
    assert _configure(tmp_path).returncode == 0
    state = tmp_path / "root/var/lib/btmux/adapters.yaml"
    state.write_text("adapters: []\n")
    assert _configure(tmp_path).returncode == 0
    assert state.read_text() == "adapters: []\n"


def test_configure_enables_the_path_unit() -> None:
    text = CONFIGURE.read_text()
    assert (
        "systemctl enable btmux-adapters.service btmux-adapters.path btmux-adapters-identity.path "
        "btmuxd.service" in text
    )
    assert "systemctl restart btmux-adapters.path" in text
    assert "systemctl restart btmux-adapters-identity.path" in text


def test_deploy_ships_all_units() -> None:
    text = (ROOT / "scripts" / "deploy.sh").read_text()
    for name in D3_UNITS:
        assert text.count(f"systemd/{name}") >= 2, name  # contrôle de présence + scp


@needs_dpkg
def test_build_deb_ships_d3_units_and_maintainer_scripts_handle_them(tmp_path: Path) -> None:
    proc, dist = _build(tmp_path, "0.2.0", ["btmux-0.2.0.5-py3-none-any.whl"])
    assert proc.returncode == 0, proc.stderr
    deb = dist / "btmux_0.2.0_all.deb"
    contents = subprocess.run(
        ["dpkg-deb", "--contents", str(deb)], capture_output=True, text=True
    ).stdout
    for name in D3_UNITS:
        assert f"lib/systemd/system/{name}" in contents, name
    ctrl = tmp_path / "ctrl"
    subprocess.run(["dpkg-deb", "-e", str(deb), str(ctrl)], check=True)
    prerm = (ctrl / "prerm").read_text()
    assert prerm.index("systemctl stop btmux-adapters.path") < prerm.index("btmuxd.service")
    assert "disable btmuxd.service btmux-adapters.service btmux-adapters.path" in prerm
    assert prerm.index("btmux-adapters-identity.path") < prerm.index("btmuxd.service")
    assert "btmux-adapters-identity.service" in prerm
    assert prerm.count("btmux-adapters-identity.path") == 2  # stop puis disable (remove)
    assert "/var/lib/btmux" in (ctrl / "postrm").read_text().split("purge)", 1)[1]


# --- #23 hotplug : requête d'identité (identity.request -> .path -> service root, sans restart) ---
REQUEST = "/var/lib/btmux/identity.request"


def test_identity_path_unit_watches_the_request_file() -> None:
    unit = _unit("btmux-adapters-identity.path")
    assert f"PathChanged={REQUEST}\n" in unit
    assert "Unit=btmux-adapters-identity.service\n" in unit
    assert "WantedBy=multi-user.target" in unit
    assert "udev" in unit  # « pas de règle udev » reste documenté


def test_identity_service_replays_the_identity_pass_without_restarting_btmuxd() -> None:
    unit = _unit("btmux-adapters-identity.service")
    assert "Type=oneshot\n" in unit and "User=" not in unit  # root : btmgmt, busctl set-property
    # seuls les contrôleurs réapparus (3e champ de chaque ligne), lus par le script lui-même (#23)
    assert (
        "ExecStart=/usr/lib/btmux/btmux-adapters.sh "
        f"--state {STATE} --config /etc/btmux/config.yaml --wait 5 --requests {REQUEST} "
        "--done-file /run/btmux-identity/done\n" in unit
    )
    assert "/bin/sh" not in unit and "head -n" not in unit  # plus de lecture shell dans l'unité
    assert "StartLimitIntervalSec=0\n" in unit  # un dongle instable ne suspend pas la surveillance
    assert "SuccessExitStatus=2\n" in unit  # config invalide : journalisée, l'unité n'échoue jamais
    assert unit.count("ExecStart=") == 1 and "--reset" not in unit
    assert "systemctl restart" not in unit  # ni redémarrage de btmuxd, ni coupure de l'API
    assert "After=bluetooth.service" in unit
    assert "ConditionPathExists=/etc/btmux/config.yaml\n" in unit
    assert "TimeoutStartSec=60\n" in unit
    assert "Environment=BTMUX_TRIGGER=hotplug\n" in unit
    assert "\n[Install]" not in unit  # déclenchée uniquement par le .path
    assert "RemainAfterExit" not in unit  # chaque requête doit pouvoir la relancer


def test_btmuxd_wants_the_identity_path_and_units_name_their_trigger() -> None:
    unit = _unit("btmuxd.service")
    assert "Wants=btmux-adapters-identity.path\n" in unit
    assert "Environment=BTMUX_TRIGGER=btmuxd\n" in unit
    assert "Environment=BTMUX_TRIGGER=boot\n" in _unit("btmux-adapters.service")


def test_configure_creates_an_empty_identity_request_and_keeps_it(tmp_path: Path) -> None:
    assert _configure(tmp_path).returncode == 0
    req = tmp_path / "root/var/lib/btmux/identity.request"
    assert req.is_file() and req.read_text() == ""
    assert oct(req.stat().st_mode & 0o777) == "0o640"
    req.write_text("2026-10-24T21:00:00+02:00\thci1\tAA:BB:CC:00:00:02\n")
    assert _configure(tmp_path).returncode == 0
    assert req.read_text().startswith("2026-10-24T21:00:00")


def test_deploy_warns_when_the_identity_path_is_inactive() -> None:
    text = (ROOT / "scripts" / "deploy.sh").read_text()
    assert "systemctl is-active --quiet btmux-adapters-identity.path" in text
