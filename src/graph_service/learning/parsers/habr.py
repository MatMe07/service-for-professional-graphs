from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import LearningProvider, ParserError, clean_text


SEARCH_URL = "https://habr.com/ru/search/"
HABR_ROOT = "https://habr.com"
ARTICLE_HREF_PATTERN = re.compile(
    r"^/ru/(?:articles|post)/\d+/?$|^/ru/companies/[^/?#]+/(?:articles|blog)/\d+/?$"
)


class HabrProvider(LearningProvider):
    name = "habr"

    def search(self, node_name: str, limit: int) -> list[dict[str, Any]]:
        response = self.get(
            SEARCH_URL,
            params={"q": node_name, "target_type": "posts", "order": "relevance"},
        )
        if response.status_code != 200:
            raise ParserError(f"Habr вернул HTTP {response.status_code} для запроса «{node_name}».")
        soup = BeautifulSoup(response.text, "html.parser")
        anchors = [anchor for anchor in soup.select("a.tm-title__link") if anchor.get("href")]
        if not anchors:
            anchors = [
                anchor
                for anchor in soup.find_all("a", href=True)
                if ARTICLE_HREF_PATTERN.match(str(anchor["href"]).strip())
            ]
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for anchor in anchors:
            href = str(anchor["href"]).strip()
            if not ARTICLE_HREF_PATTERN.match(href):
                continue
            url = urljoin(HABR_ROOT, href)
            title = clean_text(anchor.get_text())
            if not title:
                continue
            normalized = self._to_resource(node_name, title, url)
            if normalized["url"] in seen:
                continue
            seen.add(normalized["url"])
            results.append(normalized)
            if len(results) >= limit:
                break
        return results

    def _to_resource(self, node_name: str, title: str, url: str) -> dict[str, Any]:
        return {
            "node": node_name,
            "title": title,
            "url": url,
            "provider": self.name,
            "kind": "article",
            "language": "ru",
            "access": "free",
            "level": "unknown",
        }
