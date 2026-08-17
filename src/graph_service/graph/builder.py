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
    min_children: int = 3,
) -> dict[Grade, dict[str, Any]]:
    by_name = {node.name: node for node in nodes}
    result: dict[Grade, dict[str, Any]] = {}
    for grade in grades:
        tree: dict[str, Any] = {}
        for node_name, count in sorted(counts.get(grade, {}).items()):
            if count < min_count or node_name not in by_name:
                continue
            _insert(tree, [*by_name[node_name].path, node_name], {"count": count})
        _collapse_sparse_branches(tree, min_children)
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


def _collapse_sparse_branches(tree: dict[str, Any], min_children: int) -> None:
    """Flatten branches that are too small while preserving every skill leaf."""

    changed = True
    while changed:
        changed = False
        for name, child in list(tree.items()):
            if not isinstance(child, dict) or set(child) == {"count"}:
                continue
            _collapse_sparse_branches(child, min_children)
            if len(child) >= min_children:
                continue
            del tree[name]
            for promoted_name, promoted_value in child.items():
                existing = tree.get(promoted_name)
                if existing is None:
                    tree[promoted_name] = promoted_value
                elif existing != promoted_value:
                    raise ValueError(f"Конфликт нод при сворачивании малой ветки: {promoted_name}")
            changed = True
