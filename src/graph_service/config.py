from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Grade, NodeDefinition


SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
SUPPORTED_GRADES: tuple[Grade, ...] = ("junior", "middle", "senior")


class ConfigError(ValueError):
    """Raised when the project configuration is invalid."""


@dataclass(frozen=True)
class AppConfig:
    path: Path
    profession_name: str
    profession_slug: str
    grades: tuple[Grade, ...]
    source: dict[str, Any]
    graph: dict[str, Any]
    scoring: dict[str, Any]
    grade_rules: dict[str, Any]
    analysis: dict[str, Any]
    learning: dict[str, Any]
    assets: dict[str, Any]
    ai: dict[str, Any]
    nodes_path: Path
    learning_catalog_path: Path | None
    phrase_rules_path: Path | None
    split_rules_path: Path | None

    @property
    def project_root(self) -> Path:
        return self.path.parent.parent if self.path.parent.name == "examples" else self.path.parent


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Файл не найден: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Некорректный JSON {path}: {exc}") from exc


def _resolve(base: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    data = read_json(config_path)
    if not isinstance(data, dict):
        raise ConfigError("Корнем конфигурации должен быть объект JSON.")

    profession = data.get("profession", {})
    name = str(profession.get("name", "")).strip()
    slug = str(profession.get("slug", "")).strip()
    if not name:
        raise ConfigError("profession.name обязателен.")
    if not SLUG_PATTERN.fullmatch(slug):
        raise ConfigError("profession.slug должен содержать строчные латинские буквы, цифры и _. ")

    grades = tuple(data.get("grades", SUPPORTED_GRADES))
    if not grades or any(grade not in SUPPORTED_GRADES for grade in grades):
        raise ConfigError("grades должен содержать junior, middle и/или senior.")

    dictionaries = data.get("dictionaries", {})
    nodes_value = dictionaries.get("nodes")
    if not nodes_value:
        raise ConfigError("dictionaries.nodes обязателен.")
    nodes_path = _resolve(config_path.parent, str(nodes_value))

    rules = data.get("rules", {})
    if not isinstance(rules, dict):
        raise ConfigError("rules должен быть объектом.")
    phrase_rules_value = rules.get("phrases")
    split_rules_value = rules.get("splits")
    if bool(phrase_rules_value) != bool(split_rules_value):
        raise ConfigError("rules.phrases и rules.splits должны быть указаны вместе.")
    phrase_rules_path = _resolve(config_path.parent, str(phrase_rules_value)) if phrase_rules_value else None
    split_rules_path = _resolve(config_path.parent, str(split_rules_value)) if split_rules_value else None
    if phrase_rules_path is not None:
        if not isinstance(read_json(phrase_rules_path), dict) or not isinstance(read_json(split_rules_path), dict):
            raise ConfigError("Файлы phrase/split rules должны содержать JSON-объекты.")

    source = data.get("source", {})
    source_type = source.get("type", "file")
    if source_type not in {"file", "hh", "hh_public_pages", "trudvsem",  "hh_requests"}:
        raise ConfigError("source.type должен быть file, hh, hh_public_pages, trudvsem или hh_requests.")
    if source_type == "hh_public_pages":
        public_urls = source.get("urls", [])
        if not isinstance(public_urls, list) or not 1 <= len(public_urls) <= 100:
            raise ConfigError("Для hh_public_pages укажите от 1 до 100 прямых ссылок в source.urls.")
        if not 0 <= float(source.get("request_interval_seconds", 1.0)) <= 30:
            raise ConfigError("source.request_interval_seconds должен быть от 0 до 30.")
    if source_type == "hh":
        period_days = int(source.get("period_days", 30))
        date_chunk_days = int(source.get("date_chunk_days", period_days))
        if not 1 <= date_chunk_days <= period_days <= 30:
            raise ConfigError("Для HH должно выполняться 1 <= date_chunk_days <= period_days <= 30.")
    if source_type == "trudvsem":
        queries = source.get("queries", [])
        if not isinstance(queries, list) or not queries:
            raise ConfigError("Для trudvsem нужен непустой список source.queries.")
        if not 1 <= int(source.get("period_days", 30)) <= 3650:
            raise ConfigError("Для trudvsem source.period_days должен быть от 1 до 3650.")
        if not 1 <= int(source.get("per_page", 100)) <= 100:
            raise ConfigError("Для trudvsem source.per_page должен быть от 1 до 100.")
        if not 1 <= int(source.get("max_pages", 2)) <= 100:
            raise ConfigError("Для trudvsem source.max_pages должен быть от 1 до 100.")

    graph = {
        "min_children": 3,
        "min_count": 1,
        "target_depth": 4,
        "max_depth": 6,
        "target_leaf_min": 100,
        "target_leaf_max": 180,
        **data.get("graph", {}),
    }
    if int(graph["min_children"]) < 1:
        raise ConfigError("graph.min_children должен быть не меньше 1.")
    target_depth = int(graph.get("target_depth", 4))
    max_depth = int(graph.get("max_depth", 6))
    if not 2 <= target_depth <= 6 or not target_depth <= max_depth <= 6:
        raise ConfigError("graph.target_depth и graph.max_depth должны задавать глубину от 2 до 6.")
    target_leaf_min = int(graph["target_leaf_min"])
    target_leaf_max = int(graph["target_leaf_max"])
    if target_leaf_min < 1 or target_leaf_max < target_leaf_min:
        raise ConfigError("graph.target_leaf_min и graph.target_leaf_max задают некорректный диапазон.")

    user_scoring = data.get("scoring", {})
    default_section_weights = {
        "requirements": 1.0,
        "responsibilities": 0.9,
        "advantages": 0.7,
        "conditions": 0.25,
        "company": 0.0,
        "unknown": 0.6,
    }
    scoring = {
        "mode": "prevalence",
        "required": 1.0,
        "preferred": 0.75,
        "optional": 0.5,
        "unknown": 0.6,
        "negated": 0.0,
        "max_employer_share": 0.4,
        "main_status_threshold": 0.6,
        **user_scoring,
    }
    scoring["section_weights"] = {
        **default_section_weights,
        **user_scoring.get("section_weights", {}),
    }
    max_employer_share = float(scoring["max_employer_share"])
    if not 0 < max_employer_share <= 1:
        raise ConfigError("scoring.max_employer_share должен быть больше 0 и не больше 1.")
    for key in ("required", "preferred", "optional", "unknown", "negated"):
        if not 0 <= float(scoring[key]) <= 1:
            raise ConfigError(f"scoring.{key} должен быть от 0 до 1.")
    if not 0 < float(scoring["main_status_threshold"]) <= 1:
        raise ConfigError("scoring.main_status_threshold должен быть больше 0 и не больше 1.")
    for key, value in scoring["section_weights"].items():
        if not 0 <= float(value) <= 1:
            raise ConfigError(f"scoring.section_weights.{key} должен быть от 0 до 1.")
    if scoring["mode"] not in {"prevalence", "weighted_legacy"}:
        raise ConfigError("scoring.mode должен быть prevalence или weighted_legacy.")
    grade_rules = data.get("grade_rules", {})
    if not isinstance(grade_rules, dict):
        raise ConfigError("grade_rules должен быть объектом.")
    if grade_rules.get("conflict_policy", "keep_best") not in {"keep_best", "exclude"}:
        raise ConfigError("grade_rules.conflict_policy должен быть keep_best или exclude.")
    for key in ("title", "text", "experience", "salary", "conflict_score_margin", "conflict_min_score"):
        if key in grade_rules and int(grade_rules[key]) < 0:
            raise ConfigError(f"grade_rules.{key} не может быть отрицательным.")
    junior_max_years = int(grade_rules.get("junior_max_years", 1))
    middle_max_years = int(grade_rules.get("middle_max_years", 4))
    if junior_max_years < 0 or middle_max_years <= junior_max_years:
        raise ConfigError("Границы опыта в grade_rules заданы некорректно.")
    if grade_rules.get("default_grade", "middle") not in SUPPORTED_GRADES:
        raise ConfigError("grade_rules.default_grade должен быть junior, middle или senior.")
    grade_mode = grade_rules.get("mode", "experience_then_salary")
    if grade_mode not in {
        "signals",
        "experience",
        "salary",
        "experience_then_salary",
        "salary_then_experience",
        "combined",
    }:
        raise ConfigError("Некорректный grade_rules.mode.")
    junior_max_salary = float(grade_rules.get("junior_max_salary", 120000))
    middle_max_salary = float(grade_rules.get("middle_max_salary", 250000))
    if junior_max_salary <= 0 or middle_max_salary <= junior_max_salary:
        raise ConfigError("Границы зарплаты в grade_rules заданы некорректно.")
    analysis = {
        "duplicate_title_threshold": 0.88,
        "duplicate_text_threshold": 0.82,
        "unknown_min_vacancies": 2,
        "unknown_limit": 50,
        "boilerplate_min_vacancies": 2,
        "boilerplate_min_chars": 80,
        **data.get("analysis", {}),
    }
    for key in ("duplicate_title_threshold", "duplicate_text_threshold"):
        if not 0 <= float(analysis[key]) <= 1:
            raise ConfigError(f"analysis.{key} должен быть от 0 до 1.")
    if int(analysis["unknown_min_vacancies"]) < 1 or int(analysis["unknown_limit"]) < 1:
        raise ConfigError("Настройки неизвестных фраз должны быть положительными числами.")
    if int(analysis["boilerplate_min_vacancies"]) < 2:
        raise ConfigError("analysis.boilerplate_min_vacancies должен быть не меньше 2.")
    if int(analysis["boilerplate_min_chars"]) < 20:
        raise ConfigError("analysis.boilerplate_min_chars должен быть не меньше 20.")

    learning = {"max_per_node": 4, "check_links": False, **data.get("learning", {})}
    if int(learning["max_per_node"]) < 1:
        raise ConfigError("learning.max_per_node должен быть положительным числом.")
    catalog_value = learning.get("catalog")
    learning_catalog_path = _resolve(config_path.parent, str(catalog_value)) if catalog_value else None
    if learning_catalog_path is not None and not learning_catalog_path.is_file():
        raise ConfigError(f"Каталог учебных материалов не найден: {learning_catalog_path}")

    assets = {"template_version": "0.2", "known_icons": {}, **data.get("assets", {})}
    if not isinstance(assets.get("known_icons"), dict):
        raise ConfigError("assets.known_icons должен быть объектом.")

    ai = {
        "enabled": False,
        "provider": None,
        "model": None,
        "base_url": None,
        "api_key_env": "PROFESSIONAL_GRAPHS_AI_KEY",
        "timeout_seconds": 45,
        **data.get("ai", {}),
    }
    if not isinstance(ai["enabled"], bool):
        raise ConfigError("ai.enabled должен быть true или false.")
    if ai["enabled"] and ai.get("provider") not in {"deepseek", "gemini", "openai", "compatible"}:
        raise ConfigError("Для включённого AI укажите provider: deepseek, gemini, openai или compatible.")
    if ai["enabled"] and not str(ai.get("model") or "").strip():
        raise ConfigError("Для включённого AI укажите ai.model.")
    if not 1 <= int(ai["timeout_seconds"]) <= 180:
        raise ConfigError("ai.timeout_seconds должен быть от 1 до 180.")

    return AppConfig(
        path=config_path,
        profession_name=name,
        profession_slug=slug,
        grades=grades,
        source=source,
        graph=graph,
        scoring=scoring,
        grade_rules=grade_rules,
        analysis=analysis,
        learning=learning,
        assets=assets,
        ai=ai,
        nodes_path=nodes_path,
        learning_catalog_path=learning_catalog_path,
        phrase_rules_path=phrase_rules_path,
        split_rules_path=split_rules_path,
    )


def load_node_definitions(path: Path) -> tuple[str, list[NodeDefinition]]:
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise ConfigError("Словарь нод должен содержать массив nodes.")

    version = str(data.get("version", "unversioned"))
    result: list[NodeDefinition] = []
    seen: set[str] = set()
    for index, item in enumerate(data["nodes"]):
        if not isinstance(item, dict):
            raise ConfigError(f"nodes[{index}] должен быть объектом.")
        name = str(item.get("name", "")).strip()
        path_items = tuple(str(part).strip() for part in item.get("path", []) if str(part).strip())
        aliases = tuple(dict.fromkeys([name, *(str(alias).strip() for alias in item.get("aliases", []))]))
        if not name or not path_items or not aliases:
            raise ConfigError(f"nodes[{index}] должен иметь name, path и aliases.")
        if name in seen:
            raise ConfigError(f"Повторное каноническое имя ноды: {name}")
        seen.add(name)
        result.append(NodeDefinition(name=name, aliases=aliases, path=path_items, kind=str(item.get("kind", "skill"))))
    return version, result
