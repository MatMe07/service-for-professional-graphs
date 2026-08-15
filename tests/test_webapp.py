from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from graph_service.webapp import _latest_run_path, make_handler


ROOT = Path(__file__).resolve().parents[1]


class WebAppTests(unittest.TestCase):
    def test_latest_run_uses_modification_time_not_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            misleading = root / "verified-demo"
            newest = root / "20200101T000000Z_demo"
            misleading.mkdir()
            newest.mkdir()
            os.utime(misleading, (10, 10))
            os.utime(newest, (20, 20))
            self.assertEqual(_latest_run_path(root), newest)

    def test_status_and_professions_endpoints(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(ROOT))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(f"{base}/api/status", timeout=5) as response:
                status = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{base}/api/professions", timeout=5) as response:
                professions = json.loads(response.read().decode("utf-8"))
            self.assertEqual(status["storage"], "json_files")
            self.assertEqual(len(professions["items"]), 15)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
