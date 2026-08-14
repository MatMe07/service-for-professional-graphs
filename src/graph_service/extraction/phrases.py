from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import ConfigError, read_json
from ..models import Grade, Requiredness
from ..parsing.text import ParsedText, TextFragment, clause_at, detect_requiredness, normalize_text


@dataclass(frozen=True)
class PhraseTerm:
    term_id: str
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class PhraseOccurrence:
    vacancy_id: str
    grade: Grade
    source_text: str
    start: int
    end: int
    section: str
    requiredness: Requiredness
    language: str
    fragment_index: int
    fragment_text: str
    context: str
    actions: tuple[str, ...]
    object_name: str
    expanded_phrases: tuple[str, ...]
    rule_id: str
    rule_version: str
    status: str = "candidate_only"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["actions"] = list(self.actions)
        result["expanded_phrases"] = list(self.expanded_phrases)
        return result


class ProfessionalPhraseExtractor:
    def __init__(self, phrase_rules: dict[str, Any], split_rules: dict[str, Any]) -> None:
        self.phrase_version = str(phrase_rules.get("version", "unversioned"))
        self.split_version = str(split_rules.get("version", "unversioned"))
        self.actions = _load_terms(phrase_rules, "actions")
        self.objects = _load_terms(phrase_rules, "objects")
        connectors = tuple(str(value).strip() for value in split_rules.get("connectors", []) if str(value).strip())
        if not connectors:
            raise ConfigError("В split rules нужен непустой массив connectors.")
        self.extract_single = bool(split_rules.get("extract_single_action_phrases", True))

        action_aliases = _alias_pattern(self.actions)
        object_aliases = _alias_pattern(self.objects)
        connector_aliases = "|".join(re.escape(normalize_text(value)) for value in sorted(connectors, key=len, reverse=True))
        self.compound_pattern = re.compile(
            rf"(?<!\w)(?P<action1>{action_aliases})\s+(?P<connector>{connector_aliases})\s+"
            rf"(?P<action2>{action_aliases})\s+(?P<object>{object_aliases})(?!\w)",
            flags=re.IGNORECASE,
        )
        self.single_pattern = re.compile(
            rf"(?<!\w)(?P<action>{action_aliases})\s+(?P<object>{object_aliases})(?!\w)",
            flags=re.IGNORECASE,
        )
        self.action_by_alias = _alias_lookup(self.actions)
        self.object_by_alias = _alias_lookup(self.objects)

    @classmethod
    def from_files(cls, phrase_rules_path: Path, split_rules_path: Path) -> ProfessionalPhraseExtractor:
        phrase_rules = read_json(phrase_rules_path)
        split_rules = read_json(split_rules_path)
        if not isinstance(phrase_rules, dict) or not isinstance(split_rules, dict):
            raise ConfigError("Файлы phrase/split rules должны содержать JSON-объекты.")
        return cls(phrase_rules, split_rules)

    @property
    def versions(self) -> dict[str, str]:
        return {"phrase_rules_version": self.phrase_version, "split_rules_version": self.split_version}

    def extract(self, vacancy_id: str, parsed: ParsedText, grade: Grade) -> list[PhraseOccurrence]:
        result: list[PhraseOccurrence] = []
        for fragment in parsed.fragments:
            compound_spans: list[tuple[int, int]] = []
            for match in self.compound_pattern.finditer(fragment.normalized):
                compound_spans.append(match.span())
                actions = (
                    self.action_by_alias[normalize_text(match.group("action1"))],
                    self.action_by_alias[normalize_text(match.group("action2"))],
                )
                object_term = self.object_by_alias[normalize_text(match.group("object"))]
                result.append(
                    self._occurrence(
                        vacancy_id,
                        grade,
                        parsed,
                        fragment,
                        match.start(),
                        match.end(),
                        actions,
                        object_term,
                        "split.coordinated_actions",
                    )
                )

            if not self.extract_single:
                continue
            for match in self.single_pattern.finditer(fragment.normalized):
                if any(match.start() < end and match.end() > start for start, end in compound_spans):
                    continue
                action = self.action_by_alias[normalize_text(match.group("action"))]
                object_term = self.object_by_alias[normalize_text(match.group("object"))]
                result.append(
                    self._occurrence(
                        vacancy_id,
                        grade,
                        parsed,
                        fragment,
                        match.start(),
                        match.end(),
                        (action,),
                        object_term,
                        "phrase.action_object",
                    )
                )
        return sorted(result, key=lambda item: (item.start, item.end, item.rule_id))

    def _occurrence(
        self,
        vacancy_id: str,
        grade: Grade,
        parsed: ParsedText,
        fragment: TextFragment,
        local_start: int,
        local_end: int,
        actions: tuple[PhraseTerm, ...],
        object_term: PhraseTerm,
        rule_id: str,
    ) -> PhraseOccurrence:
        context = clause_at(fragment.normalized, local_start, local_end)
        requiredness = detect_requiredness(context)
        if requiredness == "unknown":
            requiredness = fragment.requiredness
        expanded = tuple(dict.fromkeys(f"{action.name} {object_term.name}" for action in actions))
        global_start = fragment.start + local_start
        global_end = fragment.start + local_end
        source_text = parsed.clean[global_start:global_end]
        return PhraseOccurrence(
            vacancy_id=vacancy_id,
            grade=grade,
            source_text=source_text,
            start=global_start,
            end=global_end,
            section=fragment.section,
            requiredness=requiredness,
            language=fragment.language,
            fragment_index=fragment.index,
            fragment_text=fragment.text,
            context=context,
            actions=tuple(action.name for action in actions),
            object_name=object_term.name,
            expanded_phrases=expanded,
            rule_id=rule_id,
            rule_version=f"phrases.{self.phrase_version};splits.{self.split_version}",
        )


