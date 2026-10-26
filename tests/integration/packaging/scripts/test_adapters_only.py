"""packaging — `btmux-adapters.sh --only <MAC>` (répétable), `--requests FICHIER` (#23, aa962d0).

Passe ciblée au hotplug.

Seul le contrôleur réapparu est traité : identité s'il est affecté, simple fermeture sinon ;
les autres ne sont pas touchés (une fenêtre d'appairage ouverte ailleurs reste ouverte).
MAC vide, invalide ou absente : avertissement, code 0. Faux `btmgmt`, `busctl`, `sudo`, Python.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "btmux-adapters.sh"
SERVICE = ROOT / "systemd" / "btmux-adapters-identity.service"

# hci0 = interne (sans rôle), hci1 = sources, hci2 = headsets
BTMGMT_THREE = (
    "Index list with 3 items\n"
    "hci0:\tPrimary controller\n\taddr B8:27:EB:00:00:09 version 9 manufacturer 305\n"
    "hci1:\tPrimary controller\n\taddr AA:BB:CC:00:00:01 version 11 manufacturer 93\n"
    "hci2:\tPrimary controller\n\taddr AA:BB:CC:00:00:02 version 11 manufacturer 93\n"
)
BOTH = "AA:BB:CC:00:00:01\tbtmux\tsources\nAA:BB:CC:00:00:02\tbtmux-hp\theadsets\n"


def _exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(tmp_path: Path, *args: str, cmd: list[str] | None = None):
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "fake.log"
    (tmp_path / "btmgmt.out").write_text(BTMGMT_THREE)
    (tmp_path / "listing").write_text(BOTH)
    _exe(
        bindir / "btmgmt",
        f'case "$*" in info) cat "{tmp_path / "btmgmt.out"}"; exit 0;; esac\n'
        f'echo "btmgmt $*" >> "{log}"\n',
    )
    _exe(
        bindir / "busctl",
        'case "$1" in get-property) echo \'s "old"\'; exit 0;; esac\n'
        f'echo "busctl $*" >> "{log}"\n',
    )
    _exe(bindir / "sudo", 'while [ "${1:-}" = "-n" ]; do shift; done\nexec "$@"\n')
    _exe(bindir / "python", f'cat "{tmp_path / "listing"}"\n')
    env = {
        **{k: v for k, v in os.environ.items() if k != "BTMUX_TRIGGER"},
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "BTMUX_BTMGMT": str(bindir / "btmgmt"),
        "BTMUX_BUSCTL": str(bindir / "busctl"),
        "BTMUX_PYTHON": str(bindir / "python"),
        "BTMUX_ALIAS_WAIT": "0",
    }
    argv = cmd or [
        "bash",
        str(SCRIPT),
        "--config",
        str(tmp_path / "config.yaml"),
        "--wait",
        "0",
        *args,
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True, env=env, cwd=tmp_path, timeout=30, check=False
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


def _touched(calls: list[str], idx: str) -> list[str]:
    return [c for c in calls if f"-i {idx} " in c or f"/org/bluez/hci{idx} " in c]


def test_only_assigned_controller_gets_its_identity_and_nothing_else(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, "--only", "aa:bb:cc:00:00:02")  # casse indifférente
    assert proc.returncode == 0, proc.stderr
    for expected in (
        "btmgmt -i 2 power on",
        "btmgmt -i 2 class 1 12",
        "btmgmt -i 2 bondable off",
        "btmgmt -i 2 discov no",
    ):
        assert expected in calls, expected
    assert [c for c in calls if "/org/bluez/hci2 " in c and "Alias s btmux-hp" in c]
    assert not _touched(calls, "1") and not _touched(calls, "0")  # fenêtre ouverte ailleurs intacte
    assert "contrôleur AA:BB:CC:00:00:02 seul" in proc.stdout


def test_only_unassigned_controller_is_closed_without_identity(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, "--only", "B8:27:EB:00:00:09")
    assert proc.returncode == 0, proc.stderr
    assert calls == ["btmgmt -i 0 bondable off", "btmgmt -i 0 discov no"]


@pytest.mark.parametrize("mac", ["", "pas-une-mac", "AA:BB:CC:00:00", "AA:BB:CC:00:00:0G"])
def test_only_empty_or_invalid_mac_warns_and_exits_0(tmp_path: Path, mac: str) -> None:
    proc, calls = _run(tmp_path, "--only", mac)
    assert proc.returncode == 0
    assert "MAC vide ou invalide" in proc.stderr
    assert calls == []


def test_only_absent_controller_warns_and_exits_0(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, "--only", "AA:BB:CC:00:00:07")
    assert proc.returncode == 0
    assert "AA:BB:CC:00:00:07 absent" in proc.stderr
    assert calls == []


def test_only_requires_an_argument(tmp_path: Path) -> None:
    proc, _ = _run(tmp_path, "--only")
    assert proc.returncode == 2


def test_without_only_every_controller_is_still_handled(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert all(_touched(calls, idx) for idx in ("0", "1", "2"))


def _service_command(tmp_path: Path, request: Path, key: str = "ExecStart=") -> list[str]:
    """ExecStart (ou ExecStopPost) de l'unité, chemins système -> chemins du test."""
    line = next(x for x in SERVICE.read_text().splitlines() if x.startswith(key))
    argv = line.removeprefix(key).split()
    assert argv[0] == "/usr/lib/btmux/btmux-adapters.sh"
    (tmp_path / "run").mkdir(exist_ok=True)  # RuntimeDirectory=btmux-identity
    subst = {
        "/var/lib/btmux/identity.request": str(request),
        "/etc/btmux/config.yaml": str(tmp_path / "config.yaml"),
        "/var/lib/btmux/adapters.yaml": str(tmp_path / "adapters.yaml"),
        "/run/btmux-identity/done": str(tmp_path / "run" / "done"),
    }
    argv = ["bash", str(SCRIPT), *(subst.get(x, x) for x in argv[1:])]
    if "--wait" in argv:
        argv[argv.index("--wait") + 1] = "0"
    return argv


