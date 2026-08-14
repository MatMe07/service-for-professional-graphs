from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..models import Grade, NodeDefinition


def build_grade_graphs(
    profession_name: str,
    grades: tuple[Grade, ...],
    nodes: list[NodeDefinition],
    counts: dict[Grade, dict[str, int]],
    min_count: int = 1,
) -> dict[Grade, dict[str, Any]]:
    by_name = {node.name: node for node in nodes}
    result: dict[Grade, dict[str, Any]] = {}
    for grade in grades:
        tree: dict[str, Any] = {}
        for node_name, count in sorted(counts.get(grade, {}).items()):
            if count < min_count or node_name not in by_name:
                continue
            _insert(tree, [*by_name[node_name].path, node_name], {"count": count})
        result[grade] = {profession_name: deepcopy(tree)}
    return result


def _insert(tree: dict[str, Any], path: list[str], value: dict[str, int]) -> None:
    current = tree
    for part in path[:-1]:
        existing = current.setdefault(part, {})
        if not isinstance(existing, dict) or "count" in existing:
            raise ValueError(f"Конфликт пути графа: {' > '.join(path)}")
        current = existing
    leaf = path[-1]
    if leaf in current and current[leaf] != value:
        raise ValueError(f"Повторная нода с другим значением: {' > '.join(path)}")
    current[leaf] = value

