from __future__ import annotations

import unittest

from graph_service.graph.grades import decide_grade
from graph_service.models import Vacancy


class GradeTests(unittest.TestCase):
    def test_clear_senior(self) -> None:
        vacancy = Vacancy("1", "Senior ML Engineer", "Опыт от 5 лет, архитектура и наставничество")
        result = decide_grade(vacancy)
        self.assertEqual(result.grade, "senior")
        self.assertFalse(result.conflict)

    def test_title_and_text_conflict_is_visible(self) -> None:
        vacancy = Vacancy("2", "Junior ML Engineer", "Опыт от 5 лет, архитектура и наставничество")
        result = decide_grade(vacancy)
        self.assertTrue(result.conflict)
        self.assertIn("title:junior", result.signals["junior"])
        self.assertIn("experience_years", result.signals["senior"])
        self.assertTrue(any("title_junior_vs_experience_senior" in reason for reason in result.conflict_reasons))

    def test_intern_maps_to_junior_but_keeps_subgrade(self) -> None:
        result = decide_grade(Vacancy("3", "ML Intern", "Можно без опыта"))
        self.assertEqual(result.grade, "junior")
        self.assertEqual(result.subgrade, "intern")
        self.assertFalse(result.conflict)

    def test_lead_maps_to_senior_but_keeps_subgrade(self) -> None:
        result = decide_grade(Vacancy("4", "Lead ML Engineer", "Архитектурные решения и наставничество"))
        self.assertEqual(result.grade, "senior")
        self.assertEqual(result.subgrade, "lead")
        self.assertFalse(result.conflict)

    def test_weak_adjacent_signal_does_not_create_conflict(self) -> None:
        result = decide_grade(Vacancy("5", "Middle ML Engineer", "Работа под руководством архитектора"))
        self.assertEqual(result.grade, "middle")
        self.assertFalse(result.conflict)

    def test_unknown_vacancy_uses_visible_default(self) -> None:
        result = decide_grade(Vacancy("6", "ML Engineer", "Работа с моделями"))
        self.assertEqual(result.grade, "middle")
        self.assertEqual(result.resolution, "default_grade_no_signals")

    def test_structured_hh_experience_is_used(self) -> None:
        vacancy = Vacancy("7", "ML Engineer", "Работа с моделями", experience_id="between3And6")
        result = decide_grade(vacancy, {"mode": "experience", "junior_max_years": 1, "middle_max_years": 6})
        self.assertEqual(result.grade, "middle")
        self.assertIn("experience_years:6", result.signals["middle"])

    def test_salary_thresholds_are_configurable(self) -> None:
        vacancy = Vacancy(
            "8",
            "ML Engineer",
            "Работа с моделями",
            salary_from=280000,
            salary_to=320000,
            salary_currency="RUR",
        )
        result = decide_grade(
            vacancy,
            {
                "mode": "salary",
                "salary_currency": "RUR",
                "junior_max_salary": 120000,
                "middle_max_salary": 250000,
            },
        )
        self.assertEqual(result.grade, "senior")
        self.assertIn("salary:300000:RUR", result.signals["senior"])


if __name__ == "__main__":
    unittest.main()
