from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graph_service.pipeline import run_pipeline
from graph_service.validation import validate_run_directory


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RunValidationTests(unittest.TestCase):
    def test_complete_demo_run_passes_integrity_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = run_pipeline(
                PROJECT_ROOT / "examples" / "profession_config.json",
                Path(directory) / "runs",
                PROJECT_ROOT / "examples" / "sample_vacancies.json",
                run_id="integrity-test",
            )
            result = validate_run_directory(report["run_directory"])
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["graph_files"], 3)
            self.assertGreater(result["json_files_checked"], 20)

    def test_missing_run_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate_run_directory(Path(directory) / "missing")
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["errors"])


if __name__ == "__main__":
    unittest.main()
