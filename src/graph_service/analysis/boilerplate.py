from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Iterable

from ..models import Vacancy
from ..parsing.text import ParsedText, normalize_text


BOILERPLATE_MARKERS = (
    "о компании",
    "наша компания",
    "наша команда",
    "мы предлагаем",
    "мы предоставляем",
    "корпоратив",
    "дмс",
    "оформление по тк",
    "социальный пакет",
    "about us",
    "about the company",
    "we offer",
    "our company",
    "our team",
    "benefits",
)


@dataclass(frozen=True)
class BoilerplateMatch:
    employer: str
    fingerprint: str
    vacancy_ids: tuple[str, ...]
    example_text: str
    section: str
    reason: str = "repeated_employer_boilerplate"

    def to_dict(self) -> dict[str, object]:
        return {
            "employer": self.employer,
            "fingerprint": self.fingerprint,
            "vacancy_count": len(self.vacancy_ids),
            "vacancy_ids": list(self.vacancy_ids),
            "example_text": self.example_text,
            "section": self.section,
            "reason": self.reason,
        }


def detect_repeated_boilerplate(
    records: Iterable[tuple[Vacancy, ParsedText]],
    min_vacancies: int = 2,
    min_chars: int = 80,
) -> tuple[dict[tuple[str, str], str], list[BoilerplateMatch]]:
    sightings: dict[tuple[str, str], set[str]] = defaultdict(set)
    examples: dict[tuple[str, str], tuple[str, str, str]] = {}

    for vacancy, parsed in records:
        employer_key = normalize_text(vacancy.employer).strip()
        if not employer_key:
            continue
        for fragment in parsed.fragments:
            normalized = fragment.normalized.strip()
            if len(normalized) < min_chars or not _looks_like_boilerplate(fragment.section, normalized):
                continue
            key = (employer_key, normalized)
            sightings[key].add(vacancy.vacancy_id)
            examples.setdefault(key, (vacancy.employer, fragment.text, fragment.section))

    reasons: dict[tuple[str, str], str] = {}
    matches: list[BoilerplateMatch] = []
    for (employer_key, normalized), vacancy_ids in sightings.items():
        if len(vacancy_ids) < min_vacancies:
            continue
        employer, example_text, section = examples[(employer_key, normalized)]
        reasons[(employer_key, normalized)] = "repeated_employer_boilerplate"
        matches.append(
            BoilerplateMatch(
                employer=employer,
                fingerprint=hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16],
                vacancy_ids=tuple(sorted(vacancy_ids)),
                example_text=example_text,
                section=section,
            )
        )
    matches.sort(key=lambda item: (item.employer.lower(), item.fingerprint))
    return reasons, matches


def apply_boilerplate_exclusions(
    vacancy: Vacancy,
    parsed: ParsedText,
    reasons: dict[tuple[str, str], str],
) -> ParsedText:
    employer_key = normalize_text(vacancy.employer).strip()
    fragments = tuple(
        replace(
            fragment,
            exclusion_reason=fragment.exclusion_reason
            or reasons.get((employer_key, fragment.normalized.strip())),
        )
        for fragment in parsed.fragments
    )
    return replace(parsed, fragments=fragments)


def _looks_like_boilerplate(section: str, normalized: str) -> bool:
    if section in {"company", "conditions"}:
        return True
    return any(marker in normalized for marker in BOILERPLATE_MARKERS)