def _req(*macs: str) -> str:
    return "".join(f"2026-10-25T07:12:0{i}Z\thci{i}\t{m}\n" for i, m in enumerate(macs))


def test_service_reads_the_mac_from_the_request_file(tmp_path: Path) -> None:
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:02"))
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0, proc.stderr
    assert "btmgmt -i 2 class 1 12" in calls
    assert not _touched(calls, "1") and not _touched(calls, "0")


def test_service_handles_every_pending_mac_once(tmp_path: Path) -> None:
    """Deux dongles réapparus ensemble : aucune MAC perdue, doublon traité 1 fois."""
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02", "aa:bb:cc:00:00:01"))
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0, proc.stderr
    assert calls.count("btmgmt -i 1 class 4 4") == 1
    assert calls.count("btmgmt -i 2 class 1 12") == 1
    assert not _touched(calls, "0")  # contrôleur interne non demandé : intact
    assert "contrôleurs AA:BB:CC:00:00:01, AA:BB:CC:00:00:02 seuls" in proc.stdout


def test_service_skips_invalid_lines_without_echoing_them(tmp_path: Path) -> None:
    request = tmp_path / "identity.request"
    secret = "root:$6$secrethash:19000:0:99999:7:::"
    request.write_text(secret + "\n" + _req("AA:BB:CC:00:00:02") + "x\thci9\tZZ:ZZ\n\n")
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0, proc.stderr
    assert "btmgmt -i 2 class 1 12" in calls
    assert not _touched(calls, "1")
    assert "2 ligne(s) invalide(s)" in proc.stderr and "MAC invalide" in proc.stderr
    out = proc.stdout + proc.stderr
    assert "secrethash" not in out and "ZZ:ZZ" not in out and "root:" not in out


def test_service_ignores_a_symlinked_request(tmp_path: Path) -> None:
    """Répertoire du compte de service : root ne suit jamais un lien (ex. vers /etc/shadow)."""
    target = tmp_path / "secret"
    target.write_text("root:x\n" + _req("AA:BB:CC:00:00:02"))
    request = tmp_path / "identity.request"
    request.symlink_to(target)
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0
    assert "n'est pas un fichier régulier" in proc.stderr
    assert calls == []
    assert "root:x" not in proc.stdout + proc.stderr


