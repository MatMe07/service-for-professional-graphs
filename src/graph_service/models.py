from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Grade = Literal["junior", "middle", "senior"]
Requiredness = Literal["required", "preferred", "optional", "unknown", "negated"]


@dataclass(frozen=True)
class Vacancy:
    vacancy_id: str
    name: str
    description: str
    employer: str = ""
    area: str = ""
    published_at: str = ""
    alternate_url: str = ""
    source: str = "file"
    status: str = "active"
    query_ids: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop("raw", None)
        return result


@dataclass(frozen=True)
class GradeDecision:
    grade: Grade
    confidence: float
    conflict: bool
    signals: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NodeDefinition:
    name: str
    aliases: tuple[str, ...]
    path: tuple[str, ...]
    kind: str = "skill"


@dataclass(frozen=True)
class Evidence:
    vacancy_id: str
    node_name: str
    grade: Grade
    matched_text: str
    start: int
    end: int
    requiredness: Requiredness
    rule_id: str
    section: str = "unknown"
    fragment_index: int = -1
    fragment_text: str = ""
    language: str = "unknown"
    context: str = ""
    matched_alias: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CollectionResult:
    vacancies: list[Vacancy]
    search_responses: list[dict[str, Any]] = field(default_factory=list)
    duplicate_sightings: list[dict[str, Any]] = field(default_factory=list)
