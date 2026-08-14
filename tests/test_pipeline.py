from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graph_service.pipeline import run_pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def test_demo_run_creates_all_contract_layers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs_root = Path(directory) / "runs"
            report = run_pipeline(
                config_path=PROJECT_ROOT / "examples" / "profession_config.json",
                vacancies_path=PROJECT_ROOT / "examples" / "sample_vacancies.json",
                runs_root=runs_root,
                run_id="test-run",
            )
            self.assertEqual(report["status"], "ok_with_placeholders")
            self.assertEqual(report["output_nodes"], 9)
            self.assertEqual(report["vacancy_versions"]["new"], 9)
            self.assertGreaterEqual(report["unknown_phrase_candidates"], 0)
            output = Path(report["run_directory"]) / "output"
            graph = json.loads(
                (output / "profession_graphs" / "machine_learning_engineer_jun.json").read_text(encoding="utf-8")
            )
            self.assertEqual(set(graph), {"ML-инженер"})
            image_dictionary_path = next(output.glob("profession_graph_node_images_*/image_dictionary.json"))
            image_dictionary = json.loads(image_dictionary_path.read_text(encoding="utf-8"))
            self.assertEqual(len(image_dictionary["nodes"]["Python"]["contexts"]), 3)
            self.assertTrue(any(output.glob("profession_graph_node_courses_*/course_dictionary.json")))
            normalized_path = next((Path(report["run_directory"]) / "normalized").glob("demo-junior-1_*.json"))
            normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
            self.assertIn("fragments", normalized)
            evidence = json.loads((Path(report["run_directory"]) / "evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(all("section" in item and "fragment_text" in item for item in evidence))
            phrase_candidates = json.loads(
                (Path(report["run_directory"]) / "phrase_candidates.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                {item["phrase"] for item in phrase_candidates["items"]},
                {"Разработка ML-моделей", "Внедрение ML-моделей"},
            )
            self.assertEqual(report["professional_phrase_occurrences"], 1)
            self.assertEqual(report["professional_phrase_candidates"], 2)
            self.assertTrue((Path(report["run_directory"]) / "phrase_evidence.json").exists())
            self.assertIn("professional_phrases", normalized)

            second = run_pipeline(
                config_path=PROJECT_ROOT / "examples" / "profession_config.json",
                vacancies_path=PROJECT_ROOT / "examples" / "sample_vacancies.json",
                runs_root=runs_root,
                run_id="test-run-second",
            )
            self.assertEqual(second["vacancy_versions"]["unchanged"], 9)


if __name__ == "__main__":
    unittest.main()
