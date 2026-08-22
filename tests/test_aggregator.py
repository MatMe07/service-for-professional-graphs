from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graph_service.learning import build_course_dictionary
from graph_service.learning.aggregator import LearningAggregator
from graph_service.learning.parsers import ParserError


PROVIDER_HOSTS = {"stepik": "stepik.org", "habr": "habr.com", "youtube": "youtube.com"}


class FakeProvider:
    def __init__(
        self,
        name: str,
        results_by_node: dict[str, list[dict]] | None = None,
        error: str | None = None,
        configured: bool = True,
    ) -> None:
        self.name = name
        self.results_by_node = results_by_node or {}
        self.error = error
        self.configured = configured

    def search(self, node_name: str, limit: int) -> list[dict]:
        if self.error:
            raise ParserError(self.error)
        return list(self.results_by_node.get(node_name, []))[:limit]


def item(provider: str, slug: str, **overrides) -> dict:
    base = {
        "title": f"{provider} материал {slug}",
        "url": f"https://{PROVIDER_HOSTS[provider]}/{slug}/",
        "provider": provider,
        "kind": "course" if provider == "stepik" else "article" if provider == "habr" else "video",
        "language": "ru",
        "access": "free",
        "level": "beginner",
    }
    return {**base, **overrides}


def make_aggregator(
    stepik_results: list[dict] | None = None,
    habr_results: list[dict] | None = None,
    youtube_results: list[dict] | None = None,
    **kwargs,
) -> LearningAggregator:
    aggregator = LearningAggregator(**kwargs)
    aggregator.providers = [
        FakeProvider("stepik", {"Python": stepik_results or []}),
        FakeProvider("habr", {"Python": habr_results or []}),
        FakeProvider("youtube", {"Python": youtube_results or []}),
    ]
    return aggregator


class AggregatorQuotaTests(unittest.TestCase):
    def test_respects_provider_quotas(self) -> None:
        aggregator = make_aggregator(
            stepik_results=[item("stepik", f"s{i}") for i in range(1, 5)],
            habr_results=[item("habr", f"h{i}") for i in range(1, 4)],
            youtube_results=[item("youtube", f"y{i}") for i in range(1, 3)],
        )
        collected = aggregator.collect_all(["Python"])
        by_provider: dict[str, int] = {}
        for resource in collected["Python"]:
            by_provider[resource["provider"]] = by_provider.get(resource["provider"], 0) + 1
        self.assertEqual(by_provider, {"stepik": 2, "habr": 1, "youtube": 1})
        self.assertEqual(aggregator.last_stats["Python"]["kept"], 4)

    def test_redistributes_slots_when_provider_empty(self) -> None:
        aggregator = make_aggregator(
            stepik_results=[item("stepik", f"s{i}") for i in range(1, 5)],
            youtube_results=[item("youtube", "y1")],
        )
        collected = aggregator.collect_all(["Python"])
        providers = [resource["provider"] for resource in collected["Python"]]
        self.assertEqual(providers.count("stepik"), 3)
        self.assertEqual(providers.count("youtube"), 1)

    def test_deduplicates_urls_after_normalization(self) -> None:
        with_tracking = item("stepik", "s1", url="https://stepik.org/s1/?utm_source=feed")
        clean = item("stepik", "s1")
        aggregator = make_aggregator(stepik_results=[with_tracking, clean])
        collected = aggregator.collect_all(["Python"])
        urls = [resource["url"] for resource in collected["Python"]]
        self.assertEqual(urls, ["https://stepik.org/s1/"])

    def test_max_per_node_cap(self) -> None:
        aggregator = make_aggregator(
            stepik_results=[item("stepik", f"s{i}") for i in range(1, 6)],
            max_per_node=3,
            quotas={"stepik": 5},
        )
        collected = aggregator.collect_all(["Python"])
        self.assertEqual(len(collected["Python"]), 3)


class AggregatorRobustnessTests(unittest.TestCase):
    def test_skips_items_with_foreign_domain(self) -> None:
        foreign = {
            "title": "Чужой домен",
            "url": "https://example.com/course/",
            "provider": "stepik",
            "kind": "course",
        }
        aggregator = make_aggregator(stepik_results=[foreign, item("stepik", "s1")])
        collected = aggregator.collect_all(["Python"])
        urls = [resource["url"] for resource in collected["Python"]]
        self.assertEqual(urls, ["https://stepik.org/s1/"])

    def test_records_provider_error_without_raising(self) -> None:
        aggregator = LearningAggregator()
        aggregator.providers = [
            FakeProvider("stepik", error="Stepik недоступен"),
            FakeProvider("habr", {"Python": [item("habr", "h1")]}),
            FakeProvider("youtube", configured=False),
        ]
        collected = aggregator.collect_all(["Python"])
        self.assertEqual(len(collected["Python"]), 1)
        self.assertEqual(aggregator.last_errors["Python"], [{"provider": "stepik", "message": "Stepik недоступен"}])
        stats = aggregator.last_stats["Python"]
        self.assertFalse(stats["providers"]["youtube"]["requested"])
        self.assertTrue(stats["providers"]["stepik"]["requested"])
        self.assertEqual(stats["errors"], 1)

    def test_empty_node_returns_empty_list(self) -> None:
        aggregator = make_aggregator()
        collected = aggregator.collect_all(["Python"])
        self.assertEqual(collected["Python"], [])


class AggregatorCatalogIntegrationTests(unittest.TestCase):
    def test_to_catalog_feeds_build_course_dictionary_after_official_docs(self) -> None:
        aggregator = make_aggregator(
            stepik_results=[item("stepik", "s1"), item("stepik", "s2")],
            habr_results=[item("habr", "h1")],
            youtube_results=[item("youtube", "y1")],
        )
        collected = aggregator.collect_all(["Python"])
        catalog = aggregator.to_catalog(collected)
        self.assertTrue(str(catalog["version"]).startswith("auto-"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.json"
            catalog_path.write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "resources": [
                            {
                                "node": "Python",
                                "title": "The Python Tutorial",
                                "url": "https://docs.python.org/3/tutorial/",
                                "provider": "official",
                                "kind": "tutorial",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            courses = build_course_dictionary(
                root / "out",
                {"Python"},
                catalog_path=catalog_path,
                max_per_node=4,
                extra_resources=catalog["resources"],
            )
            self.assertEqual(courses["Python"][0], "https://docs.python.org/3/tutorial/")
            self.assertEqual(len(courses["Python"]), 4)
            resources = json.loads((root / "out" / "learning_resources.json").read_text(encoding="utf-8"))
            self.assertEqual(resources[0]["provider"], "official")


if __name__ == "__main__":
    unittest.main()
