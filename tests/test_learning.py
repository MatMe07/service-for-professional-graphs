from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graph_service.learning import build_course_dictionary


ROOT = Path(__file__).resolve().parents[1]


class LearningCatalogTests(unittest.TestCase):
    def test_catalog_builds_nonempty_courses_and_honest_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            courses = build_course_dictionary(
                root,
                {"Python", "Docker", "Неизвестная нода"},
                ROOT / "dictionaries" / "learning_resources.json",
            )
            self.assertTrue(courses["Python"])
            self.assertTrue(courses["Docker"])
            self.assertEqual(courses["Неизвестная нода"], [])
            coverage = json.loads((root / "coverage.json").read_text(encoding="utf-8"))
            self.assertEqual(coverage["status"], "partial")
            self.assertEqual(coverage["nodes_with_materials"], 2)


if __name__ == "__main__":
    unittest.main()
