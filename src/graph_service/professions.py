from __future__ import annotations

import json
import os
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .config import ConfigError, SLUG_PATTERN


def load_profession_catalog(path: str | Path) -> dict[str, Any]:
    catalog_path = Path(path).resolve()
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Каталог профессий не найден: {catalog_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Некорректный JSON каталога профессий: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("professions"), list):
        raise ConfigError("Каталог профессий должен содержать массив professions.")
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ConfigError("Поле defaults каталога профессий должно быть объектом.")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(data["professions"]):
        if not isinstance(item, dict):
            raise ConfigError(f"professions[{index}] должен быть объектом.")
        name = str(item.get("name", "")).strip()
        slug = str(item.get("slug", "")).strip()
        aliases = [str(value).strip() for value in item.get("aliases", []) if str(value).strip()]
        queries = [str(value).strip() for value in item.get("queries", []) if str(value).strip()]
        if not name or not SLUG_PATTERN.fullmatch(slug) or not queries:
            raise ConfigError(f"professions[{index}] должен иметь name, корректный slug и queries.")
        if slug in seen:
            raise ConfigError(f"Повторный slug профессии: {slug}")
        seen.add(slug)
        normalized.append({"name": name, "slug": slug, "aliases": aliases, "queries": queries})
    return {**data, "professions": normalized, "_path": str(catalog_path)}


def get_profession(catalog: dict[str, Any], slug: str) -> dict[str, Any]:
    for profession in catalog["professions"]:
        if profession["slug"] == slug:
            return profession
    available = ", ".join(item["slug"] for item in catalog["professions"])
    raise ConfigError(f"Профессия {slug!r} не найдена. Доступно: {available}")


def resolve_profession(catalog: dict[str, Any], value: str) -> tuple[dict[str, Any], float, str]:
    requested = value.strip().casefold()
    if not requested:
        raise ConfigError("Название или slug профессии не может быть пустым.")
    candidates: list[tuple[float, dict[str, Any], str]] = []
    for profession in catalog["professions"]:
        labels = [profession["slug"], profession["name"], *profession["aliases"], *profession["queries"]]
        for label in labels:
            normalized = str(label).strip().casefold()
            if requested == normalized:
                return profession, 1.0, str(label)
            score = SequenceMatcher(None, requested, normalized).ratio()
            requested_tokens = set(requested.replace("-", " ").split())
            label_tokens = set(normalized.replace("-", " ").split())
            if requested_tokens and label_tokens:
                score = max(score, len(requested_tokens & label_tokens) / len(requested_tokens | label_tokens))
            candidates.append((score, profession, str(label)))
    score, profession, matched = max(candidates, key=lambda item: item[0])
    if score < 0.45:
        return get_profession(catalog, value), 1.0, value
    return profession, round(score, 3), matched


def build_profession_config(
    catalog: dict[str, Any],
    slug: str,
    output_path: str | Path,
    project_root: str | Path,
) -> dict[str, Any]:
    profession, _, _ = resolve_profession(catalog, slug)
    output = Path(output_path).resolve()
    root = Path(project_root).resolve()
    relative_nodes = Path(os.path.relpath(root / "dictionaries" / "canonical_nodes.json", output.parent)).as_posix()
    relative_phrases = Path(os.path.relpath(root / "rules" / "phrase_rules.json", output.parent)).as_posix()
    relative_splits = Path(os.path.relpath(root / "rules" / "split_rules.json", output.parent)).as_posix()
    defaults = catalog.get("defaults", {})
    return {
        "profession": {
            "name": profession["name"],
            "slug": profession["slug"],
            "aliases": profession["aliases"],
        },
        "grades": ["junior", "middle", "senior"],
        "source": {
            "type": "hh",
            "host": "hh.ru",
            "queries": profession["queries"],
            "areas": list(defaults.get("areas", ["113"])),
            "period_days": int(defaults.get("period_days", 30)),
            "date_chunk_days": int(defaults.get("date_chunk_days", 7)),
            "per_page": int(defaults.get("per_page", 100)),
            "max_pages": int(defaults.get("max_pages", 1)),
            "retries": 3,
            "timeout_seconds": 30,
            "user_agent": "ProfessionalGraphs/0.9 (mlprofessionalgraphs@gmail.com)",
            "user_agent_env": "HH_USER_AGENT",
            "token_env": "HH_API_TOKEN",
            "include_inactive": False,
        },
        "dictionaries": {"nodes": relative_nodes},
        "rules": {"phrases": relative_phrases, "splits": relative_splits},
        "graph": {
            "min_children": 3,
            "min_count": 1,
            "target_depth": 4,
            "max_depth": 6,
            "target_leaf_min": 100,
            "target_leaf_max": 180,
        },
        "grade_rules": {
            "conflict_policy": "keep_best",
            "mode": "experience_then_salary",
            "junior_max_years": 1,
            "middle_max_years": 4,
            "salary_currency": "RUR",
            "junior_max_salary": 120000,
            "middle_max_salary": 250000,
            "default_grade": "middle",
        },
        "scoring": {"mode": "prevalence", "status": "approved_by_curator"},
        "learning": {
            "catalog": str(Path(os.path.relpath(root / "dictionaries" / "learning_resources.json", output.parent)).as_posix()),
            "max_per_node": 4,
            "check_links": False,
        },
        "assets": {"template_version": "0.2", "known_icons": {}},
        "ai": {
            "enabled": False,
            "provider": None,
            "model": None,
            "base_url": None,
            "api_key_env": "PROFESSIONAL_GRAPHS_AI_KEY",
            "timeout_seconds": 45,
        },
        "analysis": {
            "duplicate_title_threshold": 0.88,
            "duplicate_text_threshold": 0.82,
            "unknown_min_vacancies": 2,
            "unknown_limit": 50,
            "boilerplate_min_vacancies": 2,
            "boilerplate_min_chars": 80,
        },
    }
