"""webui — la Web UI est operationnelle sur l'APPLICATION REELLE (ApiServer sur bus D-Bus simule).

Regression QA B1 : `/` sert index.html mais les ressources ne le sont que sous `/static/*` ;
une page qui reference `style.css` / `app.js` sans ce prefixe est inerte. Le test charge `/`,
puis chaque <link href>/<script src> et chaque import de module JS (relatif a l'URL du module),
sans jeton.
"""

from __future__ import annotations

import asyncio
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pytest
from specsupport import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "tests" / "unit" / "bluez"))
fakes = pytest.importorskip("fakes")  # FakeBus de dev-backend (bus D-Bus simule)
aiohttp_test = pytest.importorskip("aiohttp.test_utils")
api_server = pytest.importorskip("btmux.api.server")

BASE = "http://btmux.test"
BI = {
    "adapters": [
        {"mac": "AA:BB:CC:00:00:01", "name": "btmux", "roles": ["sources"]},
        {"mac": "AA:BB:CC:00:00:02", "name": "btmux-hp", "roles": ["headsets"]},
    ],
    "devices": [],
}
IMPORT_RE = re.compile(
    r"""(?:import|export)\s[^;'"]*?from\s*['"]([^'"]+)['"]|import\s*['"]([^'"]+)['"]"""
)


class _Refs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and a.get("href"):
            self.refs.append(a["href"])
        if tag == "script" and a.get("src"):
            self.refs.append(a["src"])


async def _crawl() -> dict[str, int]:
    from btmux.bluez.daemon import BluezService
    from btmux.config import parse_config

    service = BluezService(
        parse_config(BI), fakes.FakeBus(fakes.bi_objects()), adapter_wait=0.3, retry_interval=0.02
    )
    await service._start_once()
    service.ready.set()
    app = api_server.create_app(service, "s3cr3t-token")  # static par defaut : src/btmux/api/static
    statuses: dict[str, int] = {}
    async with aiohttp_test.TestClient(aiohttp_test.TestServer(app)) as client:
        root = await client.get("/")  # aucun jeton
        statuses["/"] = root.status
        if root.status != 200:
            return statuses
        parser = _Refs()
        parser.feed(await root.text())
        pending = [urljoin(BASE + "/", ref) for ref in parser.refs]
        seen: set[str] = set()
        while pending:
            url = pending.pop()
            if url in seen:
                continue
            seen.add(url)
            if urlparse(url).netloc != urlparse(BASE).netloc:
                statuses[url] = -1  # ressource externe : interdite (LAN seul)
                continue
            resp = await client.get(urlparse(url).path)  # aucun jeton
            statuses[urlparse(url).path] = resp.status
            if resp.status == 200 and url.endswith(".js"):
                for m in IMPORT_RE.finditer(await resp.text()):
                    spec = m.group(1) or m.group(2)
                    if spec.startswith((".", "/")):
                        pending.append(urljoin(url, spec))
    return statuses


@pytest.mark.xfail(
    strict=True,
    reason="QA B1 : index.html reference style.css/app.js sans /static/ -> 404 sur l'app reelle ; "
    "passe au vert avec le correctif de dev-frontend (#16) — retirer alors ce xfail",
)
def test_index_and_every_referenced_resource_load_without_token():
    statuses = asyncio.run(asyncio.wait_for(_crawl(), timeout=30))
    assert statuses["/"] == 200
    assert len(statuses) >= 4, f"index + css + app.js + api.js attendus : {statuses}"
    bad = {u: s for u, s in statuses.items() if s != 200}
    assert not bad, f"ressources non chargees : {bad}"


def test_root_is_public_and_serves_html():
    async def run() -> tuple[int, str]:
        statuses = await _crawl()
        return statuses["/"], ""

    status, _ = asyncio.run(asyncio.wait_for(run(), timeout=30))
    assert status == 200


def test_static_serves_the_files_under_static_prefix():
    """Les fichiers sont servis sous /static/ (sans jeton) ; seule la reference etait fausse."""
    from btmux.api.server import STATIC_DIR

    async def run() -> dict[str, int]:
        from btmux.bluez.daemon import BluezService
        from btmux.config import parse_config

        service = BluezService(
            parse_config(BI),
            fakes.FakeBus(fakes.bi_objects()),
            adapter_wait=0.3,
            retry_interval=0.02,
        )
        await service._start_once()
        service.ready.set()
        app = api_server.create_app(service, "t")
        out = {}
        async with aiohttp_test.TestClient(aiohttp_test.TestServer(app)) as client:
            for f in ("style.css", "app.js", "api.js"):
                out[f] = (await client.get(f"/static/{f}")).status
            out["README.md"] = (await client.get("/static/README.md")).status
        return out

    assert Path(STATIC_DIR / "app.js").is_file()
    codes = asyncio.run(asyncio.wait_for(run(), timeout=30))
    assert codes == {"style.css": 200, "app.js": 200, "api.js": 200, "README.md": 404}
