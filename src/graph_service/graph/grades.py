from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..models import Grade, GradeDecision, Vacancy
from ..parsing.text import normalize_text


DEFAULT_RULES: dict[Grade, dict[str, list[str]]] = {
    "junior": {
        "title": ["junior", "jr", "джуниор", "стажер", "intern", "trainee"],
        "text": [
            "без опыта",
            "до 1 года",
            "под руководством",
            "под наставничеством",
            "начинающий специалист",
            "готовы рассмотреть студентов",
        ],
    },
    "middle": {
        "title": ["middle", "мидл"],
        "text": ["1-3 года", "1–3 года", "от 2 лет", "2-4 года", "2–4 года", "самостоятельно"],
    },
    "senior": {
        "title": ["senior", "sr", "сеньор", "lead", "team lead", "tech lead", "ведущий", "руководитель"],
        "text": [
            "от 5 лет",
            "5+ лет",
            "архитектура",
            "архитектурные решения",
            "наставничество",
            "руководство командой",
            "техническое лидерство",
        ],
    },
}

DEFAULT_WEIGHTS = {
    "title": 5,
    "text": 1,
    "experience": 3,
    "conflict_score_margin": 2,
    "conflict_min_score": 3,
    "junior_max_years": 1,
    "middle_max_years": 4,
    "default_grade": "middle",
}

INTERN_MARKERS = ("intern", "trainee", "стажер", "стажёр", "стажировка")
LEAD_MARKERS = ("lead", "team lead", "tech lead", "ведущий", "руководитель")


def decide_grade(vacancy: Vacancy, custom_rules: dict[str, Any] | None = None) -> GradeDecision:
    configuration = custom_rules or {}
    custom_signals = configuration.get("signals", configuration)
    rules = _merge_rules(custom_signals if isinstance(custom_signals, dict) else {})
    weights = {**DEFAULT_WEIGHTS, **{key: value for key, value in configuration.items() if key in DEFAULT_WEIGHTS}}
    title = normalize_text(vacancy.name)
    text = normalize_text(vacancy.description)
    scores: Counter[Grade] = Counter()
    title_scores: Counter[Grade] = Counter()
    signals: dict[str, list[str]] = {grade: [] for grade in DEFAULT_RULES}

    for grade, sections in rules.items():
        for marker in sections["title"]:
            if _marker_matches(title, marker):
                weight = int(weights["title"])
                scores[grade] += weight
                title_scores[grade] += weight
                signals[grade].append(f"title:{marker}")
        for marker in sections["text"]:
            if _marker_matches(text, marker):
                scores[grade] += int(weights["text"])
                signals[grade].append(f"text:{marker}")

    experience = _experience_signal(
        f"{title}\n{text}",
        junior_max_years=int(weights["junior_max_years"]),
        middle_max_years=int(weights["middle_max_years"]),
    )
    experience_grade: Grade | None = None
    experience_years: int | None = None
    if experience is not None:
        experience_grade, experience_years = experience
        scores[experience_grade] += int(weights["experience"])
        signals[experience_grade].extend(["experience_years", f"experience_years:{experience_years}"])

    if not scores:
        default_grade = str(weights["default_grade"])
        grade: Grade = default_grade if default_grade in DEFAULT_RULES else "middle"  # type: ignore[assignment]
        return GradeDecision(
            grade=grade,
            subgrade=grade,
            confidence=0.34,
            conflict=False,
            signals=signals,
            scores={candidate: 0 for candidate in DEFAULT_RULES},
            conflict_reasons=(),
            resolution="default_grade_no_signals",
        )

    winner = _choose_winner(scores, title_scores)
    top_score = scores[winner]
    total_score = sum(scores.values())
    conflict_reasons = _conflict_reasons(
        scores,
        title_scores,
        experience_grade,
        experience_years,
        margin=int(weights["conflict_score_margin"]),
        min_score=int(weights["conflict_min_score"]),
    )
    conflict = bool(conflict_reasons)
    confidence = round(top_score / total_score, 2)
    combined_text = f"{title}\n{text}"
    subgrade = _subgrade(winner, combined_text)
    return GradeDecision(
        grade=winner,
        subgrade=subgrade,
        confidence=confidence,
        conflict=conflict,
        signals=signals,
        scores={grade: scores.get(grade, 0) for grade in DEFAULT_RULES},
        conflict_reasons=tuple(conflict_reasons),
        resolution="keep_highest_score_pending_review" if conflict else "highest_score",
    )


