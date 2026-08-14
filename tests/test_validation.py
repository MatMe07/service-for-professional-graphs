from __future__ import annotations

import unittest

from graph_service.validation import validate_graph


class ValidationTests(unittest.TestCase):
    def test_valid_strict_graph(self) -> None:
        graph = {
            "Профессия": {
                "Технологии": {
                    "Python": {"count": 90},
                    "SQL": {"count": 70},
                    "Git": {"count": 60},
                },
                "Задачи": {
                    "Классификация": {"count": 80},
                    "Регрессия": {"count": 70},
                    "Прогнозирование": {"count": 50},
                },
                "Методы": {
                    "Линейные модели": {"count": 70},
                    "Деревья решений": {"count": 60},
                    "Градиентный бустинг": {"count": 90},
                },
            }
        }
        self.assertEqual(validate_graph(graph, min_children=3), [])

    def test_invalid_leaf_is_error(self) -> None:
        graph = {"Профессия": {"Python": {"count": 0, "url": "bad"}}}
        issues = validate_graph(graph, min_children=1)
        self.assertTrue(any(issue.severity == "error" for issue in issues))


if __name__ == "__main__":
    unittest.main()

