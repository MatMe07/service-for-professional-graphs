from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graph_service.assets import build_assets
from graph_service.models import NodeDefinition


class AssetTests(unittest.TestCase):
    def test_node_kinds_receive_different_templates(self) -> None:
        nodes = [
            NodeDefinition("Python", ("Python",), ("Технологии",), "technology"),
            NodeDefinition("Регрессия", ("Регрессия",), ("Методы",), "method"),
            NodeDefinition("Статистика", ("Статистика",), ("Знания",), "knowledge"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = build_assets(Path(directory), nodes, {node.name for node in nodes})
            self.assertEqual(result["nodes"]["Python"]["template_id"], "technology")
            self.assertEqual(result["nodes"]["Регрессия"]["template_id"], "method")
            self.assertEqual(result["nodes"]["Статистика"]["template_id"], "knowledge")
            self.assertTrue((Path(directory) / "licenses" / "PROJECT-TEMPLATE-LICENSE.txt").is_file())


if __name__ == "__main__":
    unittest.main()
