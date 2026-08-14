from __future__ import annotations

from difflib import SequenceMatcher
from itertools import combinations
from typing import Any

from ..models import Vacancy
from ..parsing.text import normalize_text


def find_probable_reposts(
    vacancies: list[Vacancy],
    title_threshold: float = 0.88,
    text_threshold: float = 0.82,
) -> list[dict[str, Any]]:
    """Report likely reposts without automatically removing them."""
    result: list[dict[str, Any]] = []
    by_employer: dict[str, list[Vacancy]] = {}
    for vacancy in vacancies:
        employer = normalize_text(vacancy.employer)
        if employer:
            by_employer.setdefault(employer, []).append(vacancy)

    for employer, items in sorted(by_employer.items()):
        for left, right in combinations(items, 2):
            title_similarity = _similarity(left.name, right.name)
            text_similarity = _similarity(_compact(left.description), _compact(right.description))
            if title_similarity < title_threshold or text_similarity < text_threshold:
                continue
            result.append(
                {
                    "vacancy_ids": [left.vacancy_id, right.vacancy_id],
                    "employer": employer,
                    "title_similarity": round(title_similarity, 4),
                    "text_similarity": round(text_similarity, 4),
                    "decision": "probable_repost",
                    "action": "review_required; both vacancies remain included",
                }
            )
    return result


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_text(left), normalize_text(right), autojunk=False).ratio()


def _compact(value: str, limit: int = 5000) -> str:
    return normalize_text(value)[:limit]

