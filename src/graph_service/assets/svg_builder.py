from __future__ import annotations

import hashlib
import html
from pathlib import Path
from typing import Any

from ..models import NodeDefinition
from ..storage import write_json


PALETTE = ("#2563EB", "#0F766E", "#7C3AED", "#B45309", "#BE123C", "#0369A1")


def build_assets(
    root: Path,
    nodes: list[NodeDefinition],
    used_names: set[str],
    contexts: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    image_dir = root / "images"
    license_dir = root / "licenses"
    license_dir.mkdir(parents=True, exist_ok=True)
    (license_dir / "TEMPLATE-LICENSE.txt").write_text(
        "Project-generated SVG templates. No external icon library is used in version 0.1.\n",
        encoding="utf-8",
    )
    node_map = {node.name: node for node in nodes}
    dictionary: dict[str, Any] = {
        "metadata": {
            "format": "SVG",
            "dimensions": "800x480",
            "generator": "graph_service.assets.svg_builder/0.1",
            "status": "TEMPORARY TEMPLATE ASSETS",
            "unique_nodes": len(used_names),
            "image_files": len(used_names),
        },
        "nodes": {},
    }
    for name in sorted(used_names):
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        relative = Path("images") / digest[:2] / f"{digest}.svg"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        color = PALETTE[int(digest[:2], 16) % len(PALETTE)]
        target.write_text(_svg(name, color), encoding="utf-8")
        node = node_map[name]
        dictionary["nodes"][name] = {
            "id": digest,
            "image": relative.as_posix(),
            "base_node": name,
            "kind": node.kind,
            "source": "project template",
            "license": "TEMPLATE-LICENSE",
            "contexts": (contexts or {}).get(name, []),
        }
    write_json(root / "image_dictionary.json", dictionary)
    return dictionary


def _svg(name: str, color: str) -> str:
    label = html.escape(name)
    initials = html.escape("".join(word[0].upper() for word in name.split()[:3]) or "N")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480" viewBox="0 0 800 480" role="img" aria-label="{label}">
  <rect width="800" height="480" rx="48" fill="#F8FAFC"/>
  <circle cx="400" cy="190" r="112" fill="{color}"/>
  <text x="400" y="218" text-anchor="middle" font-family="Arial, sans-serif" font-size="76" font-weight="700" fill="#FFFFFF">{initials}</text>
  <text x="400" y="365" text-anchor="middle" font-family="Arial, sans-serif" font-size="38" font-weight="600" fill="#0F172A">{label}</text>
</svg>
'''
