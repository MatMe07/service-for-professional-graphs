from __future__ import annotations

import unittest

from graph_service.parsing import parse_text


class ParsingTests(unittest.TestCase):
    def test_html_is_split_into_named_sections_and_fragments(self) -> None:
        parsed = parse_text(
            "<h3>Обязанности</h3><ul><li>Строить API.</li></ul>"
            "<h3>Требования:</h3><p>Необходимо знать Python.</p>"
            "<h3>Будет плюсом:</h3><p>Docker.</p>"
        )
        self.assertEqual(
            [fragment.section for fragment in parsed.fragments],
            ["responsibilities", "requirements", "advantages"],
        )
        self.assertEqual(parsed.fragments[0].requiredness, "required")
        self.assertEqual(parsed.fragments[1].requiredness, "required")
        self.assertEqual(parsed.fragments[2].requiredness, "preferred")
        self.assertEqual(parsed.language, "mixed")
        for fragment in parsed.fragments:
            self.assertEqual(parsed.clean[fragment.start : fragment.end], fragment.text)

    def test_heading_and_content_can_be_on_same_line(self) -> None:
        parsed = parse_text("Requirements: Python and SQL.")
        self.assertEqual(len(parsed.fragments), 1)
        self.assertEqual(parsed.fragments[0].section, "requirements")
        self.assertEqual(parsed.fragments[0].language, "en")

    def test_not_mandatory_is_optional(self) -> None:
        parsed = parse_text("Требования: Docker не обязателен.")
        self.assertEqual(parsed.fragments[0].requiredness, "optional")

    def test_multiple_inline_headings_are_recognized(self) -> None:
        parsed = parse_text("Вводный текст. Требования: Python. Обязанности: Строить API.")
        self.assertEqual(
            [fragment.section for fragment in parsed.fragments],
            ["unknown", "requirements", "responsibilities"],
        )
        self.assertEqual([fragment.text for fragment in parsed.fragments], ["Вводный текст.", "Python.", "Строить API."])


if __name__ == "__main__":
    unittest.main()
