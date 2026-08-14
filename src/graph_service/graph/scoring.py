from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..models import Evidence, Grade, Vacancy
from ..parsing.text import normalize_text


DEFAULT_SECTION_WEIGHTS = {
    "requirements": 1.0,
    "responsibilities": 0.9,
    "advantages": 0.7,
    "conditions": 0.25,
    "company": 0.0,
    "unknown": 0.6,
}


def calculate_counts(
    vacancies: list[Vacancy],
    vacancy_grades: dict[str, Grade],
    evidence: list[Evidence],
    coefficients: dict[str, Any],
) -> tuple[dict[Grade, dict[str, int]], list[dict[str, Any]]]:
    grade_totals: dict[Grade, int] = {"junior": 0, "middle": 0, "senior": 0}
    vacancy_map = {vacancy.vacancy_id: vacancy for vacancy in vacancies}
    for vacancy in vacancies:
        grade_totals[vacancy_grades[vacancy.vacancy_id]] += 1

    observations: dict[tuple[Grade, str], list[Evidence]] = defaultdict(list)
    for item in evidence:
        observations[(item.grade, item.node_name)].append(item)

    counts: dict[Grade, dict[str, int]] = {"junior": {}, "middle": {}, "senior": {}}
    components: list[dict[str, Any]] = []
    for (grade, node_name), items in sorted(observations.items()):
        total = grade_totals[grade]
        if total <= 0:
            continue
        section_weights = {**DEFAULT_SECTION_WEIGHTS, **coefficients.get("section_weights", {})}
        vacancy_items: dict[str, list[Evidence]] = defaultdict(list)
        for item in items:
            vacancy_items[item.vacancy_id].append(item)
        vacancy_weights: dict[str, float] = {}
        for vacancy_id, vacancy_evidence in vacancy_items.items():
            weights = [
                float(coefficients.get(item.requiredness, 0.6))
                * float(section_weights.get(item.section, section_weights["unknown"]))
                for item in vacancy_evidence
            ]
            strongest = max(weights, default=0.0)
            if strongest > 0:
                vacancy_weights[vacancy_id] = strongest
        employer_weights: dict[str, float] = defaultdict(float)
        for vacancy_id, weight in vacancy_weights.items():
            vacancy = vacancy_map[vacancy_id]
            employer = normalize_text(vacancy.employer) or f"unknown:{vacancy_id}"
            employer_weights[employer] += weight
        raw_weighted_sum = sum(employer_weights.values())
        employer_cap = max(1.0, total * float(coefficients.get("max_employer_share", 0.4)))
        weighted_sum = sum(min(weight, employer_cap) for weight in employer_weights.values())
        if weighted_sum <= 0:
            continue
        prevalence = len(vacancy_weights) / total
        weighted_prevalence = weighted_sum / total
        count = max(1, min(100, round(weighted_prevalence * 100)))
        counts[grade][node_name] = count
        dates = sorted(
            vacancy_map[vacancy_id].published_at
            for vacancy_id in vacancy_weights
            if vacancy_map[vacancy_id].published_at
        )
        components.append(
            {
                "grade": grade,
                "node_name": node_name,
                "unique_vacancies": len(vacancy_weights),
                "grade_vacancies": total,
                "evidence_mentions": len(items),
                "negated_mentions": sum(item.requiredness == "negated" for item in items),
                "prevalence": round(prevalence, 4),
                "weighted_prevalence": round(weighted_prevalence, 4),
                "raw_weighted_sum": round(raw_weighted_sum, 4),
                "employer_capped_weighted_sum": round(weighted_sum, 4),
                "employer_cap": round(employer_cap, 4),
                "employers": len(employer_weights),
                "first_published_at": dates[0] if dates else None,
                "last_published_at": dates[-1] if dates else None,
                "count": count,
                "formula_status": "TEMPORARY: coefficients await curator approval",
            }
        )
    return counts, components
