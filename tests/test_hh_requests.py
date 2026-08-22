from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from graph_service.collectors.hh_requests import HHDescriptionExtractor, HHRequestsCollector, parse_salary

DESCRIPTION_HTML = (
    '<div data-qa="vacancy-description">'
    "<h2>Требования:</h2><ul>"
    "<li>Опыт работы с Python от 2 лет</li>"
    "<li>Знание SQL</li>"
    "</ul>"
    "<h2>Будет плюсом:</h2><ul>"
    "<li>Docker</li>"
    "<li>Kubernetes</li>"
    "</ul>"
    "</div>"
)

SEARCH_HTML = (
    '<html><body><div class="vacancy-serp__vacancy">'
    '<a data-qa="serp-item__title" href="/vacancy/100">Python dev</a>'
    "</div></body></html>"
)

SEARCH_HTML_WITH_ADS = (
    '<html><body><div class="vacancy-serp__vacancy">'
    '<a data-qa="serp-item__title" href="https://adsrv.hh.ru/link/?id=ad-1">Реклама</a>'
    '<a data-qa="serp-item__title" href="https://sovetnik.hh.ru/vacancy/999?from=sova">Реклама 2</a>'
    '<a data-qa="serp-item__title" href="/vacancy/100">Python dev</a>'
    "</div></body></html>"
)

VACANCY_HTML = (
    "<html><body>"
    '<h1 data-qa="vacancy-title">Python Developer</h1>'
    '<a data-qa="vacancy-company-name">TechCorp</a>'
    '<span data-qa="vacancy-salary">от 100 000 до 150 000 ₽</span>'
    '<div data-qa="vacancy-address-with-map">Москва</div>'
    '<span data-qa="vacancy-experience">1–3 года</span>'
    '<div data-qa="vacancy-description">'
    "<h2>Требования:</h2><ul><li>Python</li><li>SQL</li></ul>"
    "<h2>Будет плюсом:</h2><ul><li>Docker</li></ul>"
    "</div>"
    '<ul><li data-qa="skills-element">Linux</li><li data-qa="skills-element">Git</li></ul>'
    '<div class="bloko-gap bloko-gap_bottom"><span>Вакансия опубликована 12 августа 2026</span></div>'
    "</body></html>"
)

_POSTING = {
    "@context": "https://schema.org/",
    "@type": "JobPosting",
    "title": "Python Backend",
    "datePosted": "2026-08-15T10:00:00+03:00",
    "identifier": {"@type": "PropertyValue", "value": "777"},
    "hiringOrganization": {"@type": "Organization", "name": "DataLab"},
    "jobLocation": {
        "@type": "Place",
        "address": {"@type": "PostalAddress", "addressLocality": "Санкт-Петербург"},
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "RUR",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 120000,
            "maxValue": 160000,
        },
    },
    "description": (
        "<p>Чем предстоит заниматься:</p><ul><li>Писать сервисы</li></ul>"
        "<h3><strong>Требования</strong></h3>"
        "<p>Мы ждем от кандидата:</p>"
        "<ul><li>Python 3.12</li><li>SQL</li><li>Docker</li><li>Kubernetes</li>"
        "<li>Linux</li><li>CI/CD</li><li>Опыт от 2 лет</li></ul>"
        "<p><strong>Будет плюсом:</strong></p><ul><li>ClickHouse</li></ul>"
    ),
}

VACANCY_JSONLD_HTML = (
    "<html><body>"
    '<script type="application/ld+json">' + json.dumps(_POSTING, ensure_ascii=False) + "</script>"
    '<div data-qa="vacancy-description">fallback</div>'
    "</body></html>"
)


class _FakeResponse:
    def __init__(self, html: str, status_code: int = 200, url: str = "") -> None:
        self.text = html
        self.status_code = status_code
        self.url = url


