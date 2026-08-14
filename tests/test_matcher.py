from __future__ import annotations

import unittest

from graph_service.extraction import DictionaryMatcher
from graph_service.models import NodeDefinition
from graph_service.parsing import parse_text


class MatcherTests(unittest.TestCase):
    def test_all_alias_occurrences_are_kept_under_canonical_name(self) -> None:
        nodes = [NodeDefinition("Градиентный бустинг", ("градиентный бустинг", "GBDT"), ("Методы",), "method")]
        matcher = DictionaryMatcher(nodes, "test")
        evidence = matcher.match("vacancy-1", parse_text("Требуется GBDT и градиентный бустинг"), "middle")
        self.assertEqual(len(evidence), 2)
        self.assertEqual({item.node_name for item in evidence}, {"Градиентный бустинг"})
        self.assertEqual({item.requiredness for item in evidence}, {"required"})

    def test_negated_requirement_is_marked(self) -> None:
        nodes = [NodeDefinition("Docker", ("Docker",), ("Технологии",), "technology")]
        matcher = DictionaryMatcher(nodes, "test")
        evidence = matcher.match("vacancy-2", parse_text("Docker не требуется."), "junior")
        self.assertEqual(evidence[0].requiredness, "negated")

    def test_requiredness_is_determined_for_each_clause(self) -> None:
        nodes = [
            NodeDefinition("Python", ("Python",), ("Языки",)),
            NodeDefinition("SQL", ("SQL",), ("Языки",)),
        ]
        evidence = DictionaryMatcher(nodes, "test").match(
            "vacancy-3",
            parse_text("Требования: Python не требуется, но SQL требуется."),
            "middle",
        )
        by_node = {item.node_name: item for item in evidence}
        self.assertEqual(by_node["Python"].requiredness, "negated")
        self.assertEqual(by_node["SQL"].requiredness, "required")
        self.assertEqual(by_node["SQL"].section, "requirements")

    def test_company_mention_is_excluded_but_available_for_audit(self) -> None:
        node = NodeDefinition("Python", ("Python",), ("Языки",))
        matcher = DictionaryMatcher([node], "test")
        parsed = parse_text("О компании:\nМы обучаем Python десять лет.")
        self.assertEqual(matcher.match("vacancy-4", parsed, "middle"), [])
        audited = matcher.match("vacancy-4", parsed, "middle", include_excluded=True)
        self.assertEqual(audited[0].section, "company")
        self.assertEqual(audited[0].fragment_text, "Мы обучаем Python десять лет.")
        self.assertEqual(audited[0].exclusion_reason, "company_section")


if __name__ == "__main__":
    unittest.main()
