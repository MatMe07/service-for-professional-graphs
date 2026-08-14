from __future__ import annotations

from pathlib import Path

from ..storage import write_json


def build_course_dictionary(root: Path, node_names: set[str]) -> dict[str, list[str]]:
    """Create contract-compatible placeholders until source policy is approved."""
    result = {name: [] for name in sorted(node_names)}
    write_json(root / "course_dictionary.json", result)
    write_json(
        root / "coverage.json",
        {
            "status": "PLACEHOLDER: learning-source access and selection rules await approval",
            "nodes_without_materials": sorted(node_names),
        },
    )
    return result

