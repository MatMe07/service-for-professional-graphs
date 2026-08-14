from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_ROOT_FILES = (
    "evidence.json",
    "excluded_evidence.json",
    "phrase_evidence.json",
    "phrase_candidates.json",
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
    if validation_path.is_file():
        try:
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            if validation.get("status") == "failed":
                errors.append({"path": "output/validation_report.json", "message": "Проверка продукта завершилась ошибкой."})
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
    }