def test_service_ignores_a_request_reached_through_a_symlinked_directory(tmp_path: Path) -> None:
    """Chemin canonique = chemin donné : un répertoire parent remplacé par un lien est refusé."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "identity.request").write_text(_req("AA:BB:CC:00:00:02"))
    (tmp_path / "linked").symlink_to(real_dir)
    proc, calls = _run(
        tmp_path, cmd=_service_command(tmp_path, tmp_path / "linked" / "identity.request")
    )
    assert proc.returncode == 0
    assert "n'est pas un fichier régulier" in proc.stderr
    assert calls == []


def test_service_ignores_a_non_regular_request(tmp_path: Path) -> None:
    request = tmp_path / "identity.request"
    request.mkdir()
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0
    assert "n'est pas un fichier régulier" in proc.stderr
    assert calls == []


@pytest.mark.parametrize("content", [None, "", "\n\n", "garbage\n", "2026-10-25T07:12:03Z\thci2\n"])
def test_service_with_missing_empty_or_invalid_request_exits_0(
    tmp_path: Path, content: str | None
) -> None:
    request = tmp_path / "identity.request"
    if content is not None:
        request.write_text(content)
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0
    assert "aucune MAC valide" in proc.stderr
    assert calls == []
    assert "garbage" not in proc.stderr


def test_only_is_repeatable_and_skips_invalid_values(tmp_path: Path) -> None:
    proc, calls = _run(
        tmp_path, "--only", "AA:BB:CC:00:00:01", "--only", "bad", "--only", "B8:27:EB:00:00:09"
    )
    assert proc.returncode == 0, proc.stderr
    assert "btmgmt -i 1 class 4 4" in calls
    assert "btmgmt -i 0 bondable off" in calls
    assert not _touched(calls, "2")
    assert "MAC vide ou invalide" in proc.stderr and "bad" not in proc.stderr


# --- Requête arrivée pendant la passe (QA Pi 0.2.0.6, écart 1) : relecture bornée ---


def _append_on_class(tmp_path: Path, request: Path, lines: list[str]) -> None:
    """Faux btmgmt : à chaque `class`, ajoute la ligne suivante à la requête (dongle réapparu)."""
    queue = tmp_path / "queue"
    queue.write_text("".join(lines))
    hook = tmp_path / "fakebin" / "btmgmt"
    hook.parent.mkdir(exist_ok=True)
    (tmp_path / "hook.sh").write_text(
        f'case "$*" in *" class "*)\n'
        f'  if [ -s "{queue}" ]; then head -n 1 "{queue}" >> "{request}";'
        f' tail -n +2 "{queue}" > "{queue}.n"; mv "{queue}.n" "{queue}"; fi;;\nesac\n'
    )


def _run_with_hook(
    tmp_path: Path, request: Path, env_extra: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Comme _run, mais le faux btmgmt exécute hook.sh (écriture concurrente de la requête)."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "fake.log"
    (tmp_path / "btmgmt.out").write_text(BTMGMT_THREE)
    (tmp_path / "listing").write_text(BOTH)
    _exe(
        bindir / "btmgmt",
        f'case "$*" in info) cat "{tmp_path / "btmgmt.out"}"; exit 0;; esac\n'
        f'echo "btmgmt $*" >> "{log}"\n'
        f'. "{tmp_path / "hook.sh"}"\n',
    )
    _exe(
        bindir / "busctl",
        'case "$1" in get-property) echo \'s "old"\'; exit 0;; esac\n'
        f'echo "busctl $*" >> "{log}"\n',
    )
    _exe(bindir / "sudo", 'while [ "${1:-}" = "-n" ]; do shift; done\nexec "$@"\n')
    _exe(bindir / "python", f'cat "{tmp_path / "listing"}"\n')
    env = {
        **{k: v for k, v in os.environ.items() if k != "BTMUX_TRIGGER"},
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "BTMUX_BTMGMT": str(bindir / "btmgmt"),
        "BTMUX_BUSCTL": str(bindir / "busctl"),
        "BTMUX_PYTHON": str(bindir / "python"),
        "BTMUX_ALIAS_WAIT": "0",
        **(env_extra or {}),
    }
    proc = subprocess.run(
        _service_command(tmp_path, request),
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=30,
        check=False,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


def test_service_handles_a_request_written_during_the_pass(tmp_path: Path) -> None:
    """2e dongle réapparu ≈3 s après le 1er : traité tout de suite, pas au rattrapage +60 s."""
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:01"))
    _append_on_class(tmp_path, request, [_req("AA:BB:CC:00:00:02").replace("hci0", "hci2")])
    proc, calls = _run_with_hook(tmp_path, request)
    assert proc.returncode == 0, proc.stderr
    assert calls.count("btmgmt -i 1 class 4 4") == 1  # MAC déjà traitée : pas rejouée
    assert calls.count("btmgmt -i 2 class 1 12") == 1
    assert not _touched(calls, "0")
    assert "relecture 1/3" in proc.stdout
    assert proc.stdout.count("passe identité (déclencheur : ") == 2
    assert "contrôleur AA:BB:CC:00:00:02 seul" in proc.stdout


def test_service_reread_ignores_unchanged_or_already_handled_macs(tmp_path: Path) -> None:
    """Même MAC réécrite (en attente d'acquittement) : aucune passe en plus."""
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:02"))
    _append_on_class(tmp_path, request, [_req("aa:bb:cc:00:00:02")])
    proc, calls = _run_with_hook(tmp_path, request)
    assert proc.returncode == 0, proc.stderr
    assert calls.count("btmgmt -i 2 class 1 12") == 1
    assert "relecture" not in proc.stdout
    assert proc.stdout.count("passe identité") == 1


def test_service_reread_is_bounded(tmp_path: Path) -> None:
    """Une MAC nouvelle à chaque passe : au plus N relectures, jamais de boucle."""
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:01"))
    _append_on_class(
        tmp_path,
        request,
        [_req("AA:BB:CC:00:00:02"), _req("B8:27:EB:00:00:09"), _req("AA:BB:CC:00:00:07")],
    )
    (tmp_path / "hook.sh").write_text(
        (tmp_path / "hook.sh").read_text().replace('*" class "*', '*" class "*|*" bondable "*')
    )
    proc, calls = _run_with_hook(tmp_path, request, {"BTMUX_REQUESTS_REREAD": "1"})
    assert proc.returncode == 0, proc.stderr
    assert "relecture 1/1" in proc.stdout and "relecture 2/" not in proc.stdout
    assert proc.stdout.count("passe identité") == 2
    assert "borne de 1 relecture(s) atteinte" in proc.stderr


def test_service_reread_does_not_repeat_invalid_line_warnings(tmp_path: Path) -> None:
    request = tmp_path / "identity.request"
    request.write_text("garbage\n" + _req("AA:BB:CC:00:00:02"))
    _append_on_class(tmp_path, request, [])
    proc, _ = _run_with_hook(tmp_path, request)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.count("ligne(s) invalide(s)") == 1


# --- Requête écrite après la dernière relecture (QA Pi 0.2.0.8, écart 1) : ExecStopPost ---
# Le .path ne relance pas une unité encore active : une écriture entre la dernière relecture
# et la sortie du script était perdue jusqu'à la réémission du daemon (+60 s). L'ExecStopPost
# relit le fichier et relance l'unité (une fois, --no-block) s'il contient une MAC non lue
# par l'exécution qui se termine.


def _rearm(tmp_path: Path, request: Path) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """ExecStopPost de l'unité ; faux systemctl qui journalise ses appels."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    slog = tmp_path / "systemctl.log"
    _exe(bindir / "systemctl", f'echo "systemctl $*" >> "{slog}"\n')
    for fake in ("btmgmt", "busctl", "python"):  # le contrôle ne doit rien toucher d'autre
        _exe(bindir / fake, f'echo "{fake} $*" >> "{tmp_path / "forbidden.log"}"\nexit 1\n')
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "BTMUX_SYSTEMCTL": str(bindir / "systemctl"),
        "BTMUX_BTMGMT": str(bindir / "btmgmt"),
        "BTMUX_BUSCTL": str(bindir / "busctl"),
        "BTMUX_PYTHON": str(bindir / "python"),
    }
    proc = subprocess.run(
        _service_command(tmp_path, request, "ExecStopPost="),
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=30,
        check=False,
    )
    assert not (tmp_path / "forbidden.log").exists()
    calls = slog.read_text().splitlines() if slog.exists() else []
    slog.unlink(missing_ok=True)
    return proc, calls


RELAUNCH = "systemctl start --no-block btmux-adapters-identity.service"


def test_unit_closes_the_window_after_the_last_reread_with_a_post_exit_check() -> None:
    unit = SERVICE.read_text()
    assert unit.count("ExecStopPost=") == 1
    assert "--rearm btmux-adapters-identity.service" in unit
    assert "RuntimeDirectory=btmux-identity\n" in unit and "RuntimeDirectoryMode=0700\n" in unit
    start = next(x for x in unit.splitlines() if x.startswith("ExecStart="))
    stop = next(x for x in unit.splitlines() if x.startswith("ExecStopPost="))
    assert (
        "--done-file /run/btmux-identity/done" in start
        and "--done-file /run/btmux-identity/done" in stop
    )


def test_request_written_after_the_last_reread_relaunches_the_unit_once(tmp_path: Path) -> None:
    """Course QA 0.2.0.8 : 2e requête 16 ms après la dernière relecture -> relance, pas +60 s."""
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:01"))
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0, proc.stderr
    assert "relecture" not in proc.stdout and not _touched(calls, "2")
    # écriture après la dernière relecture, avant la sortie de l'unité (événement .path perdu)
    request.write_text(request.read_text() + _req("AA:BB:CC:00:00:02").replace("hci0", "hci2"))
    post, systemctl = _rearm(tmp_path, request)
    assert post.returncode == 0, post.stderr
    assert systemctl == [RELAUNCH]
    assert "AA:BB:CC:00:00:02 arrivée(s) après la dernière relecture" in post.stdout
    # exécution relancée : traite la nouvelle MAC ; son contrôle ne relance plus (fichier inchangé)
    (tmp_path / "fake.log").unlink()
    proc, calls = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0, proc.stderr
    assert "btmgmt -i 2 class 1 12" in calls
    post, systemctl = _rearm(tmp_path, request)
    assert post.returncode == 0 and systemctl == [] and post.stdout == ""


def test_post_exit_check_without_new_request_does_not_relaunch(tmp_path: Path) -> None:
    """Fichier inchangé, MAC en attente d'acquittement ou lignes invalides : aucune relance."""
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02"))
    proc, _ = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0, proc.stderr
    assert sorted((tmp_path / "run" / "done").read_text().split()) == [
        "AA:BB:CC:00:00:01",
        "AA:BB:CC:00:00:02",
    ]
    for content in (
        request.read_text(),
        _req("aa:bb:cc:00:00:02"),  # réécriture du daemon sans la MAC acquittée
        "garbage\n" + _req("AA:BB:CC:00:00:01"),
        "",
    ):
        request.write_text(content)
        post, systemctl = _rearm(tmp_path, request)
        assert post.returncode == 0, post.stderr
        assert systemctl == [], content
    request.unlink()
    post, systemctl = _rearm(tmp_path, request)
    assert post.returncode == 0 and systemctl == []


def test_post_exit_check_relaunches_for_a_request_on_an_initially_empty_file(
    tmp_path: Path,
) -> None:
    """Sortie anticipée (aucune MAC valide) : suivi écrit quand même, requête tardive vue."""
    request = tmp_path / "identity.request"
    request.write_text("")
    proc, _ = _run(tmp_path, cmd=_service_command(tmp_path, request))
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "run" / "done").read_text().strip() == ""
    request.write_text(_req("AA:BB:CC:00:00:02"))
    _, systemctl = _rearm(tmp_path, request)
    assert systemctl == [RELAUNCH]


