from __future__ import annotations

import re

from ..models import Evidence, Grade, NodeDefinition
from ..parsing.text import ParsedText, clause_at, detect_requiredness, normalize_text


class DictionaryMatcher:
    def __init__(self, nodes: list[NodeDefinition], dictionary_version: str) -> None:
        self.nodes = nodes
        self.dictionary_version = dictionary_version
        self.patterns: list[tuple[NodeDefinition, str, re.Pattern[str]]] = []
        for node in nodes:
            for alias in sorted(node.aliases, key=len, reverse=True):
                normalized = normalize_text(alias)
                pattern = re.compile(rf"(?<!\w){re.escape(normalized)}(?!\w)", flags=re.IGNORECASE)
                self.patterns.append((node, alias, pattern))

    def match(self, vacancy_id: str, parsed: ParsedText, grade: Grade) -> list[Evidence]:
        evidence: list[Evidence] = []
        occupied: dict[tuple[str, int], list[tuple[int, int]]] = {}
        for node, alias, pattern in self.patterns:
            for fragment in parsed.fragments:
                for found in pattern.finditer(fragment.normalized):
                    occupied_key = (node.name, fragment.index)
                    spans = occupied.setdefault(occupied_key, [])
                    if any(found.start() < end and found.end() > start for start, end in spans):
                        continue
                    spans.append((found.start(), found.end()))
                    context = clause_at(fragment.normalized, found.start(), found.end())
                    requiredness = detect_requiredness(context)
                    if requiredness == "unknown":
                        requiredness = fragment.requiredness
                    surface = fragment.text[found.start() : found.end()] or alias
                    evidence.append(
                        Evidence(
                            vacancy_id=vacancy_id,
                            node_name=node.name,
                            grade=grade,
                            matched_text=surface,
                            start=fragment.start + found.start(),
                            end=fragment.start + found.end(),
                            requiredness=requiredness,
                            rule_id=f"dictionary.{self.dictionary_version}",
                            section=fragment.section,
                            fragment_index=fragment.index,
                            fragment_text=fragment.text,
                            language=fragment.language,
                            context=context,
                            matched_alias=alias,
                        )
                    )
        return sorted(evidence, key=lambda item: (item.start, item.end, item.node_name))
