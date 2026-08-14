from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..models import Grade, GradeDecision, Vacancy
from ..parsing.text import normalize_text


DEFAULT_RULES: dict[Grade, dict[str, list[str]]] = {
    "junior": {
        "title": ["junior", "джуниор", "стажер", "intern"],
        "text": ["без опыта", "до 1 года", "под руководством", "наставник"],
    },
    "middle": {
        "title": ["middle", "мидл"],
        "text": ["1-3 года", "от 2 лет", "2-4 года", "самостоятельно"],
    },
    "senior": {
        "title": ["senior", "сеньор", "lead", "ведущий"],
        "text": ["от 5 лет", "5+ лет", "архитектура", "наставничество", "руководство командой"],
    },
}


def decide_grade(vacancy: Vacancy, custom_rules: dict[str, Any] | None = None) -> GradeDecision:
    rules = _merge_rules(custom_rules or {})
    title = normalize_text(vacancy.name)
    text = normalize_text(vacancy.description)
    scores: Counter[Grade] = Counter()
    signals: dict[str, list[str]] = {grade: [] for grade in DEFAULT_RULES}

    for grade, sections in rules.items():
        for marker in sections["title"]:
            if normalize_text(marker) in title:
                scores[grade] += 3
                signals[grade].append(f"title:{marker}")
        for marker in sections["text"]:
            if normalize_text(marker) in text:
                scores[grade] += 1
                signals[grade].append(f"text:{marker}")

    experience_signal = _experience_grade(f"{title}\n{text}")
    if experience_signal:
        scores[experience_signal] += 2
        signals[experience_signal].append("experience_years")

    if not scores:
        return GradeDecision(grade="middle", confidence=0.34, conflict=False, signals=signals)

    ranked = scores.most_common()
    winner = ranked[0][0]
    top_score = ranked[0][1]
    total_score = sum(scores.values())
    conflict = len([grade for grade, score in scores.items() if score > 0]) > 1
    confidence = round(top_score / total_score, 2)
    return GradeDecision(grade=winner, confidence=confidence, conflict=conflict, signals=signals)


def _merge_rules(custom: dict[str, Any]) -> dict[Grade, dict[str, list[str]]]:
    merged: dict[Grade, dict[str, list[str]]] = {}
    for grade, sections in DEFAULT_RULES.items():
        grade_custom = custom.get(grade, {})
        merged[grade] = {
            "title": [*sections["title"], *grade_custom.get("title", [])],
            "text": [*sections["text"], *grade_custom.get("text", [])],
        }
    return merged


def _experience_grade(text: str) -> Grade | None:
    candidates = [int(value) for value in re.findall(r"(?:от\s*)?(\d+)\s*(?:\+\s*)?(?:лет|года|год)", text)]
    if not candidates:
        return None
    years = max(candidates)
    if years <= 1:
        return "junior"
    if years <= 4:
        return "middle"
    return "senior"