def _merge_rules(custom: dict[str, Any]) -> dict[Grade, dict[str, list[str]]]:
    merged: dict[Grade, dict[str, list[str]]] = {}
    for grade, sections in DEFAULT_RULES.items():
        grade_custom = custom.get(grade, {}) if isinstance(custom.get(grade, {}), dict) else {}
        merged[grade] = {
            "title": list(dict.fromkeys([*sections["title"], *grade_custom.get("title", [])])),
            "text": list(dict.fromkeys([*sections["text"], *grade_custom.get("text", [])])),
        }
    return merged


def _marker_matches(value: str, marker: str) -> bool:
    normalized = normalize_text(marker).strip()
    if not normalized:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", value, flags=re.IGNORECASE) is not None


def _experience_signal(text: str, junior_max_years: int, middle_max_years: int) -> tuple[Grade, int] | None:
    normalized = normalize_text(text)
    if "без опыта" in normalized:
        return "junior", 0
    candidates: list[int] = []
    for left, right in re.findall(r"(\d+)\s*[-–—]\s*(\d+)\s*(?:лет|года|год|years?|yrs?)", normalized):
        candidates.append(max(int(left), int(right)))
    candidates.extend(
        int(value)
        for value in re.findall(
            r"(?:от|до|более|не менее|минимум)?\s*(\d+)\s*(?:\+\s*)?(?:лет|года|год|years?|yrs?)",
            normalized,
        )
    )
    if not candidates:
        return None
    years = max(candidates)
    if years <= junior_max_years:
        return "junior", years
    if years <= middle_max_years:
        return "middle", years
    return "senior", years


def _choose_winner(scores: Counter[Grade], title_scores: Counter[Grade]) -> Grade:
    grade_priority = {"middle": 2, "senior": 1, "junior": 0}
    return max(
        DEFAULT_RULES,
        key=lambda grade: (scores.get(grade, 0), title_scores.get(grade, 0), grade_priority[grade]),
    )


def _conflict_reasons(
    scores: Counter[Grade],
    title_scores: Counter[Grade],
    experience_grade: Grade | None,
    experience_years: int | None,
    margin: int,
    min_score: int,
) -> list[str]:
    reasons: list[str] = []
    title_grades = [grade for grade in DEFAULT_RULES if title_scores.get(grade, 0) > 0]
    if len(title_grades) > 1:
        reasons.append(f"multiple_title_grades:{','.join(title_grades)}")
    if experience_grade is not None:
        for title_grade in title_grades:
            if title_grade != experience_grade:
                reasons.append(f"title_{title_grade}_vs_experience_{experience_grade}:{experience_years}")

    ranked = sorted(((grade, scores.get(grade, 0)) for grade in DEFAULT_RULES), key=lambda item: -item[1])
    if ranked[1][1] >= min_score and ranked[0][1] - ranked[1][1] <= margin:
        reasons.append(f"close_scores:{ranked[0][0]}={ranked[0][1]},{ranked[1][0]}={ranked[1][1]}")
    return list(dict.fromkeys(reasons))


def _subgrade(grade: Grade, text: str) -> str:
    if grade == "junior" and any(_marker_matches(text, marker) for marker in INTERN_MARKERS):
        return "intern"
    if grade == "senior" and any(_marker_matches(text, marker) for marker in LEAD_MARKERS):
        return "lead"
    return grade
