from __future__ import annotations

import unittest
from unittest.mock import patch

from src.llm.model_adapter import _anthropic_llm_kwargs


class ModelAdapterTests(unittest.TestCase):
    def test_anthropic_opus_omits_deprecated_temperature_parameter(self) -> None:
        with patch.dict("os.environ", {"LLM_TEMPERATURE": "0", "LLM_MAX_OUTPUT_TOKENS": "2048"}):
            kwargs = _anthropic_llm_kwargs(
                model_name="claude-opus-4-8",
                api_key="test-key",
            )

        self.assertEqual(kwargs["model"], "claude-opus-4-8")
        self.assertEqual(kwargs["api_key"], "test-key")
        self.assertEqual(kwargs["max_tokens"], 2048)
        self.assertNotIn("temperature", kwargs)

    def test_anthropic_non_opus_keeps_temperature_parameter(self) -> None:
        with patch.dict("os.environ", {"LLM_TEMPERATURE": "0.2", "LLM_MAX_OUTPUT_TOKENS": "1024"}):
            kwargs = _anthropic_llm_kwargs(
                model_name="claude-sonnet-4-6",
                api_key="test-key",
            )

        self.assertEqual(kwargs["temperature"], 0.2)
        self.assertEqual(kwargs["max_tokens"], 1024)


if __name__ == "__main__":
    unittest.main()
