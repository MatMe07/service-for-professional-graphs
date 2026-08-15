from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graph_service.config import load_config
from graph_service.professions import build_profession_config, get_profession, load_profession_catalog


ROOT = Path(__file__).resolve().parents[1]


class ProfessionCatalogTests(unittest.TestCase):
    def test_catalog_contains_fifteen_unique_professions(self) -> None:
        catalog = load_profession_catalog(ROOT / "dictionaries" / "professions.json")
        self.assertEqual(len(catalog["professions"]), 15)
        self.assertEqual(len({item["slug"] for item in catalog["professions"]}), 15)
        self.assertEqual(get_profession(catalog, "machine_learning_engineer")["name"], "ML-инженер")

    def test_generated_config_is_loadable(self) -> None:
        catalog = load_profession_catalog(ROOT / "dictionaries" / "professions.json")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "python_developer.json"
            data = build_profession_config(catalog, "python_developer", output, ROOT)
            output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            config = load_config(output)
            self.assertEqual(config.profession_slug, "python_developer")
            self.assertEqual(config.source["queries"][0], "Python разработчик")


if __name__ == "__main__":
    unittest.main()
