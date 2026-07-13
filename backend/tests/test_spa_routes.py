import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from core.spa import SpaStaticFiles


async def asgi_get(application, path):
    messages = []
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    await asyncio.wait_for(application(scope, receive, send), timeout=5)
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, body.decode()


class SpaRouteTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        dist = Path(cls.temp_dir.name)
        cls.index_html = "<!doctype html><title>VideoMind test app</title>"
        (dist / "index.html").write_text(cls.index_html, encoding="utf-8")
        (dist / "assets").mkdir()
        cls.app = FastAPI()
        cls.app.mount("/", SpaStaticFiles(directory=dist, html=True), name="frontend")

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    async def test_vue_router_deep_links_return_the_spa_entrypoint(self):
        for path in ("/workspace", "/history", "/history/example"):
            with self.subTest(path=path):
                status, body = await asgi_get(self.app, path)

                self.assertEqual(200, status)
                self.assertEqual(self.index_html, body)

    async def test_missing_static_asset_stays_not_found(self):
        status, _ = await asgi_get(self.app, "/assets/missing.js")

        self.assertEqual(404, status)


if __name__ == "__main__":
    unittest.main()
