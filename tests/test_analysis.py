from __future__ import annotations

import unittest

from graph_service.analysis import find_probable_reposts
from graph_service.extraction import mine_unknown_phrases
from graph_service.models import NodeDefinition, Vacancy
from graph_service.parsing import parse_text


class DuplicateTests(unittest.TestCase):
    def test_probable_repost_is_reported_not_removed(self) -> None:
        left = Vacancy("1", "ML Engineer", "Python SQL построение моделей", employer="Компания")
        right = Vacancy("2", "ML Engineer", "Python SQL построение моделей", employer="Компания")
        result = find_probable_reposts([left, right])
        self.assertEqual(result[0]["decision"], "probable_repost")
        self.assertIn("remain included", result[0]["action"])


class UnknownTermsTests(unittest.TestCase):
    def test_known_aliases_are_removed_before_mining(self) -> None:
        nodes = [NodeDefinition("Python", ("Python",), ("Технологии",), "technology")]
        first = Vacancy("1", "ML", "Python и Apache Airflow orchestration")
        second = Vacancy("2", "ML", "Python и Apache Airflow orchestration")
        report = mine_unknown_phrases(
            [(first, parse_text(first.description)), (second, parse_text(second.description))],
            nodes,
            min_vacancies=2,
        )
        phrases = {item["phrase"] for item in report["items"]}
        self.assertIn("apache airflow", phrases)
        self.assertNotIn("python apache", phrases)


if __name__ == "__main__":
    unittest.main()

