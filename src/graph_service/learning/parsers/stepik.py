from __future__ import annotations

from typing import Any

from .base import LearningProvider, ParserError, clean_text


API_URL = "https://stepik.org/api/courses"
DIFFICULTY_LEVELS = {"easy": "beginner", "normal": "intermediate", "hard": "advanced"}
MAX_PAGES = 4


class StepikProvider(LearningProvider):
    name = "stepik"

    def search(self, node_name: str, limit: int) -> list[dict[str, Any]]:
        collected: dict[int, dict[str, Any]] = {}
        page = 1
        while page <= MAX_PAGES and len(collected) < limit:
            response = self.get(
                API_URL,
                params={
                    "search": node_name,
                    "is_public": "true",
                    "page": page,
                    "page_size": 20,
                },
            )
            if response.status_code != 200:
                raise ParserError(f"Stepik API вернул HTTP {response.status_code} для запроса «{node_name}».")
            try:
                payload = response.json()
            except ValueError as exc:
                raise ParserError(f"Stepik API вернул некорректный JSON: {exc}") from exc
            courses = payload.get("courses")
            if not isinstance(courses, list):
                raise ParserError("Stepik API вернул неожиданный формат списка курсов.")
            for course in courses:
                if not isinstance(course, dict):
                    continue
                resource = self._to_resource(node_name, course)
                if resource is not None:
                    collected[int(course["id"])] = resource
            meta = payload.get("meta") or {}
            if not meta.get("has_next"):
                break
            page += 1
        resources = list(collected.values())
        resources.sort(key=lambda item: (0 if str(item["language"]).lower().startswith("ru") else 1,))
        return resources[: max(0, limit)]

    def _to_resource(self, node_name: str, course: dict[str, Any]) -> dict[str, Any] | None:
        course_id = course.get("id")
        title = clean_text(course.get("title"))
        if not course_id or not title:
            return None
        if not bool(course.get("is_public", True)) or bool(course.get("is_paid", False)):
            return None
        difficulty = str(course.get("difficulty") or "").strip().lower()
        workload = clean_text(course.get("workload"))
        return {
            "node": node_name,
            "title": title,
            "url": f"https://stepik.org/course/{course_id}/",
            "provider": self.name,
            "kind": "course",
            "language": clean_text(course.get("language")) or "unknown",
            "access": "free",
            "level": DIFFICULTY_LEVELS.get(difficulty, "unknown"),
            "duration": workload or None,
            "certificate": bool(course.get("with_certificate")),
        }
