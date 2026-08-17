from __future__ import annotations

import unittest

from graph_service.graph.builder import build_grade_graphs
from graph_service.models import NodeDefinition
from graph_service.validation import validate_graph


class GraphBuilderTests(unittest.TestCase):
    def test_sparse_branches_are_flattened_without_losing_leaves(self) -> None:
        nodes = [
            NodeDefinition("Python", ("python",), ("Языки",)),
            NodeDefinition("Git", ("git",), ("Инструменты",)),
            NodeDefinition("Docker", ("docker",), ("Инфраструктура",)),
        ]
        graphs = build_grade_graphs(
            "Разработчик",
            ("junior",),
            nodes,
            {"junior": {"Python": 100, "Git": 80, "Docker": 60}, "middle": {}, "senior": {}},
            min_children=3,
        )
        graph = graphs["junior"]
        self.assertEqual(set(graph["Разработчик"]), {"Python", "Git", "Docker"})
        self.assertEqual(validate_graph(graph, min_children=3), [])


if __name__ == "__main__":
    unittest.main()
