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


if __name__ == "__main__":
    unittest.main()
