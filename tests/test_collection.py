from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from graph_service.collectors.file import FileCollector
from graph_service.collectors.hh import HHCollector, HHCollectorError


class FileCollectionTests(unittest.TestCase):
    def test_duplicate_source_id_is_merged_with_query_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vacancies.json"
            path.write_text(
                json.dumps(
                    [
                        {"id": "1", "name": "ML", "description": "Python", "query_ids": ["q1"]},
                        {"id": "1", "name": "ML", "description": "Python", "query_ids": ["q2"]},
                    ]
                ),
                encoding="utf-8",
            )
            result = FileCollector(path).collect()
            self.assertEqual(len(result.vacancies), 1)
            self.assertEqual(result.vacancies[0].query_ids, ("q1", "q2"))
            self.assertEqual(result.duplicate_sightings[0]["occurrences"], 2)

    def test_archived_status_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vacancies.json"
            path.write_text(
                json.dumps([{"id": "1", "name": "ML", "description": "Python", "archived": True}]),
                encoding="utf-8",
            )
            result = FileCollector(path).collect()
            self.assertEqual(result.vacancies[0].status, "archived")


class FakeHHCollector(HHCollector):
    def _get_json(self, path: str, params: dict[str, object]) -> dict[str, object]:
        if path == "/vacancies":
            return {"items": [{"id": "100"}], "pages": 1}
        return {
            "id": "100",
            "name": "Middle ML Engineer",
            "description": "Python",
            "employer": {"name": "Test"},
        }


class HHCollectionTests(unittest.TestCase):
    def test_search_response_and_query_id_are_preserved(self) -> None:
        collector = FakeHHCollector(
            {
                "queries": ["ML Engineer"],
                "areas": ["1"],
                "max_pages": 1,
                "per_page": 20,
            }
        )
        result = collector.collect()
        self.assertEqual(len(result.search_responses), 1)
        self.assertEqual(result.vacancies[0].query_ids, ("hh:q001:area:1",))

    def test_placeholder_contact_is_rejected_for_live_request(self) -> None:
        with patch.dict("os.environ", {"HH_USER_AGENT": ""}):
            collector = HHCollector({"queries": ["ML Engineer"]})
        self.assertFalse(collector.live_contact_ready)
        with self.assertRaises(HHCollectorError):
            collector.validate_live_contact()

    def test_user_agent_can_be_supplied_through_environment(self) -> None:
        with patch.dict("os.environ", {"HH_USER_AGENT": "ProfessionalGraphService/0.6 (team@domain.ru)"}):
            collector = HHCollector({"queries": ["ML Engineer"]})
        self.assertTrue(collector.live_contact_ready)
        collector.validate_live_contact()


if __name__ == "__main__":
    unittest.main()
