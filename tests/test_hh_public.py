from __future__ import annotations

import json
import unittest
from email.message import Message
from unittest.mock import patch

from graph_service.collectors.hh_public import (
    HHPublicPageCollector,
    HHPublicPageError,
    normalize_public_vacancy_url,
)


HTML = f"""<!doctype html><html><body>
<h1 data-qa="vacancy-title">Python-разработчик</h1>
<span data-qa="vacancy-experience">1–3 года</span>
<div data-qa="vacancy-salary">от 120 000 ₽ за месяц</div>
<a data-qa="vacancy-company-name"><span>Тестовая компания</span></a>
<script type="application/ld+json">{json.dumps({
    "@context": "https://schema.org/",
    "@type": "JobPosting",
    "identifier": {"@type": "PropertyValue", "value": 123456},
    "title": "Python-разработчик",
    "description": "<p><strong>Требования</strong></p><ul><li>Python и SQL</li></ul>",
    "datePosted": "2026-08-15T10:00:00+03:00",
    "validThrough": "2026-09-15T10:00:00+03:00",
    "hiringOrganization": {"@type": "Organization", "name": "Тестовая компания"},
    "jobLocation": {"address": {"addressLocality": "Москва"}},
}, ensure_ascii=False)}</script>
</body></html>"""


class _Response:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body

    def geturl(self) -> str:
        return "https://hh.ru/vacancy/123456"


class HHPublicPageTests(unittest.TestCase):
    def test_only_direct_hh_vacancy_urls_are_accepted(self) -> None:
        self.assertEqual(
            normalize_public_vacancy_url("https://www.hh.ru/vacancy/123456/?from=search"),
            "https://hh.ru/vacancy/123456",
        )
        with self.assertRaises(HHPublicPageError):
            normalize_public_vacancy_url("https://hh.ru/search/vacancy?text=Python")
        with self.assertRaises(HHPublicPageError):
            normalize_public_vacancy_url("https://example.com/vacancy/123456")

    def test_public_page_is_normalized_without_token(self) -> None:
        collector = HHPublicPageCollector(
            {
                "urls": ["https://hh.ru/vacancy/123456"],
                "contact_email": "test@example.org",
                "request_interval_seconds": 0,
            }
        )
        with patch("urllib.request.urlopen", return_value=_Response(HTML)):
            result = collector.collect()
        self.assertEqual(len(result.vacancies), 1)
        vacancy = result.vacancies[0]
        self.assertEqual(vacancy.vacancy_id, "123456")
        self.assertEqual(vacancy.name, "Python-разработчик")
        self.assertEqual(vacancy.experience_id, "between1And3")
        self.assertEqual(vacancy.salary_from, 120000)
        self.assertEqual(vacancy.source, "hh_public")
        self.assertIn("html", vacancy.raw["public_page"])
        self.assertFalse(result.search_responses[0]["response"]["automatic_search"])


if __name__ == "__main__":
    unittest.main()
