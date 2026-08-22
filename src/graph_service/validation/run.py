from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_ROOT_FILES = (
    "evidence.json",
    "excluded_evidence.json",
    "phrase_evidence.json",
    "phrase_candidates.json",
    "alignment_ledger.json",
    "boilerplate_report.json",
    "grade_decisions.json",
    "grade_conflicts.json",
    "scoring_components.json",
    "unclassified.json",
    "duplicates.json",
    "review_report.json",
    "review_report.html",
    "review_decisions_template.json",
)


def validate_run_directory(path: str | Path) -> dict[str, Any]:
    root = Path(path).resolve()
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not root.is_dir():
        return {
            "status": "failed",
            "run_directory": str(root),
            "errors": [{"path": str(root), "message": "Папка запуска не найдена."}],
            "warnings": [],
            "json_files_checked": 0,
        }

    required_paths = [root / name for name in REQUIRED_ROOT_FILES]
    required_paths.extend(
        [
            root / "input" / "profession_config.json",
            root / "input" / "source_queries.json",
            root / "input" / "versions.json",
            root / "output" / "validation_report.json",
        ]
    )
    for required in required_paths:
        if not required.is_file():
            errors.append({"path": str(required.relative_to(root)), "message": "Обязательный файл отсутствует."})

    normalized_files = list((root / "normalized").glob("*.json")) if (root / "normalized").is_dir() else []
    raw_files = list((root / "raw" / "vacancies").glob("*.json")) if (root / "raw" / "vacancies").is_dir() else []
    graph_files = list((root / "output" / "profession_graphs").glob("*.json"))
    if not normalized_files:
        errors.append({"path": "normalized", "message": "Нет нормализованных вакансий."})
    if not raw_files:
        errors.append({"path": "raw/vacancies", "message": "Нет исходных карточек вакансий."})
    if not graph_files:
        errors.append({"path": "output/profession_graphs", "message": "Не сформированы графы."})

    json_files = sorted(root.rglob("*.json"))
    for file in json_files:
        try:
            json.loads(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append({"path": str(file.relative_to(root)), "message": f"JSON не читается: {exc}"})

    html_path = root / "review_report.html"
    if html_path.is_file() and html_path.stat().st_size < 500:
        errors.append({"path": "review_report.html", "message": "HTML-отчёт подозрительно мал."})
    temporary_files = list(root.rglob("*.tmp"))
    if temporary_files:
        warnings.append(
            {
                "path": ", ".join(str(file.relative_to(root)) for file in temporary_files[:5]),
                "message": "После запуска остались временные файлы.",
            }
        )

    validation_path = root / "output" / "validation_report.json"
    missing_grades: list[str] = []
    if validation_path.is_file():
        try:
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            missing_grades = _missing_grades(validation)
            if validation.get("status") == "failed":
                blocking = _blocking_report_errors(validation, missing_grades)
                if blocking or not missing_grades:
                    errors.append({"path": "output/validation_report.json", "message": "Проверка продукта завершилась ошибкой."})
                elif missing_grades:
                    warnings.append(
                        {
                            "path": "output/validation_report.json",
                            "message": (
                                "Отчёт цел, но в выборке нет вакансий уровней: "
                                f"{', '.join(missing_grades)}."
                            ),
                        }
                    )
            elif missing_grades:
                warnings.append(
                    {
                        "path": "output/validation_report.json",
                        "message": f"В выборке нет вакансий уровней: {', '.join(missing_grades)}.",
                    }
                )
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    return {
        "status": "ok" if not errors else "failed",
        "run_directory": str(root),
        "errors": errors,
        "warnings": warnings,
        "json_files_checked": len(json_files),
        "normalized_vacancies": len(normalized_files),
        "raw_vacancies": len(raw_files),
        "graph_files": len(graph_files),
        "missing_grades": missing_grades,
    }


def _missing_grades(validation: dict[str, Any]) -> list[str]:
    explicit = validation.get("missing_grades")
    if isinstance(explicit, list):
        return [str(grade) for grade in explicit]
    leaf_counts = validation.get("leaf_counts")
    graph_issues = validation.get("graph_issues")
    if not isinstance(leaf_counts, dict) or not isinstance(graph_issues, dict):
        return []
    result: list[str] = []
    for grade, count in leaf_counts.items():
        issues = graph_issues.get(grade, [])
        if count == 0 and isinstance(issues, list) and any(
            isinstance(issue, dict)
            and issue.get("message") == "Корень графа не должен быть пустым."
            for issue in issues
        ):
            result.append(str(grade))
    return result


def _blocking_report_errors(
    validation: dict[str, Any],
    missing_grades: list[str],
) -> list[dict[str, Any]]:
    blocking: list[dict[str, Any]] = []
    graph_issues = validation.get("graph_issues")
    if isinstance(graph_issues, dict):
        for grade, issues in graph_issues.items():
            if not isinstance(issues, list):
                continue
            for issue in issues:
                if not isinstance(issue, dict) or issue.get("severity") != "error":
                    continue
                if (
                    str(grade) in missing_grades
                    and issue.get("message") == "Корень графа не должен быть пустым."
                ):
                    continue
                blocking.append(issue)
    product_issues = validation.get("product_issues")
    if isinstance(product_issues, list):
        blocking.extend(
            issue
            for issue in product_issues
            if isinstance(issue, dict) and issue.get("severity") == "error"
        )
    if not isinstance(graph_issues, dict) and not isinstance(product_issues, list):
        blocking.append({"message": "Отчёт не содержит детализации ошибок."})
    return blocking
