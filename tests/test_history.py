from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graph_service.storage import RunStorage, VacancyHistory


class HistoryTests(unittest.TestCase):
    def test_new_unchanged_and_changed_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = VacancyHistory(Path(directory))
            first = history.record("hh", "1", {"id": "1", "name": "A"})
            second = history.record("hh", "1", {"id": "1", "name": "A"})
            third = history.record("hh", "1", {"id": "1", "name": "B"})
            self.assertEqual(first["status"], "new")
            self.assertEqual(second["status"], "unchanged")
            self.assertEqual(third["status"], "changed")
            index = Path(directory) / third["history_index"]
            self.assertTrue(index.is_file())

    def test_vacancy_id_cannot_escape_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = RunStorage(Path(directory), "run")
            storage.prepare()
            path = storage.save_raw_vacancy("../../outside", {"id": "../../outside"})
            self.assertTrue(path.is_relative_to(storage.raw_dir))
            self.assertTrue(path.is_file())
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("saved_at", record)
            self.assertIn("sha256", record)


if __name__ == "__main__":
    unittest.main()
