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


if __name__ == "__main__":
    unittest.main()

