from __future__ import annotations

import json
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

    def test_legacy_failed_report_with_only_missing_grade_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = run_pipeline(
                PROJECT_ROOT / "examples" / "profession_config.json",
                Path(directory) / "runs",
                PROJECT_ROOT / "examples" / "sample_vacancies.json",
                run_id="legacy-missing-grade",
            )
            validation_path = Path(report["run_directory"]) / "output" / "validation_report.json"
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            validation["status"] = "failed"
            validation.pop("missing_grades", None)
            validation["leaf_counts"]["junior"] = 0
            validation["graph_issues"]["junior"] = [
                {
                    "severity": "error",
                    "path": validation["profession"],
                    "message": "Корень графа не должен быть пустым.",
                }
            ]
            validation_path.write_text(
                json.dumps(validation, ensure_ascii=False),
                encoding="utf-8",
            )

            result = validate_run_directory(report["run_directory"])

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["missing_grades"], ["junior"])
            self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
