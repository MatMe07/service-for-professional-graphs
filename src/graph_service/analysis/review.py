from __future__ import annotations

import html
from collections import defaultdict
from typing import Any

from ..extraction.phrases import PhraseOccurrence
from ..models import Evidence, Grade, Vacancy
from ..parsing.text import ParsedText
from .boilerplate import BoilerplateMatch


def build_review_report(
    vacancies: list[Vacancy],
    grades: dict[str, Grade],
    grade_decisions: dict[str, dict[str, Any]],
    parsed_by_vacancy: dict[str, ParsedText],
    evidence: list[Evidence],
    excluded_evidence: list[Evidence],
    phrase_occurrences: list[PhraseOccurrence],
    phrase_candidates: dict[str, Any],
    boilerplate_matches: list[BoilerplateMatch],
) -> dict[str, Any]:
    active_by_vacancy = _group_evidence(evidence)
    excluded_by_vacancy = _group_evidence(excluded_evidence)
    phrases_by_vacancy: dict[str, list[PhraseOccurrence]] = defaultdict(list)
    for item in phrase_occurrences:
        phrases_by_vacancy[item.vacancy_id].append(item)

    vacancy_items: list[dict[str, Any]] = []
    excluded_fragment_count = 0
    for vacancy in vacancies:
        parsed = parsed_by_vacancy[vacancy.vacancy_id]
        excluded_fragments = [
            {
                "fragment_index": fragment.index,
                "section": fragment.section,
                "reason": fragment.exclusion_reason,
                "text": fragment.text,
                "start": fragment.start,
                "end": fragment.end,
            }
            for fragment in parsed.fragments
            if fragment.exclusion_reason
        ]
        excluded_fragment_count += len(excluded_fragments)
        vacancy_items.append(
            {
                "vacancy_id": vacancy.vacancy_id,
                "title": vacancy.name,
                "employer": vacancy.employer,
                "url": vacancy.alternate_url,
                "grade": grades[vacancy.vacancy_id],
                "grade_decision": grade_decisions[vacancy.vacancy_id],
                "skills": active_by_vacancy.get(vacancy.vacancy_id, []),
                "excluded_skill_mentions": excluded_by_vacancy.get(vacancy.vacancy_id, []),
                "professional_phrases": [
                    item.to_dict() for item in phrases_by_vacancy.get(vacancy.vacancy_id, [])
                ],
                "excluded_fragments": excluded_fragments,
                "review_status": "pending",
                "review_comment": "",
            }
        )

    return {
        "status": "manual_review_required",
        "instructions": [
            "Проверьте грейд и найденные навыки по исходным фрагментам.",
            "Убедитесь, что исключённые рекламные фрагменты действительно не описывают требования.",
            "Решения по новым фразам заполните в review_decisions_template.json.",
            "Изменение отчёта само по себе не меняет канонический словарь или граф.",
        ],
        "summary": {
            "vacancies": len(vacancy_items),
            "active_skill_mentions": len(evidence),
            "excluded_skill_mentions": len(excluded_evidence),
            "excluded_fragments": excluded_fragment_count,
            "repeated_boilerplate_blocks": len(boilerplate_matches),
            "professional_phrase_occurrences": len(phrase_occurrences),
            "professional_phrase_candidates": len(phrase_candidates.get("items", [])),
            "grade_conflicts": sum(bool(item.get("conflict")) for item in grade_decisions.values()),
        },
        "phrase_candidates": phrase_candidates.get("items", []),
        "repeated_boilerplate": [item.to_dict() for item in boilerplate_matches],
        "vacancies": vacancy_items,
    }


def build_review_decisions_template(
    phrase_candidates: dict[str, Any],
    boilerplate_matches: list[BoilerplateMatch],
    vacancies: list[Vacancy] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "status": "fill_manually",
        "allowed_decisions": ["pending", "approve", "merge", "reject"],
        "vacancy_reviews": [
            {
                "vacancy_id": vacancy.vacancy_id,
                "grade_decision": "pending",
                "skills_decision": "pending",
                "comment": "",
            }
            for vacancy in (vacancies or [])
        ],
        "phrase_decisions": [
            {
                "phrase": item["phrase"],
                "decision": "pending",
                "canonical_name": "",
                "comment": "",
            }
            for item in phrase_candidates.get("items", [])
        ],
        "boilerplate_decisions": [
            {
                "employer": item.employer,
                "fingerprint": item.fingerprint,
                "decision": "pending",
                "comment": "",
            }
            for item in boilerplate_matches
        ],
    }


