"""Client CLI de l'API btmuxd : `state`, `pairing open|close`, `device pair|connect|disconnect|forget`.

Connexion : `--url` (défaut `$BTMUX_URL` ou http://127.0.0.1:8088) ; jeton : `--token`, `$BTMUX_TOKEN` ou
`/etc/btmux/token` si lisible. Codes de sortie : 0 succès, 1 erreur renvoyée par l'API, 2 usage / réseau.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8088"
DEFAULT_TOKEN_FILE = Path("/etc/btmux/token")
TIMEOUT_S = 90.0  # pair/connect peuvent durer (BlueZ)


# Pas de proxy d'environnement : l'API est locale ou sur le LAN.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class CtlError(Exception):
    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="btmuxctl", description="Client de l'API btmuxd.")
    parser.add_argument("--url", default=os.environ.get("BTMUX_URL", DEFAULT_URL))
    parser.add_argument("--token", default=os.environ.get("BTMUX_TOKEN"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("state", help="affiche l'état (JSON)")
    pairing = sub.add_parser("pairing", help="fenêtre d'appairage").add_subparsers(
        dest="action", required=True
    )
    opener = pairing.add_parser("open", help="ouvre la fenêtre")
    opener.add_argument("adapter", choices=["sources", "headsets"])
    opener.add_argument("duration", nargs="?", type=int, help="secondes (1..300)")
    pairing.add_parser("close", help="ferme la fenêtre")
    device = sub.add_parser("device", help="actions sur un appareil").add_subparsers(
        dest="action", required=True
    )
    for action in ("pair", "connect", "disconnect", "forget"):
        device.add_parser(action).add_argument("mac")
    return parser


def resolve_token(arg: str | None) -> str | None:
    if arg:
        return arg
    try:
        return DEFAULT_TOKEN_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def request(method: str, url: str, token: str | None, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)  # noqa: S310
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        try:
            info = json.loads(exc.read())
            detail = f"{info.get('error', '')}: {info.get('message', '')}"
        except ValueError:
            detail = exc.reason
        raise CtlError(f"HTTP {exc.code} {detail}", 1) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CtlError(f"cannot reach {url}: {getattr(exc, 'reason', exc)}", 2) from exc
    return json.loads(raw) if raw else None


def run(args: argparse.Namespace) -> Any:
    base = args.url.rstrip("/")
    token = resolve_token(args.token)
    if args.command == "state":
        return request("GET", f"{base}/api/state", token)
    if args.command == "pairing":
        if args.action == "close":
            return request("DELETE", f"{base}/api/pairing", token)
        body: dict[str, Any] = {"adapter": args.adapter}
        if args.duration is not None:
            body["duration"] = args.duration
        return request("POST", f"{base}/api/pairing", token, body)
    return request("POST", f"{base}/api/devices/{args.mac}/{args.action}", token)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except CtlError as exc:
        print(f"btmuxctl: {exc}", file=sys.stderr)
        return exc.code
    if result is not None:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