def test_post_exit_check_takes_over_macs_left_by_the_reread_bound(tmp_path: Path) -> None:
    """Borne de relecture atteinte : la MAC laissée est relancée tout de suite (pas +60 s)."""
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:01"))
    _append_on_class(
        tmp_path,
        request,
        [_req("AA:BB:CC:00:00:02"), _req("B8:27:EB:00:00:09"), _req("AA:BB:CC:00:00:07")],
    )
    (tmp_path / "hook.sh").write_text(
        (tmp_path / "hook.sh").read_text().replace('*" class "*', '*" class "*|*" bondable "*')
    )
    proc, _ = _run_with_hook(tmp_path, request, {"BTMUX_REQUESTS_REREAD": "1"})
    assert "borne de 1 relecture(s) atteinte" in proc.stderr
    _, systemctl = _rearm(tmp_path, request)
    assert systemctl == [RELAUNCH]


def test_post_exit_check_without_done_file_warns_and_does_not_relaunch(tmp_path: Path) -> None:
    request = tmp_path / "identity.request"
    request.write_text(_req("AA:BB:CC:00:00:02"))
    (tmp_path / "run").mkdir()
    post, systemctl = _rearm(tmp_path, request)
    assert post.returncode == 0 and systemctl == []
    assert "absent — pas de relance" in post.stderr


def test_post_exit_check_survives_a_failing_systemctl(tmp_path: Path) -> None:
    request = tmp_path / "identity.request"
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "done").write_text("\n")
    request.write_text(_req("AA:BB:CC:00:00:02"))
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    _exe(bindir / "systemctl", "exit 1\n")
    env = {**os.environ, "BTMUX_SYSTEMCTL": str(bindir / "systemctl")}
    proc = subprocess.run(
        _service_command(tmp_path, request, "ExecStopPost="),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
    assert "relance de btmux-adapters-identity.service impossible" in proc.stderr


def test_rearm_requires_requests_and_done_file(tmp_path: Path) -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--rearm", "x.service"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 2 and "--rearm exige" in proc.stderr
