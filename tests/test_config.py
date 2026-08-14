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


if __name__ == "__main__":
    unittest.main()
