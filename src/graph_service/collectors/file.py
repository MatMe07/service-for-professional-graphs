from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ..config import ConfigError, read_json
from ..models import CollectionResult, Vacancy
from .base import Collector


class FileCollector(Collector):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()

    def collect(self) -> CollectionResult:
        data = read_json(self.path)
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ConfigError("Файл вакансий должен быть массивом или объектом с массивом items.")
        default_query_id = f"file:{self.path.stem}"
        vacancies = [_vacancy_from_payload(item, source="file", default_query_id=default_query_id) for item in items]
        unique, duplicates = _deduplicate(vacancies)
        return CollectionResult(vacancies=unique, duplicate_sightings=duplicates)


def _vacancy_from_payload(payload: Any, source: str, default_query_id: str = "") -> Vacancy:
    if not isinstance(payload, dict):
        raise ConfigError("Каждая вакансия должна быть объектом JSON.")
    vacancy_id = str(payload.get("id") or payload.get("vacancy_id") or "").strip()
    if not vacancy_id:
        raise ConfigError("У вакансии отсутствует id.")

    employer_value = payload.get("employer", "")
    employer = str(employer_value.get("name", "")) if isinstance(employer_value, dict) else str(employer_value)
    area_value = payload.get("area", "")
    area = str(area_value.get("name", "")) if isinstance(area_value, dict) else str(area_value)
    query_values = payload.get("query_ids") or payload.get("found_by_queries") or []
    if isinstance(query_values, str):
        query_values = [query_values]
    query_ids = tuple(sorted({str(value) for value in query_values if str(value).strip()}))
    if not query_ids and default_query_id:
        query_ids = (default_query_id,)
    experience_value = payload.get("experience", "")
    experience_id = (
        str(experience_value.get("id", "")) if isinstance(experience_value, dict) else str(experience_value or "")
    )
    salary_value = payload.get("salary")
    salary = salary_value if isinstance(salary_value, dict) else {}
    description_parts = [str(payload.get("description") or "")]
    for field, heading in (
        ("responsibilities", "Обязанности"),
        ("requirements", "Требования"),
        ("conditions", "Условия"),
    ):
        value = payload.get(field)
        if value:
            description_parts.append(f"{heading}:\n{value}")
    key_skills = payload.get("key_skills", [])
    if isinstance(key_skills, list):
        skill_names = [
            str(item.get("name", "") if isinstance(item, dict) else item).strip()
            for item in key_skills
        ]
        skill_names = [name for name in skill_names if name]
        if skill_names:
            description_parts.append("Ключевые навыки:\n" + "\n".join(skill_names))

    def salary_number(value: Any) -> float | None:
        if value in {None, ""}:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return Vacancy(
        vacancy_id=vacancy_id,
        name=str(payload.get("name") or payload.get("title") or "").strip(),
        description="\n".join(part for part in description_parts if part),
        employer=employer.strip(),
        area=area.strip(),
        published_at=str(payload.get("published_at") or ""),
        alternate_url=str(payload.get("alternate_url") or payload.get("url") or ""),
        source=source,
        status=str(payload.get("status") or ("archived" if payload.get("archived") else "active")),
        query_ids=query_ids,
        experience_id=experience_id.strip(),
        salary_from=salary_number(salary.get("from")),
        salary_to=salary_number(salary.get("to")),
        salary_currency=str(salary.get("currency") or "").strip(),
        salary_gross=salary.get("gross") if isinstance(salary.get("gross"), bool) else None,
        raw=payload,
    )


def _deduplicate(vacancies: list[Vacancy]) -> tuple[list[Vacancy], list[dict[str, Any]]]:
    unique: dict[str, Vacancy] = {}
    occurrences: dict[str, int] = {}
    for vacancy in vacancies:
        occurrences[vacancy.vacancy_id] = occurrences.get(vacancy.vacancy_id, 0) + 1
        previous = unique.get(vacancy.vacancy_id)
        if previous is None:
            unique[vacancy.vacancy_id] = vacancy
            continue
        merged_query_ids = tuple(sorted(set(previous.query_ids) | set(vacancy.query_ids)))
        unique[vacancy.vacancy_id] = replace(vacancy, query_ids=merged_query_ids)
    duplicates = [
        {
            "vacancy_id": vacancy_id,
            "occurrences": count,
            "query_ids": list(unique[vacancy_id].query_ids),
            "action": "merged_by_source_id",
        }
        for vacancy_id, count in sorted(occurrences.items())
        if count > 1
    ]
    return list(unique.values()), duplicates
