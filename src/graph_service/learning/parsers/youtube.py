from __future__ import annotations

import os
from typing import Any

from .base import LearningProvider, ParserError, clean_text


SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


class YouTubeProvider(LearningProvider):
    name = "youtube"

    def __init__(
        self,
        api_key: str | None = None,
        api_key_env: str = "YOUTUBE_API_KEY",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if api_key:
            self.api_key = str(api_key).strip()
        else:
            self.api_key = os.environ.get(api_key_env, "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, node_name: str, limit: int) -> list[dict[str, Any]]:
        if not self.api_key:
            raise ParserError("Ключ YouTube API не задан (переменная окружения YOUTUBE_API_KEY).")
        response = self.get(
            SEARCH_URL,
            params={
                "part": "snippet",
                "q": f"{node_name} tutorial",
                "type": "video",
                "maxResults": min(max(int(limit), 1), 25),
                "key": self.api_key,
            },
        )
        if response.status_code != 200:
            raise ParserError(f"YouTube API вернул HTTP {response.status_code} для запроса «{node_name}».")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ParserError(f"YouTube API вернул некорректный JSON: {exc}") from exc
        items = payload.get("items")
        if not isinstance(items, list):
            raise ParserError("YouTube API вернул неожиданный формат ответа.")
        results: list[dict[str, Any]] = []
        for item in items:
            resource = self._to_resource(node_name, item)
            if resource is not None:
                results.append(resource)
            if len(results) >= limit:
                break
        return results

    def _to_resource(self, node_name: str, item: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        video_id = (item.get("id") or {}).get("videoId")
        snippet = item.get("snippet") or {}
        title = clean_text(snippet.get("title"))
        channel = clean_text(snippet.get("channelTitle"))
        if not video_id or not title:
            return None
        return {
            "node": node_name,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "provider": self.name,
            "kind": "video",
            "language": clean_text(snippet.get("defaultAudioLanguage")) or "unknown",
            "access": "free",
            "level": "unknown",
            "channel": channel or None,
        }
