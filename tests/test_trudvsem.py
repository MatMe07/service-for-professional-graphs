from __future__ import annotations

import unittest

from graph_service.collectors.trudvsem import TrudvsemCollector


class FakeTrudvsemCollector(TrudvsemCollector):
    def _get_json(self, path: str, params: dict[str, object]) -> dict[str, object]:
        return {
            "status": "200",
            "meta": {"total": 1, "limit": params["limit"]},
            "results": {
                "vacancies": [
                    {
                        "vacancy": {
                            "id": "public-1",
                            "job-name": "Python-разработчик",
                            "company": {"name": "Компания"},
                            "region": {"name": "Москва"},
                            "creation-date": "2026-08-01",
                            "vac_url": "https://trudvsem.ru/vacancy/card/company/public-1",
                            "requirements": "Python и FastAPI",
                            "duty": "Разработка API",
                            "requirement": {"experience": 3},
                            "salary_min": 150000,
                            "salary_max": 220000,
                            "skills": ["Python"],
                        }
                    }
                ]
            },
        }


class TrudvsemCollectionTests(unittest.TestCase):
    def test_automatic_search_normalizes_public_vacancy(self) -> None:
        collector = FakeTrudvsemCollector(
            {"queries": ["Python разработчик"], "per_page": 100, "max_pages": 2, "request_interval_seconds": 0}
        )
        result = collector.collect()
        self.assertEqual(len(result.search_responses), 1)
        self.assertEqual(len(result.vacancies), 1)
        vacancy = result.vacancies[0]
        self.assertEqual(vacancy.source, "trudvsem")
        self.assertEqual(vacancy.experience_id, "between3And6")
        self.assertEqual(vacancy.salary_from, 150000)
        self.assertIn("Требования", vacancy.description)
        self.assertEqual(vacancy.query_ids, ("trudvsem:q001:region:all",))


if __name__ == "__main__":
    unittest.main()
