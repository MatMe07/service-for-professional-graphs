from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Literal

from ..models import Requiredness


SectionType = Literal["requirements", "responsibilities", "advantages", "conditions", "company", "unknown"]
Language = Literal["ru", "en", "mixed", "unknown"]

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")
SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")

SECTION_HEADINGS: dict[SectionType, tuple[str, ...]] = {
    "requirements": (
        "требования",
        "требования к кандидату",
        "мы ожидаем",
        "ожидания от кандидата",
        "requirements",
        "what we expect",
    ),
    "responsibilities": (
        "обязанности",
        "задачи",
        "чем предстоит заниматься",
        "что нужно делать",
        "responsibilities",
        "what you will do",
    ),
    "advantages": (
        "будет плюсом",
        "будет преимуществом",
        "желательно",
        "преимущества",
        "nice to have",
        "preferred qualifications",
    ),
    "conditions": (
        "условия",
        "мы предлагаем",
        "что предлагаем",
        "conditions",
        "what we offer",
        "benefits",
    ),
    "company": (
        "о компании",
        "о нас",
        "кто мы",
        "about company",
        "about us",
    ),
    "unknown": (),
}

SECTION_DEFAULT_REQUIREDNESS: dict[SectionType, Requiredness] = {
    "requirements": "required",
    "responsibilities": "required",
    "advantages": "preferred",
    "conditions": "unknown",
    "company": "unknown",
    "unknown": "unknown",
}

HEADING_VARIANTS = sorted(
    (variant for variants in SECTION_HEADINGS.values() for variant in variants),
    key=len,
    reverse=True,
)
INLINE_HEADING_RE = re.compile(
    rf"(?:^|(?<=[.!?;]))\s*(?P<heading>{'|'.join(re.escape(value) for value in HEADING_VARIANTS)})\s*:",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class TextFragment:
    index: int
    section: SectionType
    text: str
    normalized: str
    start: int
    end: int
    language: Language
    requiredness: Requiredness
    exclusion_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ParsedText:
    original: str
    clean: str
    normalized: str
    language: Language
    fragments: tuple[TextFragment, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "clean_text": self.clean,
            "normalized_text": self.normalized,
            "language": self.language,
            "fragments": [fragment.to_dict() for fragment in self.fragments],
        }


def clean_html(value: str) -> str:
    with_breaks = re.sub(r"(?i)</?(?:p|div|li|ul|ol|br|h[1-6]|strong)[^>]*>", "\n", value)
    plain = TAG_RE.sub(" ", with_breaks)
    decoded = html.unescape(plain)
    lines = [SPACE_RE.sub(" ", line).strip() for line in decoded.splitlines()]
    return "\n".join(line for line in lines if line)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower().replace("ё", "е")
    normalized = normalized.replace("–", "-").replace("—", "-")
    return SPACE_RE.sub(" ", normalized)


def parse_text(value: str) -> ParsedText:
    clean = clean_html(value)
    normalized = normalize_text(clean)
    fragments: list[TextFragment] = []
    current_section: SectionType = "unknown"
    cursor = 0

    for line in clean.splitlines():
        line_start = clean.find(line, cursor)
        cursor = line_start + len(line)
        direct_section = _heading_type(normalize_text(line).strip(" :.-"))
        if direct_section is not None:
            current_section = direct_section
            continue
        current_section = _append_sectioned_line(fragments, line, line_start, current_section)

    return ParsedText(
        original=value,
        clean=clean,
        normalized=normalized,
        language=detect_language(clean),
        fragments=tuple(fragments),
    )


def _append_fragments(
    fragments: list[TextFragment],
    value: str,
    global_start: int,
    section: SectionType,
) -> None:
    for match in SENTENCE_RE.finditer(value):
        text = match.group(0).strip()
        if not text:
            continue
        local_offset = match.start() + len(match.group(0)) - len(match.group(0).lstrip())
        start = global_start + local_offset
        requiredness = detect_requiredness(text)
        if requiredness == "unknown":
            requiredness = SECTION_DEFAULT_REQUIREDNESS[section]
        fragments.append(
            TextFragment(
                index=len(fragments),
                section=section,
                text=text,
                normalized=normalize_text(text),
                start=start,
                end=start + len(text),
                language=detect_language(text),
                requiredness=requiredness,
                exclusion_reason="company_section" if section == "company" else None,
            )
        )


def _append_sectioned_line(
    fragments: list[TextFragment],
    line: str,
    line_start: int,
    current_section: SectionType,
) -> SectionType:
    headings = list(INLINE_HEADING_RE.finditer(line))
    if not headings:
        _append_fragments(fragments, line, line_start, current_section)
        return current_section

    if headings[0].start() > 0:
        prefix = line[: headings[0].start()]
        _append_fragments(fragments, prefix, line_start, current_section)

    for index, heading in enumerate(headings):
        section = _heading_type(normalize_text(heading.group("heading")))
        if section is None:
            continue
        current_section = section
        content_start = heading.end()
        content_end = headings[index + 1].start() if index + 1 < len(headings) else len(line)
        _append_fragments(
            fragments,
            line[content_start:content_end],
            line_start + content_start,
            current_section,
        )
    return current_section


def _heading_type(value: str) -> SectionType | None:
    for section, variants in SECTION_HEADINGS.items():
        if value in variants:
            return section
    return None


def detect_language(value: str) -> Language:
    cyrillic = len(re.findall(r"[а-яё]", value, flags=re.IGNORECASE))
    latin = len(re.findall(r"[a-z]", value, flags=re.IGNORECASE))
    total = cyrillic + latin
    if total == 0:
        return "unknown"
    if cyrillic / total >= 0.8:
        return "ru"
    if latin / total >= 0.8:
        return "en"
    return "mixed"


def clause_at(text: str, start: int, end: int) -> str:
    separators = "\n,;"
    left = max((text.rfind(mark, 0, start) for mark in separators), default=-1) + 1
    endings = [position for mark in separators if (position := text.find(mark, end)) >= 0]
    right = min(endings) if endings else len(text)
    return text[left:right].strip()


def detect_requiredness(context: str) -> Requiredness:
    lowered = normalize_text(context)
    if any(marker in lowered for marker in ("не требуется", "без необходимости", "not required", "not necessary")):
        return "negated"
    if any(
        marker in lowered
        for marker in ("не обязательно", "не обязателен", "не обязательна", "не обязательны", "optional")
    ):
        return "optional"
    if any(marker in lowered for marker in ("будет плюсом", "желательно", "преимуществ", "nice to have", "preferred")):
        return "preferred"
    if any(
        marker in lowered
        for marker in (
            "обязательно",
            "обязателен",
            "обязательна",
            "обязательны",
            "необходим",
            "требуется",
            "требуются",
            "должен",
            "должна",
            "должны",
            "must",
            "required",
        )
    ):
        return "required"
    return "unknown"
