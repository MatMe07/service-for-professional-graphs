from __future__ import annotations

import unittest
from pathlib import Path

from graph_service.extraction import ProfessionalPhraseExtractor, build_phrase_candidates
from graph_service.parsing import parse_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProfessionalPhraseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.extractor = ProfessionalPhraseExtractor.from_files(
            PROJECT_ROOT / "rules" / "phrase_rules.json",
            PROJECT_ROOT / "rules" / "split_rules.json",
        )

    def test_coordinated_actions_are_expanded_into_two_candidates(self) -> None:
        parsed = parse_text("Требования: Разработка и внедрение ML-моделей обязательна.")
        occurrences = self.extractor.extract("vacancy-1", parsed, "middle")
        self.assertEqual(len(occurrences), 1)
        occurrence = occurrences[0]
        self.assertEqual(
            occurrence.expanded_phrases,
            ("Разработка ML-моделей", "Внедрение ML-моделей"),
        )
        self.assertEqual(occurrence.section, "requirements")
        self.assertEqual(occurrence.requiredness, "required")
        self.assertEqual(parsed.clean[occurrence.start : occurrence.end], occurrence.source_text)

    def test_english_compound_phrase_uses_same_canonical_candidates(self) -> None:
        occurrences = self.extractor.extract(
            "vacancy-2",
            parse_text("Requirements: Developing and deploying ML models is required."),
            "senior",
        )
        self.assertEqual(
            occurrences[0].expanded_phrases,
            ("Разработка ML-моделей", "Развёртывание ML-моделей"),
        )
        self.assertEqual(occurrences[0].language, "en")

    def test_single_negated_professional_phrase_is_kept_for_review(self) -> None:
        occurrences = self.extractor.extract(
            "vacancy-3",
            parse_text("Внедрение ML-моделей не требуется."),
            "junior",
        )
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0].requiredness, "negated")
        candidates = build_phrase_candidates(occurrences)
        self.assertEqual(candidates["items"][0]["phrase"], "Внедрение ML-моделей")
        self.assertEqual(candidates["items"][0]["vacancy_count"], 1)

    def test_unapproved_free_form_phrase_is_not_invented(self) -> None:
        occurrences = self.extractor.extract(
            "vacancy-4",
            parse_text("Работа с большими и интересными ML-моделями."),
            "middle",
        )
        self.assertEqual(occurrences, [])


if __name__ == "__main__":
    unittest.main()
