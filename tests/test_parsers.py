from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from graph_service.learning.parsers import HabrProvider, StepikProvider, YouTubeProvider


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data=None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no payload")
        return self._json


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append({"url": url, "params": params})
        return self.response


def stepik_course(**overrides) -> dict:
    base = {
        "id": 101,
        "title": "Курс Python",
        "language": "ru",
        "difficulty": "easy",
        "workload": "10 часов",
        "with_certificate": True,
        "is_public": True,
        "is_paid": False,
    }
    return {**base, **overrides}


class StepikProviderTests(unittest.TestCase):
    def test_maps_free_courses_and_skips_paid(self) -> None:
        payload = {
            "meta": {"has_next": False},
            "courses": [
                stepik_course(),
                stepik_course(id=102, title="Платный курс", is_paid=True),
                stepik_course(id=103, title="English Course", language="en", difficulty="hard", workload=""),
            ],
        }
        provider = StepikProvider(session=FakeSession(FakeResponse(json_data=payload)), interval=0)
        results = provider.search("Python", 4)
        self.assertEqual(
            [item["url"] for item in results],
            ["https://stepik.org/course/101/", "https://stepik.org/course/103/"],
        )
        first = results[0]
        self.assertEqual(first["provider"], "stepik")
        self.assertEqual(first["kind"], "course")
        self.assertEqual(first["language"], "ru")
        self.assertEqual(first["level"], "beginner")
        self.assertEqual(first["duration"], "10 часов")
        self.assertTrue(first["certificate"])
        second = results[1]
        self.assertEqual(second["level"], "advanced")
        self.assertIsNone(second["duration"])

    def test_requests_search_with_expected_params(self) -> None:
        session = FakeSession(FakeResponse(json_data={"meta": {"has_next": False}, "courses": []}))
        provider = StepikProvider(session=session, interval=0)
        provider.search("Docker", 4)
        params = session.calls[0]["params"]
        self.assertEqual(params["search"], "Docker")
        self.assertEqual(params["is_public"], "true")

    def test_raises_on_http_error(self) -> None:
        from graph_service.learning.parsers import ParserError

        provider = StepikProvider(session=FakeSession(FakeResponse(status_code=403)), retries=1, interval=0)
        with self.assertRaises(ParserError):
            provider.search("Python", 4)


class HabrProviderTests(unittest.TestCase):
    HABR_HTML = """
    <html><body>
      <h2><a href="/ru/articles/111/" class="tm-title__link">  Статья
      про Docker </a></h2>
      <h2><a href="/ru/companies/ozontech/blog/222/" class="tm-title__link">Блоговая статья</a></h2>
      <a href="https://example.com/ru/articles/333/" class="tm-title__link">Внешняя ссылка</a>
      <h2><a href="/ru/articles/111/" class="tm-title__link">Дубль</a></h2>
    </body></html>
    """

    def test_parses_titles_and_absolute_urls(self) -> None:
        provider = HabrProvider(session=FakeSession(FakeResponse(text=self.HABR_HTML)), interval=0)
        results = provider.search("Docker", 5)
        self.assertEqual(len(results), 2)
        first = results[0]
        self.assertEqual(first["url"], "https://habr.com/ru/articles/111/")
        self.assertEqual(first["title"], "Статья про Docker")
        self.assertEqual(first["provider"], "habr")
        self.assertEqual(first["kind"], "article")
        self.assertEqual(results[1]["url"], "https://habr.com/ru/companies/ozontech/blog/222/")

    def test_fallback_finds_plain_article_links(self) -> None:
        html = '<html><body><a href="/ru/articles/444/">Статья Kubernetes</a></body></html>'
        provider = HabrProvider(session=FakeSession(FakeResponse(text=html)), interval=0)
        results = provider.search("Kubernetes", 5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://habr.com/ru/articles/444/")
        self.assertEqual(results[0]["title"], "Статья Kubernetes")


class YouTubeProviderTests(unittest.TestCase):
    def test_without_key_is_not_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            provider = YouTubeProvider(api_key_env="YOUTUBE_API_KEY", interval=0)
            self.assertFalse(provider.configured)
            with self.assertRaises(Exception):
                provider.search("Python", 4)

    def test_maps_video_items(self) -> None:
        payload = {
            "items": [
                {
                    "id": {"videoId": "abc123"},
                    "snippet": {
                        "title": "Python tutorial for beginners",
                        "channelTitle": "Code Channel",
                        "defaultAudioLanguage": "en",
                    },
                },
                {"id": {"kind": "video"}, "snippet": {}},
            ]
        }
        provider = YouTubeProvider(api_key="test-key", session=FakeSession(FakeResponse(json_data=payload)), interval=0)
        self.assertTrue(provider.configured)
        results = provider.search("Python", 4)
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item["url"], "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(item["title"], "Python tutorial for beginners")
        self.assertEqual(item["channel"], "Code Channel")
        self.assertEqual(item["language"], "en")
        self.assertEqual(item["kind"], "video")

    def test_uses_tutorial_query_suffix(self) -> None:
        session = FakeSession(FakeResponse(json_data={"items": []}))
        provider = YouTubeProvider(api_key="test-key", session=session, interval=0)
        provider.search("Docker", 4)
        self.assertEqual(session.calls[0]["params"]["q"], "Docker tutorial")
        self.assertEqual(session.calls[0]["params"]["type"], "video")


if __name__ == "__main__":
    unittest.main()
