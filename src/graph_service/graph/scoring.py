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
    mode = str(coefficients.get("mode", "prevalence"))
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
        requiredness_strength = {"required": 1.0, "preferred": 0.75, "optional": 0.5, "unknown": 0.5}
        for vacancy_id, vacancy_evidence in vacancy_items.items():
            positive_evidence = [
                item
                for item in vacancy_evidence
                if item.requiredness != "negated" and item.section != "company" and item.exclusion_reason is None
            ]
            weights = [
                float(coefficients.get(item.requiredness, 0.6))
                * float(section_weights.get(item.section, section_weights["unknown"]))
                for item in positive_evidence
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
        if not vacancy_weights:
            continue
        prevalence = len(vacancy_weights) / total
        weighted_prevalence = weighted_sum / total
        if mode == "weighted_legacy":
            count = max(1, min(100, round(weighted_prevalence * 100)))
            formula = "round(employer_capped_weighted_sum / grade_vacancies * 100)"
        else:
            count = max(1, min(100, round(prevalence * 100)))
            formula = "round(unique_vacancies_with_skill / grade_vacancies * 100)"
        counts[grade][node_name] = count
        dates = sorted(
            vacancy_map[vacancy_id].published_at
            for vacancy_id in vacancy_weights
            if vacancy_map[vacancy_id].published_at
        )
        requiredness_by_vacancy = []
        strong_section_vacancies = 0
        for vacancy_evidence in vacancy_items.values():
            positive = [item for item in vacancy_evidence if item.requiredness != "negated" and item.section != "company"]
            if not positive:
                continue
            requiredness_by_vacancy.append(
                max(requiredness_strength.get(item.requiredness, 0.5) for item in positive)
            )
            if any(item.section in {"requirements", "responsibilities"} for item in positive):
                strong_section_vacancies += 1
        largest_employer_share = max(
            (sum(1 for vacancy_id in vacancy_weights if (normalize_text(vacancy_map[vacancy_id].employer) or f"unknown:{vacancy_id}") == employer) / len(vacancy_weights) for employer in employer_weights),
            default=0.0,
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
                "criticality": round(sum(requiredness_by_vacancy) / len(requiredness_by_vacancy), 4),
                "grade_relevance": 1.0,
                "evidence_confidence": round(strong_section_vacancies / len(vacancy_weights), 4),
                "weighted_prevalence": round(weighted_prevalence, 4),
                "raw_weighted_sum": round(raw_weighted_sum, 4),
                "employer_capped_weighted_sum": round(weighted_sum, 4),
                "employer_cap": round(employer_cap, 4),
                "employers": len(employer_weights),
                "largest_employer_share": round(largest_employer_share, 4),
                "employer_share_warning": largest_employer_share > float(coefficients.get("max_employer_share", 0.4)),
                "first_published_at": dates[0] if dates else None,
                "last_published_at": dates[-1] if dates else None,
                "count": count,
                "mode": mode,
                "formula": formula,
                "formula_status": "APPROVED_BY_CURATOR" if mode == "prevalence" else "LEGACY_COMPATIBILITY_MODE",
            }
        )
    return counts, components
