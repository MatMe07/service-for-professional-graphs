from __future__ import annotations

import unittest

from graph_service.graph.scoring import calculate_counts
from graph_service.models import Evidence, Vacancy


class ScoringTests(unittest.TestCase):
    def test_negated_only_evidence_does_not_create_count(self) -> None:
        vacancies = [Vacancy("1", "Junior", "Docker не требуется")]
        grades = {"1": "junior"}
        evidence = [Evidence("1", "Docker", "junior", "Docker", 0, 6, "negated", "test")]
        counts, components = calculate_counts(vacancies, grades, evidence, {"negated": 0.0})
        self.assertNotIn("Docker", counts["junior"])
        self.assertEqual(components, [])

    def test_one_employer_is_capped(self) -> None:
        vacancies = [Vacancy(str(index), "Junior", "Docker", employer="Одна компания") for index in range(4)]
        grades = {vacancy.vacancy_id: "junior" for vacancy in vacancies}
        evidence = [
            Evidence(vacancy.vacancy_id, "Docker", "junior", "Docker", 0, 6, "required", "test")
            for vacancy in vacancies
        ]
        counts, components = calculate_counts(
            vacancies,
            grades,
            evidence,
            {"required": 1.0, "max_employer_share": 0.4},
        )
        self.assertEqual(counts["junior"]["Docker"], 40)
        self.assertEqual(components[0]["employers"], 1)

    def test_company_section_does_not_create_count(self) -> None:
        vacancies = [Vacancy("1", "Middle", "Наша компания использует Python")]
        grades = {"1": "middle"}
        evidence = [
            Evidence("1", "Python", "middle", "Python", 22, 28, "unknown", "test", section="company")
        ]
        counts, components = calculate_counts(vacancies, grades, evidence, {})
        self.assertNotIn("Python", counts["middle"])
        self.assertEqual(components, [])

    def test_section_weight_changes_count(self) -> None:
        vacancies = [
            Vacancy("1", "Middle", "Python", employer="A"),
            Vacancy("2", "Middle", "Python", employer="B"),
        ]
        grades = {"1": "middle", "2": "middle"}
        evidence = [
            Evidence("1", "Python", "middle", "Python", 0, 6, "required", "test", section="requirements"),
            Evidence("2", "Python", "middle", "Python", 0, 6, "required", "test", section="conditions"),
        ]
        counts, components = calculate_counts(
            vacancies,
            grades,
            evidence,
            {
                "required": 1.0,
                "max_employer_share": 1.0,
                "section_weights": {"requirements": 1.0, "conditions": 0.2},
            },
        )
        self.assertEqual(counts["middle"]["Python"], 60)
        self.assertEqual(components[0]["evidence_mentions"], 2)


if __name__ == "__main__":
    unittest.main()
