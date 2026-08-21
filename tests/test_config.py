from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graph_service.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_rejects_invalid_slug(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nodes.json").write_text('{"nodes": []}', encoding="utf-8")
            config = {
                "profession": {"name": "Тест", "slug": "Bad slug"},
                "dictionaries": {"nodes": "nodes.json"},
            }
            path = root / "config.json"
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_rejects_section_weight_above_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nodes.json").write_text('{"nodes": []}', encoding="utf-8")
            config = {
                "profession": {"name": "Тест", "slug": "test"},
                "dictionaries": {"nodes": "nodes.json"},
                "scoring": {"section_weights": {"company": 1.5}},
            }
            path = root / "config.json"
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_phrase_and_split_rules_must_be_configured_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nodes.json").write_text('{"nodes": []}', encoding="utf-8")
            config = {
                "profession": {"name": "Тест", "slug": "test"},
                "dictionaries": {"nodes": "nodes.json"},
                "rules": {"phrases": "phrases.json"},
            }
            path = root / "config.json"
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_rejects_invalid_grade_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nodes.json").write_text('{"nodes": []}', encoding="utf-8")
            config = {
                "profession": {"name": "Тест", "slug": "test"},
                "dictionaries": {"nodes": "nodes.json"},
                "grade_rules": {"junior_max_years": 4, "middle_max_years": 3},
            }
            path = root / "config.json"
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def _write_config(self, root: Path, learning: dict) -> Path:
        (root / "nodes.json").write_text('{"nodes": []}', encoding="utf-8")
        config = {
            "profession": {"name": "Тест", "slug": "test"},
            "dictionaries": {"nodes": "nodes.json"},
            "learning": learning,
        }
        path = root / "config.json"
        path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        return path

    def test_accepts_auto_collect_defaults_and_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_config(self._write_config(root, {"auto_collect": True}))
            self.assertTrue(config.learning["auto_collect"])
            self.assertEqual(config.learning["providers"], ["stepik", "habr", "youtube"])
            self.assertEqual(config.learning["provider_quotas"], {"stepik": 2, "habr": 1, "youtube": 1})

    def test_rejects_unknown_learning_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ConfigError):
                load_config(self._write_config(root, {"providers": ["stepik", "twitter"]}))

    def test_rejects_non_bool_auto_collect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ConfigError):
                load_config(self._write_config(root, {"auto_collect": "yes"}))

    def test_rejects_negative_provider_quota(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ConfigError):
                load_config(self._write_config(root, {"provider_quotas": {"habr": -1}}))


if __name__ == "__main__":
    unittest.main()
