from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..storage import write_json
from .base import check_resource_url, normalize_resource_url
from .providers import validate_provider


def build_course_dictionary(
    root: Path,
    node_names: set[str],
    catalog_path: Path | None = None,
    max_per_node: int = 4,
    check_links: bool = False,
    extra_resources: list[dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    resources = _load_catalog(catalog_path) if catalog_path is not None else []
    resources += [item for item in (extra_resources or []) if isinstance(item, dict)]
    selected: dict[str, list[dict[str, Any]]] = {name: [] for name in sorted(node_names)}
    seen: dict[str, set[str]] = {name: set() for name in node_names}
    errors: list[dict[str, str]] = []

    for index, item in enumerate(resources):
        node = str(item.get("node", "")).strip()
        if node not in selected:
            continue
        try:
            normalized_url = normalize_resource_url(str(item.get("url", "")))
            provider = str(item.get("provider", "official"))
            validate_provider(provider, normalized_url)
        except ValueError as exc:
            errors.append({"resource": str(index), "message": str(exc)})
            continue
        if normalized_url in seen[node] or len(selected[node]) >= max_per_node:
            continue
        seen[node].add(normalized_url)
        normalized = {
            "resource_id": f"{node}:{len(selected[node]) + 1}",
            "node": node,
            "title": str(item.get("title", node)).strip(),
            "url": normalized_url,
            "provider": provider,
            "kind": str(item.get("kind", "unknown")),
            "language": str(item.get("language", "unknown")),
            "access": str(item.get("access", "unknown")),
            "level": str(item.get("level", "unknown")),
            "duration": item.get("duration"),
            "certificate": item.get("certificate"),
            "subtitles": item.get("subtitles"),
            "practice": item.get("practice"),
            "coverage": str(item.get("coverage", "exact")),
            "availability": check_resource_url(normalized_url) if check_links else {"available": None, "status": "not_checked"},
        }
        selected[node].append(normalized)

    course_dictionary = {
        node: [item["url"] for item in items]
        for node, items in sorted(selected.items())
    }
    without_materials = [node for node, urls in course_dictionary.items() if not urls]
    write_json(root / "course_dictionary.json", course_dictionary)
    write_json(root / "learning_resources.json", [item for items in selected.values() for item in items])
    write_json(
        root / "coverage.json",
        {
            "status": "partial" if without_materials else "complete",
            "catalog": str(catalog_path) if catalog_path else None,
            "nodes_total": len(node_names),
            "nodes_with_materials": len(node_names) - len(without_materials),
            "nodes_without_materials": without_materials,
            "resources_selected": sum(len(items) for items in selected.values()),
            "invalid_resources": errors,
            "links_checked": check_links,
        },
    )
    return course_dictionary


def _load_catalog(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Не удалось прочитать каталог учебных материалов {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("resources"), list):
        raise ValueError("Каталог учебных материалов должен содержать массив resources.")
    return [item for item in data["resources"] if isinstance(item, dict)]