class HHDescriptionExtractorTests(unittest.TestCase):
    def test_extracts_requirements_and_plus_from_html(self) -> None:
        sections = HHDescriptionExtractor().extract(DESCRIPTION_HTML)
        self.assertIn("Опыт работы с Python от 2 лет", sections["requirements"])
        self.assertIn("Знание SQL", sections["requirements"])
        self.assertIn("Docker", sections["plus"])
        self.assertIn("Kubernetes", sections["plus"])
        self.assertNotIn("Будет плюсом:", sections["requirements"])
        self.assertNotIn("Требования:", sections["plus"])

    def test_inline_heading_with_content_on_same_line(self) -> None:
        html = "<p><strong>Требования:</strong> Python и SQL.</p><p>Опыт работы.</p>"
        sections = HHDescriptionExtractor().extract(html)
        self.assertIn("Python и SQL.", sections["requirements"])

    def test_nested_heading_does_not_break_collection(self) -> None:
        html = "<p><strong>Требования:</strong></p><ul><li>Linux</li><li>Git</li></ul>"
        sections = HHDescriptionExtractor().extract(html)
        self.assertIn("Linux", sections["requirements"])
        self.assertIn("Git", sections["requirements"])

    def test_fallback_to_lists_when_no_heading(self) -> None:
        sections = HHDescriptionExtractor().extract("<ul><li>Linux</li><li>Git</li></ul>")
        self.assertEqual(sections["requirements"], "Linux\nGit")
        self.assertEqual(sections["plus"], "")

    def test_heading_zhdem_ot_tebya(self) -> None:
        html = (
            "<p>Твои задачи:</p><ul><li>работа с библиотеками Python</li></ul>"
            "<p>Ждем от тебя:</p><ul><li>Опыт работы (Python)</li><li>Знание SQL</li></ul>"
            "<p>Мы предлагаем:</p><ul><li>ДМС</li></ul>"
        )
        sections = HHDescriptionExtractor().extract(html)
        self.assertEqual(sections["requirements"], "Опыт работы (Python)\nЗнание SQL")

    def test_heading_what_we_expect_from_candidate(self) -> None:
        html = (
            "<p>Чем предстоит заниматься:</p><ul><li>сервисы</li></ul>"
            "<p>Что ожидаем от кандидата:</p><ul><li>Python 5+</li><li>FastAPI</li></ul>"
            "<p>Что вам может быть интересно о Sibedge:</p><ul><li>ДМС</li></ul>"
        )
        sections = HHDescriptionExtractor().extract(html)
        self.assertEqual(sections["requirements"], "Python 5+\nFastAPI")

    def test_heading_we_expect_that_you(self) -> None:
        html = "<p><strong>Мы ожидаем, что вы:</strong></p><ul><li>Python</li><li>SQL</li></ul>"
        sections = HHDescriptionExtractor().extract(html)
        self.assertEqual(sections["requirements"], "Python\nSQL")

    def test_heading_requirements_to_candidate(self) -> None:
        html = "<p><strong>Требования к кандидату</strong></p><ul><li>Python</li><li>Git</li></ul>"
        sections = HHDescriptionExtractor().extract(html)
        self.assertEqual(sections["requirements"], "Python\nGit")

    def test_plus_with_em_strong_heading_and_stop(self) -> None:
        html = (
            "<p>Что мы от Вас ждём:</p><ul><li>опыт Python</li></ul>"
            "<p><em><strong>Будем плюсом:</strong></em></p><p>знание TCP/IP, Docker</p>"
            "<p>Что мы готовы предложить:</p><ul><li>ДМС</li></ul>"
        )
        sections = HHDescriptionExtractor().extract(html)
        self.assertEqual(sections["requirements"], "опыт Python")
        self.assertEqual(sections["plus"], "знание TCP/IP, Docker")

    def test_empty_input(self) -> None:
        self.assertEqual(HHDescriptionExtractor().extract(None), {"requirements": "", "plus": ""})

    def test_real_structure_with_subheading_noise(self) -> None:
        html = (
            "<p>Чем предстоит заниматься:</p><ul><li>Сервисы</li></ul>"
            "<h3><strong>Требования</strong></h3>"
            "<p>Мы ждем от кандидата:</p>"
            "<ul><li>Python 3.12</li><li>SQL</li><li>Docker</li><li>Kubernetes</li>"
            "<li>Linux</li><li>CI/CD</li><li>Опыт от 2 лет</li></ul>"
            "<p><strong>Будет плюсом:</strong></p><ul><li>ClickHouse</li></ul>"
        )
        sections = HHDescriptionExtractor().extract(html)
        req = sections["requirements"].split("\n")
        self.assertEqual(len(req), 7)
        self.assertNotIn("Мы ждем от кандидата:", req)
        self.assertIn("Python 3.12", req)
        self.assertIn("Опыт от 2 лет", req)
        self.assertEqual(sections["plus"], "ClickHouse")


