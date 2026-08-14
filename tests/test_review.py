from __future__ import annotations

import unittest

from graph_service.analysis import build_review_report, render_review_html
from graph_service.models import Vacancy
from graph_service.parsing import parse_text


class ReviewReportTests(unittest.TestCase):
    def test_html_escapes_values_from_vacancies(self) -> None:
        vacancy = Vacancy("1", "<script>alert(1)</script>", "Python", employer="A & B")
        report = build_review_report(
            [vacancy],
            {"1": "middle"},
            {"1": {"grade": "middle", "confidence": 1.0, "conflict": False, "signals": {}}},
            {"1": parse_text(vacancy.description)},
            [],
            [],
            [],
            {"items": []},
            [],
        )
        rendered = render_review_html(report)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn("A &amp; B", rendered)


if __name__ == "__main__":
    unittest.main()
