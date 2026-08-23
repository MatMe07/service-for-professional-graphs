# habr.py
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import LearningProvider, ParserError, clean_text


SEARCH_URL = "https://habr.com/kek/v2/articles/"
HABR_ROOT = "https://habr.com"
ARTICLE_HREF_PATTERN = re.compile(
    r"^/ru/(?:articles|post)/\d+/?$|^/ru/companies/[^/?#]+/(?:articles|blog)/\d+/?$"
)


class HabrProvider(LearningProvider):
    name = "habr"

    def search(self, node_name: str, limit: int) -> list[dict[str, Any]]:
        params = {
            "query": node_name,
            "order": "relevance",
            "fl": "ru",
            "hl": "ru",
            "page": 1,
            "perPage": limit,
        }
        response = self.get(SEARCH_URL, params=params)
        if response.status_code != 200:
            raise ParserError(f"Habr вернул HTTP {response.status_code} для запроса «{node_name}».")
        
        data = response.json()
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        
        publication_ids = data.get("publicationIds", [])
        publications = data.get("publicationRefs", {})
        
        for pub_id in publication_ids:
            article = publications.get(pub_id)
            if not article:
                continue
            
            title_html = article.get("titleHtml", "")
            title = clean_text(re.sub(r'<[^>]+>', '', title_html))
            if not title:
                continue
            
            article_id = article.get("id")
            url = urljoin(HABR_ROOT, f"/ru/news/{article_id}/")
            
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