class HHRequestsSalaryTests(unittest.TestCase):
    def test_salary_range(self) -> None:
        self.assertEqual(
            parse_salary("от 100\u00a0000 до 150 000 ₽"),
            {"from": 100000.0, "to": 150000.0, "currency": "RUR", "gross": None},
        )

    def test_salary_to_with_net_marker(self) -> None:
        parsed = parse_salary("до 200 000 руб. на руки")
        self.assertEqual(parsed["to"], 200000.0)
        self.assertIs(parsed["gross"], False)

    def test_salary_without_numbers(self) -> None:
        self.assertIsNone(parse_salary(""))
        self.assertIsNone(parse_salary("не указана"))

    def test_salary_single_number_exact(self) -> None:
        parsed = parse_salary("78 000 ₽ за месяц на руки")
        self.assertEqual(parsed["from"], 78000.0)
        self.assertEqual(parsed["to"], 78000.0)
        self.assertEqual(parsed["currency"], "RUR")
        self.assertIs(parsed["gross"], False)


class HHRequestsCollectorTests(unittest.TestCase):
    def _build_collector(self, **overrides) -> HHRequestsCollector:
        config: dict[str, object] = {
            "queries": ["Python разработчик"],
            "areas": ["1"],
            "max_pages": 1,
            "per_page": 20,
            "period_days": 0,
            "relevance_terms": [],
            "retries": 0,
            "request_interval_seconds": 0.1,
            "detail_interval_seconds": 0.0,
        }
        config.update(overrides)
        return HHRequestsCollector(config)

    def test_collect_assembles_vacancy_fields(self) -> None:
        collector = self._build_collector()

        def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
            if "search/vacancy" in url:
                return _FakeResponse(SEARCH_HTML)
            return _FakeResponse(VACANCY_HTML)

        with patch.object(collector, "_get_page", side_effect=fake_get):
            result = collector.collect()

        self.assertEqual(len(result.vacancies), 1)
        vacancy = result.vacancies[0]
        self.assertEqual(vacancy.vacancy_id, "100")
        self.assertEqual(vacancy.name, "Python Developer")
        self.assertEqual(vacancy.employer, "TechCorp")
        self.assertEqual(vacancy.area, "Москва")
        self.assertEqual(vacancy.alternate_url, "https://hh.ru/vacancy/100")
        self.assertEqual(vacancy.experience_id, "between1And3")
        self.assertEqual(vacancy.salary_from, 100000.0)
        self.assertEqual(vacancy.salary_to, 150000.0)
        self.assertEqual(vacancy.salary_currency, "RUR")
        self.assertEqual(vacancy.published_at, "2026-08-12")
        self.assertEqual(vacancy.query_ids, ("hh_requests:Python разработчик:area:1",))
        self.assertIn("Требования:", vacancy.description)
        self.assertIn("Python", vacancy.description)
        self.assertIn("SQL", vacancy.description)
        self.assertIn("Будет плюсом:\nDocker", vacancy.description)
        self.assertIn("Ключевые навыки:\nLinux\nGit", vacancy.description)

    def test_detail_404_is_skipped(self) -> None:
        collector = self._build_collector()

        def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
            if "search/vacancy" in url:
                return _FakeResponse(SEARCH_HTML)
            return _FakeResponse("", status_code=404)

        with patch.object(collector, "_get_page", side_effect=fake_get):
            result = collector.collect()
        self.assertEqual(result.vacancies, [])

    def test_pagination_stops_when_page_has_fewer_links_than_per_page(self) -> None:
        collector = self._build_collector(max_pages=3, per_page=10)
        calls = {"count": 0}

        def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
            calls["count"] += 1
            if "search/vacancy" in url:
                return _FakeResponse(SEARCH_HTML)
            return _FakeResponse(VACANCY_HTML)

        with patch.object(collector, "_get_page", side_effect=fake_get):
            result = collector.collect()

        search_calls = [calls["count"] - 1]
        self.assertEqual(len(result.search_responses), 1)
        self.assertLess(search_calls[0], 3)

    def test_json_ld_populates_fields(self) -> None:
        collector = self._build_collector()

        def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
            if "search/vacancy" in url:
                return _FakeResponse(SEARCH_HTML)
            return _FakeResponse(VACANCY_JSONLD_HTML)

        with patch.object(collector, "_get_page", side_effect=fake_get):
            result = collector.collect()

        self.assertEqual(len(result.vacancies), 1)
        vacancy = result.vacancies[0]
        self.assertEqual(vacancy.vacancy_id, "100")
        self.assertEqual(vacancy.name, "Python Backend")
        self.assertEqual(vacancy.employer, "DataLab")
        self.assertEqual(vacancy.area, "Санкт-Петербург")
        self.assertEqual(vacancy.published_at, "2026-08-15T10:00:00+03:00")
        self.assertEqual(vacancy.salary_from, 120000.0)
        self.assertEqual(vacancy.salary_to, 160000.0)
        self.assertEqual(vacancy.salary_currency, "RUR")
        self.assertIn("Требования", vacancy.description)
        self.assertIn("Python 3.12", vacancy.description)
        self.assertIn("ClickHouse", vacancy.description)

    def test_adsrv_links_are_ignored(self) -> None:
        collector = self._build_collector()

        def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
            if "search/vacancy" in url:
                return _FakeResponse(SEARCH_HTML_WITH_ADS)
            return _FakeResponse(VACANCY_HTML)

        with patch.object(collector, "_get_page", side_effect=fake_get):
            result = collector.collect()

        self.assertEqual(len(result.vacancies), 1)
        self.assertEqual(result.vacancies[0].vacancy_id, "100")

    def test_final_redirect_url_is_used(self) -> None:
        collector = self._build_collector()

        def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
            if "search/vacancy" in url:
                return _FakeResponse(SEARCH_HTML)
            return _FakeResponse(VACANCY_HTML, url="https://hh.ru/vacancy/333?query=python-developer")

        with patch.object(collector, "_get_page", side_effect=fake_get):
            result = collector.collect()

        self.assertEqual(len(result.vacancies), 1)
        vacancy = result.vacancies[0]
        self.assertEqual(vacancy.vacancy_id, "333")
        self.assertEqual(vacancy.alternate_url, "https://hh.ru/vacancy/333")
        self.assertEqual(vacancy.published_at, "2026-08-12")

    def test_bullet_markers_are_stripped(self) -> None:
        collector = self._build_collector()
        page = VACANCY_HTML.replace(
            "<h2>Требования:</h2><ul><li>Python</li><li>SQL</li></ul>",
            "<h2>Требования:</h2><ul><li>• Python</li><li>• SQL</li></ul>",
        )

        def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
            if "search/vacancy" in url:
                return _FakeResponse(SEARCH_HTML)
            return _FakeResponse(page)

        with patch.object(collector, "_get_page", side_effect=fake_get):
            result = collector.collect()

        vacancy = result.vacancies[0]
        self.assertNotIn("•", vacancy.description)
        self.assertIn("Python", vacancy.description)

    def test_key_skills_enriched_from_canonical_nodes(self) -> None:
        import tempfile

        canonical = {
            "version": "test",
            "nodes": [
                {"name": "Django", "aliases": ["django", "django framework"], "path": ["Framework"], "kind": "skill"},
                {"name": "PostgreSQL", "aliases": ["postgresql"], "path": ["Data"], "kind": "skill"},
            ],
        }
        page = VACANCY_HTML.replace(
            "<h2>Требования:</h2><ul><li>Python</li><li>SQL</li></ul>",
            "<h2>Требования:</h2><ul><li>Опыт работы с Django</li><li>SQL</li></ul>",
        ).replace(
            '<li data-qa="skills-element">Linux</li><li data-qa="skills-element">Git</li>',
            '<li data-qa="skills-element">Django</li><li data-qa="skills-element">Git</li>',
        )
        with tempfile.TemporaryDirectory() as tmp:
            nodes_path = f"{tmp}/canonical_nodes.json"
            with open(nodes_path, "w", encoding="utf-8") as fh:
                json.dump(canonical, fh)
            collector = self._build_collector(nodes_path=nodes_path)

            def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
                if "search/vacancy" in url:
                    return _FakeResponse(SEARCH_HTML)
                return _FakeResponse(page)

            with patch.object(collector, "_get_page", side_effect=fake_get):
                result = collector.collect()

        vacancy = result.vacancies[0]
        self.assertEqual(vacancy.description.split("Ключевые навыки:\n", 1)[1], "Django\nGit")
        self.assertNotIn("PostgreSQL", vacancy.description)

    def test_captcha_detection(self) -> None:
        collector = self._build_collector()
        self.assertTrue(collector._is_captcha("<html>captcha challenge</html>"))
        self.assertTrue(collector._is_captcha("<html>проверка, что вы не робот</html>"))
        self.assertFalse(collector._is_captcha(SEARCH_HTML))
        self.assertFalse(collector._is_captcha(VACANCY_HTML))

    def test_search_request_contains_period_and_publication_order(self) -> None:
        collector = self._build_collector(period_days=30)
        captured: dict[str, object] = {}

        def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
            captured["params"] = params
            return _FakeResponse(SEARCH_HTML)

        with patch.object(collector, "_get_page", side_effect=fake_get):
            links = collector._get_vacancy_links("Python разработчик", "1", 0)

        self.assertEqual(links, ["https://hh.ru/vacancy/100"])
        self.assertEqual(captured["params"]["period"], 30)
        self.assertEqual(captured["params"]["order_by"], "publication_time")

    def test_direct_link_fallback_does_not_depend_on_data_qa(self) -> None:
        collector = self._build_collector()
        html = '<html><body><a class="new-layout" href="/vacancy/321?from=search">Python</a></body></html>'
        with patch.object(collector, "_get_page", return_value=_FakeResponse(html)):
            links = collector._get_vacancy_links("Python разработчик", "1", 0)
        self.assertEqual(links, ["https://hh.ru/vacancy/321"])

    def test_max_vacancies_is_global_across_queries(self) -> None:
        collector = self._build_collector(
            queries=["Python разработчик", "Python Developer"],
            max_vacancies=1,
            per_page=2,
        )
        search_html = (
            '<html><body><div class="vacancy-serp__vacancy">'
            '<a data-qa="serp-item__title" href="/vacancy/100">Python</a>'
            '<a data-qa="serp-item__title" href="/vacancy/101">Python</a>'
            '</div></body></html>'
        )
        search_calls = 0

        def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
            nonlocal search_calls
            if "search/vacancy" in url:
                search_calls += 1
                return _FakeResponse(search_html)
            return _FakeResponse(VACANCY_HTML)

        with patch.object(collector, "_get_page", side_effect=fake_get):
            result = collector.collect()

        self.assertEqual(len(result.vacancies), 1)
        self.assertEqual(search_calls, 1)

    def test_irrelevant_title_is_rejected(self) -> None:
        collector = self._build_collector(
            relevance_terms=["Python разработчик", "Python Developer"]
        )
        irrelevant_page = VACANCY_HTML.replace(
            "Python Developer", "Junior специалист BI"
        )

        def fake_get(url: str, params: object = None, retries: object = None) -> _FakeResponse:
            if "search/vacancy" in url:
                return _FakeResponse(SEARCH_HTML)
            return _FakeResponse(irrelevant_page)

        with patch.object(collector, "_get_page", side_effect=fake_get):
            result = collector.collect()

        self.assertEqual(result.vacancies, [])
        self.assertEqual(result.search_responses[0]["rejected"], 1)

    def test_reordered_relevance_terms_are_accepted(self) -> None:
        collector = self._build_collector(
            relevance_terms=["Python Developer"]
        )
        self.assertTrue(collector._is_relevant_title("Senior Developer Python"))
        self.assertFalse(collector._is_relevant_title("Data Analyst (Python)"))

    def test_period_is_enforced_locally(self) -> None:
        collector = self._build_collector(period_days=30)
        now = datetime(2026, 8, 22, tzinfo=timezone.utc)
        self.assertTrue(
            collector._is_within_period(
                (now - timedelta(days=5)).isoformat(), now=now
            )
        )
        self.assertFalse(
            collector._is_within_period(
                (now - timedelta(days=31)).isoformat(), now=now
            )
        )

    def test_user_agent_is_stable_for_session(self) -> None:
        collector = self._build_collector(user_agent="ProfessionalGraphs-Test/1.0")
        self.assertEqual(collector.get_headers(), collector.get_headers())
        self.assertEqual(
            collector.get_headers()["User-Agent"], "ProfessionalGraphs-Test/1.0"
        )


if __name__ == "__main__":
    unittest.main()
