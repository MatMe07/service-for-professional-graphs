from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

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
            self.assertTrue(status["hh_html_ready"])
            self.assertTrue(status["public_search_ready"])
            self.assertNotIn("hh_token_ready", status)
            self.assertEqual(len(professions["items"]), 15)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_page_exposes_only_two_collection_sources(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(ROOT))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/", timeout=5
            ) as response:
                page = response.read().decode("utf-8")
            self.assertIn("2A. Вакансии HH.ru", page)
            self.assertIn("2B. Вакансии «Работа России»", page)
            self.assertIn("/api/run/hh-html", page)
            self.assertNotIn("Демо без HH", page)
            self.assertNotIn("Ручные ссылки HH", page)
            self.assertNotIn("HH через API", page)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_hh_html_endpoint_builds_automatic_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            (project_root / "dictionaries").mkdir()
            shutil.copyfile(ROOT / "dictionaries" / "professions.json", project_root / "dictionaries" / "professions.json")
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(project_root))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                body = json.dumps(
                    {
                        "profession": "python_developer",
                        "period_days": 30,
                        "max_pages": 3,
                        "max_vacancies": 50,
                        "area": "1",
                    }
                ).encode("utf-8")
                request = urllib.request.Request(
                    f"{base}/api/run/hh-html",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("graph_service.webapp.run_pipeline", return_value={"status": "ok"}) as mocked:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        report = json.loads(response.read().decode("utf-8"))
                self.assertEqual(report["status"], "ok")
                config_path = Path(mocked.call_args.args[0])
                generated = json.loads(config_path.read_text(encoding="utf-8"))
                source = generated["source"]
                self.assertEqual(source["type"], "hh_requests")
                self.assertEqual(source["period_days"], 30)
                self.assertEqual(source["max_pages"], 3)
                self.assertEqual(source["max_vacancies"], 50)
                self.assertEqual(source["areas"], ["1"])
                self.assertIn("Python Developer", source["relevance_terms"])
                self.assertTrue(source["nodes_path"].endswith("canonical_nodes.json"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_public_search_endpoint_builds_automatic_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            (project_root / "dictionaries").mkdir()
            shutil.copyfile(ROOT / "dictionaries" / "professions.json", project_root / "dictionaries" / "professions.json")
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(project_root))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                body = json.dumps(
                    {"profession": "python_developer", "period_days": 45, "max_pages": 3}
                ).encode("utf-8")
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/run/public-search",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("graph_service.webapp.run_pipeline", return_value={"status": "ok"}) as mocked:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        report = json.loads(response.read().decode("utf-8"))
                self.assertEqual(report["status"], "ok")
                generated = json.loads(Path(mocked.call_args.args[0]).read_text(encoding="utf-8"))
                self.assertEqual(generated["source"]["type"], "trudvsem")
                self.assertEqual(generated["source"]["period_days"], 45)
                self.assertEqual(generated["source"]["max_pages"], 3)
                self.assertTrue(generated["source"]["queries"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
