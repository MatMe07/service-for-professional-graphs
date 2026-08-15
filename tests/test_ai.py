from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graph_service.ai import AIError, ai_status, suggest_dictionary_candidates


class AITests(unittest.TestCase):
    def test_status_does_not_expose_key(self) -> None:
        settings = {
            "enabled": True,
            "provider": "deepseek",
            "model": "deepseek-chat",
            "api_key_env": "TEST_GRAPH_AI_KEY",
        }
        with patch.dict(os.environ, {"TEST_GRAPH_AI_KEY": "secret-value"}, clear=False):
            status = ai_status(settings)
        self.assertTrue(status["ready"])
        self.assertNotIn("secret-value", json.dumps(status))
        self.assertFalse(status["raw_hh_data_transfer"])

    def test_disabled_service_fails_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "unclassified.json"
            source.write_text('{"items": []}', encoding="utf-8")
            with self.assertRaises(AIError):
                suggest_dictionary_candidates(
                    {"enabled": False, "provider": None}, source, root / "result.json"
                )


if __name__ == "__main__":
    unittest.main()