def render_review_html(report: dict[str, Any]) -> str:
    summary = report["summary"]
    cards = "".join(
        f'<div class="card"><strong>{html.escape(label)}</strong><span>{value}</span></div>'
        for label, value in (
            ("Вакансии", summary["vacancies"]),
            ("Навыки", summary["active_skill_mentions"]),
            ("Исключено упоминаний", summary["excluded_skill_mentions"]),
            ("Кандидаты фраз", summary["professional_phrase_candidates"]),
            ("Конфликты грейда", summary["grade_conflicts"]),
        )
    )
    candidate_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['phrase'])}</td>"
        f"<td>{item['vacancy_count']}</td>"
        f"<td>{html.escape(', '.join(item['vacancy_ids']))}</td>"
        "<td>Ожидает решения</td>"
        "</tr>"
        for item in report["phrase_candidates"]
    ) or '<tr><td colspan="4">Кандидатов нет</td></tr>'

    vacancy_sections = "".join(_render_vacancy(item) for item in report["vacancies"])
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Проверка профессионального графа</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #f4f6f8; color: #17202a; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    h1, h2 {{ margin-top: 0; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 18px 0 28px; }}
    .card, section, details {{ background: white; border: 1px solid #dfe4e8; border-radius: 10px; }}
    .card {{ padding: 16px; }} .card strong, .card span {{ display: block; }} .card span {{ font-size: 26px; margin-top: 8px; }}
    section {{ padding: 20px; margin: 18px 0; }} details {{ padding: 14px 18px; margin: 12px 0; }}
    summary {{ cursor: pointer; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
    th, td {{ text-align: left; vertical-align: top; padding: 9px; border-bottom: 1px solid #e7ebee; }}
    th {{ background: #f8fafb; }} .muted {{ color: #66727c; }} .excluded {{ background: #fff4e5; padding: 10px; border-radius: 6px; }}
    code {{ white-space: pre-wrap; }}
  </style>
</head>
<body><main>
  <h1>Отчёт для ручной проверки</h1>
  <p class="muted">Отчёт ничего не добавляет в граф автоматически. Решения заполняются в JSON-шаблоне.</p>
  <div class="cards">{cards}</div>
  <section><h2>Новые профессиональные фразы</h2>
    <table><thead><tr><th>Кандидат</th><th>Вакансий</th><th>ID вакансий</th><th>Статус</th></tr></thead>
    <tbody>{candidate_rows}</tbody></table>
  </section>
  <section><h2>Вакансии</h2>{vacancy_sections}</section>
</main></body></html>
"""


def _group_evidence(items: list[Evidence]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[Evidence]] = defaultdict(list)
    for item in items:
        grouped[(item.vacancy_id, item.node_name)].append(item)
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (vacancy_id, node_name), node_items in grouped.items():
        result[vacancy_id].append(
            {
                "node_name": node_name,
                "mention_count": len(node_items),
                "requiredness": sorted({item.requiredness for item in node_items}),
                "sections": sorted({item.section for item in node_items}),
                "exclusion_reasons": sorted(
                    {item.exclusion_reason for item in node_items if item.exclusion_reason}
                ),
                "examples": [
                    {
                        "matched_text": item.matched_text,
                        "fragment_text": item.fragment_text,
                        "start": item.start,
                        "end": item.end,
                    }
                    for item in node_items[:3]
                ],
            }
        )
    for vacancy_items in result.values():
        vacancy_items.sort(key=lambda item: item["node_name"])
    return dict(result)


def _render_vacancy(item: dict[str, Any]) -> str:
    conflict = " — конфликт грейда" if item["grade_decision"].get("conflict") else ""
    skill_rows = "".join(
        "<tr>"
        f"<td>{html.escape(skill['node_name'])}</td>"
        f"<td>{html.escape(', '.join(skill['requiredness']))}</td>"
        f"<td>{html.escape(', '.join(skill['sections']))}</td>"
        f"<td>{'<br>'.join(html.escape(example['fragment_text']) for example in skill['examples'])}</td>"
        "</tr>"
        for skill in item["skills"]
    ) or '<tr><td colspan="4">Навыки не найдены</td></tr>'
    phrase_rows = "".join(
        "<li>"
        f"{html.escape(', '.join(occurrence['expanded_phrases']))} — "
        f"<code>{html.escape(occurrence['source_text'])}</code>"
        "</li>"
        for occurrence in item["professional_phrases"]
    ) or "<li>нет</li>"
    excluded_nodes = ", ".join(
        value["node_name"] for value in item["excluded_skill_mentions"]
    ) or "нет"
    excluded = "".join(
        f'<p class="excluded"><strong>{html.escape(fragment["reason"])}</strong><br>'
        f'<code>{html.escape(fragment["text"])}</code></p>'
        for fragment in item["excluded_fragments"]
    ) or '<p class="muted">Исключённых фрагментов нет.</p>'
    return (
        f"<details><summary>{html.escape(item['title'])} — {html.escape(item['grade'])}{conflict}</summary>"
        f"<p><strong>Работодатель:</strong> {html.escape(item['employer'] or 'не указан')}</p>"
        "<h3>Найденные навыки</h3>"
        "<table><thead><tr><th>Навык</th><th>Обязательность</th><th>Раздел</th><th>Исходный фрагмент</th></tr></thead>"
        f"<tbody>{skill_rows}</tbody></table>"
        f"<h3>Кандидаты фраз</h3><ul>{phrase_rows}</ul>"
        f"<h3>Исключённые фрагменты</h3><p><strong>Навыки внутри:</strong> {html.escape(excluded_nodes)}</p>"
        f"{excluded}</details>"
    )