def build_phrase_candidates(occurrences: list[PhraseOccurrence]) -> dict[str, Any]:
    grouped: dict[str, list[PhraseOccurrence]] = {}
    for occurrence in occurrences:
        for phrase in occurrence.expanded_phrases:
            grouped.setdefault(phrase, []).append(occurrence)

    items: list[dict[str, Any]] = []
    for phrase, phrase_occurrences in grouped.items():
        vacancy_ids = sorted({item.vacancy_id for item in phrase_occurrences})
        examples = [
            {
                "vacancy_id": item.vacancy_id,
                "source_text": item.source_text,
                "section": item.section,
                "requiredness": item.requiredness,
            }
            for item in phrase_occurrences[:3]
        ]
        items.append(
            {
                "phrase": phrase,
                "vacancy_count": len(vacancy_ids),
                "occurrence_count": len(phrase_occurrences),
                "vacancy_ids": vacancy_ids,
                "examples": examples,
                "review_action": "approve, rename, merge with an existing node, or reject",
            }
        )
    items.sort(key=lambda item: (-item["vacancy_count"], -item["occurrence_count"], item["phrase"]))
    return {
        "status": "candidates_only; canonical dictionary and graphs are not changed automatically",
        "items": items,
    }


def _load_terms(data: dict[str, Any], key: str) -> tuple[PhraseTerm, ...]:
    values = data.get(key)
    if not isinstance(values, list) or not values:
        raise ConfigError(f"В phrase rules нужен непустой массив {key}.")
    result: list[PhraseTerm] = []
    seen_ids: set[str] = set()
    seen_aliases: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ConfigError(f"{key}[{index}] должен быть объектом.")
        term_id = str(value.get("id", "")).strip()
        name = str(value.get("name", "")).strip()
        aliases = tuple(
            dict.fromkeys(normalize_text(str(alias).strip()) for alias in value.get("aliases", []) if str(alias).strip())
        )
        if not term_id or not name or not aliases:
            raise ConfigError(f"{key}[{index}] должен иметь id, name и aliases.")
        if term_id in seen_ids:
            raise ConfigError(f"Повторный id в {key}: {term_id}")
        duplicate_alias = next((alias for alias in aliases if alias in seen_aliases), None)
        if duplicate_alias:
            raise ConfigError(f"Повторный alias в {key}: {duplicate_alias}")
        seen_ids.add(term_id)
        seen_aliases.update(aliases)
        result.append(PhraseTerm(term_id=term_id, name=name, aliases=aliases))
    return tuple(result)


def _alias_pattern(terms: tuple[PhraseTerm, ...]) -> str:
    aliases = sorted((alias for term in terms for alias in term.aliases), key=len, reverse=True)
    return "|".join(re.escape(alias) for alias in aliases)


def _alias_lookup(terms: tuple[PhraseTerm, ...]) -> dict[str, PhraseTerm]:
    return {alias: term for term in terms for alias in term.aliases}
