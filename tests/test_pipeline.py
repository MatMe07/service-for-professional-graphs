from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            self.assertEqual(report["repeated_boilerplate_blocks"], 1)
            self.assertEqual(report["repeated_boilerplate_fragment_occurrences"], 2)
            self.assertEqual(report["excluded_evidence_count"], 2)
            self.assertTrue((Path(report["run_directory"]) / "phrase_evidence.json").exists())
            self.assertIn("professional_phrases", normalized)
            self.assertTrue((Path(report["run_directory"]) / "review_report.html").exists())
            self.assertTrue((Path(report["run_directory"]) / "review_decisions_template.json").exists())
            self.assertTrue((Path(report["run_directory"]) / "grade_conflicts.json").exists())

            second = run_pipeline(
                config_path=PROJECT_ROOT / "examples" / "profession_config.json",
                vacancies_path=PROJECT_ROOT / "examples" / "sample_vacancies.json",
                runs_root=runs_root,
                run_id="test-run-second",
            )
            self.assertEqual(second["vacancy_versions"]["unchanged"], 9)


class FakeAggregator:
    def __init__(
        self,
        providers=None,
        max_per_node: int = 4,
        quotas=None,
        youtube_api_key_env: str = "YOUTUBE_API_KEY",
    ) -> None:
        pass

    def collect_all(self, node_names):
        return {name: [self._resource(name)] for name in node_names}

    def to_catalog(self, collected):
        resources = [item for items in collected.values() for item in items]
        return {"version": "auto-test", "resources": resources}

    @staticmethod
    def _resource(node_name: str) -> dict:
        video_id = hashlib.sha256(node_name.encode("utf-8")).hexdigest()[:11]
        return {
            "node": node_name,
            "title": f"{node_name} tutorial",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "provider": "youtube",
            "kind": "video",
            "language": "unknown",
            "access": "free",
            "level": "beginner",
        }


class AutoCollectPipelineTests(unittest.TestCase):
    def test_auto_collect_saves_and_merges_materials(self) -> None:
        config = json.loads((PROJECT_ROOT / "examples" / "profession_config.json").read_text(encoding="utf-8"))
        config["dictionaries"]["nodes"] = str(PROJECT_ROOT / "dictionaries" / "canonical_nodes.json")
        config["rules"] = {
            "phrases": str(PROJECT_ROOT / "rules" / "phrase_rules.json"),
            "splits": str(PROJECT_ROOT / "rules" / "split_rules.json"),
        }
        config["source"]["path"] = str(PROJECT_ROOT / "examples" / "sample_vacancies.json")
        config["learning"]["catalog"] = str(PROJECT_ROOT / "dictionaries" / "learning_resources.json")
        config["learning"]["auto_collect"] = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            with patch("graph_service.learning.aggregator.LearningAggregator", FakeAggregator):
                report = run_pipeline(
                    config_path=config_path,
                    runs_root=root / "runs",
                    run_id="auto-collect-run",
                )
            self.assertTrue(report["learning"]["auto_collect"])
            self.assertGreater(report["learning"]["collected_resources"], 0)
            collected = json.loads(
                (Path(report["run_directory"]) / "collected_learning_resources.json").read_text(encoding="utf-8")
            )
            self.assertEqual(collected["version"], "auto-test")
            self.assertTrue(collected["resources"])
            courses_path = next(
                (Path(report["run_directory"]) / "output").glob("profession_graph_node_courses_*/course_dictionary.json")
            )
            courses = json.loads(courses_path.read_text(encoding="utf-8"))
            self.assertTrue(courses["Python"])
            self.assertTrue(courses["Python"][0].startswith("https://docs.python.org"))
            self.assertTrue(any(url.startswith("https://www.youtube.com") for urls in courses.values() for url in urls))


if __name__ == "__main__":
    unittest.main()
