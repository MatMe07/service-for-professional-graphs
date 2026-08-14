from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable

from ..models import NodeDefinition, Vacancy
from ..parsing.text import ParsedText, normalize_text


TOKEN_RE = re.compile(r"[a-zа-я][a-zа-я0-9+#]*(?:[.-][a-zа-я0-9+#]+)*", flags=re.IGNORECASE)
STOPWORDS = {
    "без",
    "более",
    "будет",
    "ваш",
    "весь",
    "для",
    "его",
    "или",
    "и",
    "как",
    "команда",
    "компании",
    "который",
    "мы",
    "на",
    "наш",
    "не",
    "необходимо",
    "опыт",
    "от",
    "по",
    "работа",
    "работать",
    "с",
    "требуется",
    "что",
    "and",
    "for",
    "the",
    "with",
}


def mine_unknown_phrases(
    parsed_vacancies: Iterable[tuple[Vacancy, ParsedText]],
    nodes: list[NodeDefinition],
    min_vacancies: int = 2,
    limit: int = 50,
) -> dict[str, Any]:
    known_sequences = {
        tuple(_tokenize(normalize_text(alias)))
        for node in nodes
        for alias in node.aliases
        if _tokenize(normalize_text(alias))
    }
    sightings: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, list[dict[str, str]]] = defaultdict(list)

    for vacancy, parsed in parsed_vacancies:
        tokens = _tokenize(parsed.normalized)
        ignored = [False] * len(tokens)
        for start in range(len(tokens)):
            for sequence in known_sequences:
                if tokens[start : start + len(sequence)] == list(sequence):
                    for position in range(start, min(start + len(sequence), len(tokens))):
                        ignored[position] = True
        segments: list[list[str]] = []
        current: list[str] = []
        for token, is_known in zip(tokens, ignored):
            if is_known or token in STOPWORDS:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(token)
        if current:
            segments.append(current)

        vacancy_phrases: set[str] = set()
        for segment in segments:
            for size in (2, 3):
                for start in range(0, len(segment) - size + 1):
                    window = segment[start : start + size]
                    if _looks_professional(window):
                        vacancy_phrases.add(" ".join(window))
        for phrase in vacancy_phrases:
            sightings[phrase].add(vacancy.vacancy_id)
            if len(examples[phrase]) < 3:
                examples[phrase].append(
                    {
                        "vacancy_id": vacancy.vacancy_id,
                        "title": vacancy.name,
                    }
                )

    ranked = sorted(
        (
            {
                "phrase": phrase,
                "vacancy_count": len(vacancy_ids),
                "vacancy_ids": sorted(vacancy_ids),
                "examples": examples[phrase],
            }
            for phrase, vacancy_ids in sightings.items()
            if len(vacancy_ids) >= min_vacancies
        ),
        key=lambda item: (-item["vacancy_count"], item["phrase"]),
    )[:limit]
    return {
        "status": "candidates_only; graph and dictionaries are not changed automatically",
        "min_vacancies": min_vacancies,
        "items": ranked,
    }


def _looks_professional(tokens: list[str]) -> bool:
    if all(token.isalpha() and len(token) < 4 for token in tokens):
        return False
    return any(
        character.isupper() or character.isdigit() or character in "+#.-"
        for token in tokens
        for character in token
    ) or any(len(token) >= 6 for token in tokens)


def _tokenize(value: str) -> list[str]:
    return [token.lower().replace("ё", "е").rstrip(".-") for token in TOKEN_RE.findall(value) if token.rstrip(".-")]
