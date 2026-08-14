from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .analysis import (
    apply_boilerplate_exclusions,
    build_review_decisions_template,
    build_review_report,
    detect_repeated_boilerplate,
    find_probable_reposts,
    render_review_html,
)
from .assets import build_assets
from .collectors import FileCollector, HHCollector
from .config import AppConfig, load_config, load_node_definitions, read_json
from .extraction import DictionaryMatcher, ProfessionalPhraseExtractor, build_phrase_candidates, mine_unknown_phrases
from .graph import build_grade_graphs, calculate_counts, decide_grade
from .learning import build_course_dictionary
from .models import CollectionResult, Grade
from .parsing import parse_text
from .storage import RunStorage, VacancyHistory, make_run_id, safe_record_name, write_json, write_text
from .validation import validate_graph, validate_product_layers
from .validation.contracts import collect_leaf_names


class PipelineError(RuntimeError):
    pass


GRADE_FILE_SUFFIX: dict[Grade, str] = {
    "junior": "jun",
    "middle": "middle",
    "senior": "senior",
}


def run_pipeline(
    config_path: str | Path,
    runs_root: str | Path,
    vacancies_path: str | Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    dictionary_version, nodes = load_node_definitions(config.nodes_path)
    phrase_extractor = (
        ProfessionalPhraseExtractor.from_files(config.phrase_rules_path, config.split_rules_path)
        if config.phrase_rules_path is not None and config.split_rules_path is not None
        else None
    )
    runs_path = Path(runs_root).resolve()
    storage = RunStorage(runs_path, run_id or make_run_id(config.profession_slug))
    storage.prepare()
    history = VacancyHistory(runs_path.parent / "history")

    write_json(storage.input_dir / "profession_config.json", read_json(config.path))
    write_json(
        storage.input_dir / "versions.json",
        {
            "dictionary_version": dictionary_version,
            "service_version": __version__,
            **(phrase_extractor.versions if phrase_extractor is not None else {}),
        },
    )

    collection = _collect(config, vacancies_path)
    vacancies = collection.vacancies
    if not vacancies:
        raise PipelineError("Сборщик не вернул ни одной вакансии.")
    for index, response in enumerate(collection.search_responses, start=1):
        storage.save_search_response(index, response)

    matcher = DictionaryMatcher(nodes, dictionary_version)
    vacancy_grades: dict[str, Grade] = {}
    grade_decisions: dict[str, dict[str, Any]] = {}
    all_evidence = []
    excluded_evidence = []
    all_phrase_occurrences = []
    excluded_conflicts: list[str] = []
    parsed_vacancies = []
    history_records: dict[str, dict[str, Any]] = {}
    inactive_excluded: list[str] = []
    prepared_records = []
    conflict_policy = str(config.grade_rules.get("conflict_policy", "keep_best"))

    for vacancy in vacancies:
        raw_payload = vacancy.raw or vacancy.to_dict()
        storage.save_raw_vacancy(
            vacancy.vacancy_id,
            raw_payload,
            {
                "source": vacancy.source,
                "status": vacancy.status,
                "query_ids": list(vacancy.query_ids),
            },
        )
        history_records[vacancy.vacancy_id] = history.record(vacancy.source, vacancy.vacancy_id, raw_payload)
        if vacancy.status != "active" and not bool(config.source.get("include_inactive", False)):
            inactive_excluded.append(vacancy.vacancy_id)
            write_json(
                storage.normalized_dir / f"{safe_record_name(vacancy.vacancy_id)}.json",
                {
                    "vacancy": vacancy.to_dict(),
                    "excluded_reason": f"inactive_status:{vacancy.status}",
                },
            )
            continue
        parsed = parse_text(f"{vacancy.name}\n{vacancy.description}")
        description_parsed = parse_text(vacancy.description)
        decision = decide_grade(vacancy, config.grade_rules)
        grade_decisions[vacancy.vacancy_id] = decision.to_dict()
        if decision.conflict and conflict_policy == "exclude":
            excluded_conflicts.append(vacancy.vacancy_id)
            write_json(
                storage.normalized_dir / f"{safe_record_name(vacancy.vacancy_id)}.json",
                {
                    "vacancy": vacancy.to_dict(),
                    "grade": decision.to_dict(),
                    **parsed.to_dict(),
                    "excluded_reason": "grade_conflict",
                },
            )
            continue
        vacancy_grades[vacancy.vacancy_id] = decision.grade
        prepared_records.append((vacancy, parsed, description_parsed, decision))

    boilerplate_reasons, boilerplate_matches = detect_repeated_boilerplate(
        [(vacancy, parsed) for vacancy, parsed, _, _ in prepared_records],
        min_vacancies=int(config.analysis["boilerplate_min_vacancies"]),
        min_chars=int(config.analysis["boilerplate_min_chars"]),
    )
    parsed_by_vacancy = {}
    for vacancy, parsed, description_parsed, decision in prepared_records:
        parsed = apply_boilerplate_exclusions(vacancy, parsed, boilerplate_reasons)
        description_parsed = apply_boilerplate_exclusions(vacancy, description_parsed, boilerplate_reasons)
        parsed_by_vacancy[vacancy.vacancy_id] = parsed
        parsed_vacancies.append((vacancy, description_parsed))
        audited_evidence = matcher.match(
            vacancy.vacancy_id,
            parsed,
            decision.grade,
            include_excluded=True,
        )
        evidence = [item for item in audited_evidence if item.exclusion_reason is None]
        ignored_evidence = [item for item in audited_evidence if item.exclusion_reason is not None]
        phrase_occurrences = (
            phrase_extractor.extract(vacancy.vacancy_id, parsed, decision.grade)
            if phrase_extractor is not None
            else []
        )
        all_evidence.extend(evidence)
        excluded_evidence.extend(ignored_evidence)
        all_phrase_occurrences.extend(phrase_occurrences)
        write_json(
            storage.normalized_dir / f"{safe_record_name(vacancy.vacancy_id)}.json",
            {
                "vacancy": vacancy.to_dict(),
                "grade": decision.to_dict(),
                **parsed.to_dict(),
                "matched_nodes": sorted({item.node_name for item in evidence}),
                "excluded_skill_mentions": [item.to_dict() for item in ignored_evidence],
                "professional_phrases": [item.to_dict() for item in phrase_occurrences],
            },
        )

    included = [vacancy for vacancy in vacancies if vacancy.vacancy_id in vacancy_grades]
    if not included:
        raise PipelineError("После применения правил грейда не осталось вакансий.")

    counts, scoring_components = calculate_counts(included, vacancy_grades, all_evidence, config.scoring)
    graphs = build_grade_graphs(
        config.profession_name,
        config.grades,
        nodes,
        counts,
        min_count=int(config.graph.get("min_count", 1)),
    )

    graphs_dir = storage.output_dir / "profession_graphs"
    graph_issues: dict[str, list[dict[str, str]]] = {}
    for grade, graph in graphs.items():
        write_json(graphs_dir / f"{config.profession_slug}_{GRADE_FILE_SUFFIX[grade]}.json", graph)
        graph_issues[grade] = [
            issue.to_dict() for issue in validate_graph(graph, min_children=int(config.graph["min_children"]))
        ]

    used_names: set[str] = set()
    for graph in graphs.values():
        used_names.update(collect_leaf_names(graph))

    date_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    image_root = storage.output_dir / f"profession_graph_node_images_{date_stamp}"
    course_root = storage.output_dir / f"profession_graph_node_courses_{date_stamp}"
    node_map = {node.name: node for node in nodes}
    image_contexts: dict[str, list[dict[str, Any]]] = {name: [] for name in used_names}
    for grade, grade_counts in counts.items():
        for name in sorted(set(grade_counts) & used_names):
            image_contexts[name].append(
                {
                    "profession": config.profession_name,
                    "grade": grade,
                    "file": f"{config.profession_slug}_{GRADE_FILE_SUFFIX[grade]}.json",
                    "path": [config.profession_name, *node_map[name].path, name],
                }
            )
    image_dictionary = build_assets(image_root, nodes, used_names, image_contexts)
    course_dictionary = build_course_dictionary(course_root, used_names)
    product_issues = [
        issue.to_dict()
        for issue in validate_product_layers(
            {grade: graph for grade, graph in graphs.items()},
            image_dictionary,
            course_dictionary,
            image_root,
        )
    ]

    write_json(storage.root / "evidence.json", [item.to_dict() for item in all_evidence])
    write_json(storage.root / "excluded_evidence.json", [item.to_dict() for item in excluded_evidence])
    write_json(storage.root / "phrase_evidence.json", [item.to_dict() for item in all_phrase_occurrences])
    phrase_candidates = build_phrase_candidates(all_phrase_occurrences)
    write_json(storage.root / "phrase_candidates.json", phrase_candidates)
    explicit_company_fragments = sum(
        fragment.exclusion_reason == "company_section"
        for parsed in parsed_by_vacancy.values()
        for fragment in parsed.fragments
    )
    repeated_fragments = sum(
        fragment.exclusion_reason == "repeated_employer_boilerplate"
        for parsed in parsed_by_vacancy.values()
        for fragment in parsed.fragments
    )
    boilerplate_report = {
        "status": "excluded fragments remain available for audit",
        "settings": {
            "min_vacancies": int(config.analysis["boilerplate_min_vacancies"]),
            "min_chars": int(config.analysis["boilerplate_min_chars"]),
        },
        "explicit_company_fragments": explicit_company_fragments,
        "repeated_fragment_occurrences": repeated_fragments,
        "repeated_blocks": [item.to_dict() for item in boilerplate_matches],
    }
    write_json(storage.root / "boilerplate_report.json", boilerplate_report)
    write_json(storage.root / "scoring_components.json", scoring_components)
    write_json(storage.root / "grade_decisions.json", grade_decisions)
    grade_conflict_items = [
        {
            "vacancy_id": vacancy.vacancy_id,
            "title": vacancy.name,
            "employer": vacancy.employer,
            "url": vacancy.alternate_url,
            "decision": grade_decisions[vacancy.vacancy_id],
            "policy": conflict_policy,
            "pipeline_action": "excluded" if vacancy.vacancy_id in excluded_conflicts else "kept_highest_score",
            "review_required": True,
        }
        for vacancy in vacancies
        if vacancy.vacancy_id in grade_decisions and grade_decisions[vacancy.vacancy_id]["conflict"]
    ]
    write_json(
        storage.root / "grade_conflicts.json",
        {
            "status": "manual_review_required" if grade_conflict_items else "no_conflicts",
            "conflict_policy": conflict_policy,
            "items": grade_conflict_items,
        },
    )
    write_json(storage.root / "vacancy_versions.json", history_records)
    unclassified = mine_unknown_phrases(
        parsed_vacancies,
        nodes,
        min_vacancies=int(config.analysis["unknown_min_vacancies"]),
        limit=int(config.analysis["unknown_limit"]),
    )
    write_json(storage.root / "unclassified.json", unclassified)
    review_report = build_review_report(
        included,
        vacancy_grades,
        grade_decisions,
        parsed_by_vacancy,
        all_evidence,
        excluded_evidence,
        all_phrase_occurrences,
        phrase_candidates,
        boilerplate_matches,
    )
    write_json(storage.root / "review_report.json", review_report)
    write_text(storage.root / "review_report.html", render_review_html(review_report))
    write_json(
        storage.root / "review_decisions_template.json",
        build_review_decisions_template(phrase_candidates, boilerplate_matches, included),
    )
    probable_reposts = find_probable_reposts(
        vacancies,
        title_threshold=float(config.analysis["duplicate_title_threshold"]),
        text_threshold=float(config.analysis["duplicate_text_threshold"]),
    )
    duplicate_report = {
        "status": "exact source IDs are merged; probable reposts require review and remain included",
        "exact_duplicate_sightings": collection.duplicate_sightings,
        "probable_reposts": probable_reposts,
    }
    write_json(storage.root / "duplicates.json", duplicate_report)

    version_statuses = {"new": 0, "changed": 0, "unchanged": 0}
    for item in history_records.values():
        version_statuses[item["status"]] += 1

    report = {
        "run_id": storage.root.name,
        "profession": config.profession_name,
        "dictionary_version": dictionary_version,
        "vacancies_collected": len(vacancies),
        "vacancies_included": len(included),
        "inactive_vacancies_excluded": inactive_excluded,
        "search_responses_saved": len(collection.search_responses),
        "vacancy_versions": version_statuses,
        "exact_duplicate_sightings": len(collection.duplicate_sightings),
        "probable_reposts": len(probable_reposts),
        "unknown_phrase_candidates": len(unclassified["items"]),
        "grade_conflicts": [vacancy_id for vacancy_id, value in grade_decisions.items() if value["conflict"]],
        "grade_conflict_count": len(grade_conflict_items),
        "excluded_conflicts": excluded_conflicts,
        "evidence_count": len(all_evidence),
        "excluded_evidence_count": len(excluded_evidence),
        "excluded_company_fragments": explicit_company_fragments,
        "repeated_boilerplate_blocks": len(boilerplate_matches),
        "repeated_boilerplate_fragment_occurrences": repeated_fragments,
        "professional_phrase_occurrences": len(all_phrase_occurrences),
        "professional_phrase_candidates": len(phrase_candidates["items"]),
        "output_nodes": len(used_names),
        "graph_issues": graph_issues,
        "product_issues": product_issues,
        "temporary_implementations": [
            "canonical dictionary structure awaits curator approval",
            "grade rules and conflict policy",
            "count formula and coefficients",
            "template SVG design",
            "course_dictionary contains empty lists",
            "probable reposts are reported but not automatically excluded",
            "parallel history writes are not locked",
            "professional phrases remain candidates until curator review",
            "live HH probe reached the API but anonymous access was rejected; application token is required",
        ],
    }
    errors = [
        issue
        for issues in graph_issues.values()
        for issue in issues
        if issue["severity"] == "error"
    ] + [issue for issue in product_issues if issue["severity"] == "error"]
    report["status"] = "failed" if errors else "ok_with_placeholders"
    write_json(storage.output_dir / "validation_report.json", report)
    report["run_directory"] = str(storage.root)
    return report


def _collect(config: AppConfig, override_path: str | Path | None) -> CollectionResult:
    if override_path is not None:
        return FileCollector(override_path).collect()
    if config.source.get("type", "file") == "hh":
        return HHCollector(config.source).collect()
    source_path = config.source.get("path")
    if not source_path:
        raise PipelineError("Для source.type=file нужен source.path или параметр --vacancies.")
    candidate = Path(str(source_path))
    if not candidate.is_absolute():
        candidate = (config.path.parent / candidate).resolve()
    return FileCollector(candidate).collect()
