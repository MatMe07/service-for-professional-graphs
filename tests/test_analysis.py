from __future__ import annotations

import unittest

from graph_service.analysis import apply_boilerplate_exclusions, detect_repeated_boilerplate, find_probable_reposts
from graph_service.extraction import DictionaryMatcher, mine_unknown_phrases
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


class BoilerplateTests(unittest.TestCase):
    def test_repeated_employer_advertising_is_excluded_and_auditable(self) -> None:
        repeated = (
            "Наша компания предлагает сотрудникам корпоративное обучение Python, "
            "добровольное медицинское страхование и современный комфортный офис."
        )
        vacancies = [
            Vacancy("1", "ML Engineer", repeated, employer="Одна компания"),
            Vacancy("2", "Data Scientist", repeated, employer="Одна компания"),
        ]
        parsed_records = [(vacancy, parse_text(vacancy.description)) for vacancy in vacancies]
        reasons, matches = detect_repeated_boilerplate(parsed_records, min_vacancies=2, min_chars=60)
        self.assertEqual(len(matches), 1)
        marked = apply_boilerplate_exclusions(vacancies[0], parsed_records[0][1], reasons)
        self.assertEqual(marked.fragments[0].exclusion_reason, "repeated_employer_boilerplate")

        matcher = DictionaryMatcher([NodeDefinition("Python", ("Python",), ("Технологии",))], "test")
        self.assertEqual(matcher.match("1", marked, "middle"), [])
        audited = matcher.match("1", marked, "middle", include_excluded=True)
        self.assertEqual(audited[0].exclusion_reason, "repeated_employer_boilerplate")

    def test_repeated_requirements_without_advertising_markers_are_kept(self) -> None:
        repeated = "Необходимо уверенно использовать Python и SQL для построения моделей и проверки гипотез в продукте."
        vacancies = [
            Vacancy("1", "ML Engineer", repeated, employer="Одна компания"),
            Vacancy("2", "Data Scientist", repeated, employer="Одна компания"),
        ]
        reasons, matches = detect_repeated_boilerplate(
            [(vacancy, parse_text(vacancy.description)) for vacancy in vacancies],
            min_vacancies=2,
            min_chars=60,
        )
        self.assertEqual(reasons, {})
        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
