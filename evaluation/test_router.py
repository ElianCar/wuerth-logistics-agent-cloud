from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.agent.router import build_router_graph, classify_intent
from src.agent.router_template_retriever import find_similar_templates_for_router


ROUTER_EXCERPT = {
    "data_domain": "TPC-H business data",
    "available_data": ["orders", "customers"],
    "question_types": {
        "aggregation": {"needs_sql": True, "complexity": "easy"},
        "explanation": {"needs_sql": False, "complexity": "easy"},
    },
    "complexity_signals": {"easy": ["single metric"], "hard": ["join"]},
    "no_sql_signals": ["help"],
    "blocked": ["drop table"],
}


def fake_router_payload(**overrides: object) -> str:
    payload = {
        "intent": "aggregation",
        "needs_sql": True,
        "needs_clarification": False,
        "blocked_or_unsafe": False,
        "output_mode": "table",
        "language": "de",
        "memory_intent_key": "aggregation",
        "complexity_tier": "easy",
        "complexity_reason": "single table aggregation",
        "constraints": {"time_window": None, "grouping_level": []},
        "execution_plan": ["retrieve_templates", "run_sql_agent", "run_reporting_agent"],
        "clarification_question": "",
    }
    payload.update(overrides)
    return json.dumps(payload)


class RouterTests(unittest.TestCase):
    def test_placeholder_template_retrieval_returns_empty_list(self) -> None:
        self.assertEqual(
            find_similar_templates_for_router(
                "total revenue",
                memory_intent_key="aggregation",
                intent="aggregation",
            ),
            [],
        )

    def test_deterministic_block_stops_before_llm(self) -> None:
        with patch("src.agent.router.invoke_model") as invoke_model:
            result = classify_intent({"user_question": "Please drop table orders"})

        invoke_model.assert_not_called()
        self.assertTrue(result["blocked_or_unsafe"])
        self.assertFalse(result["needs_sql"])
        self.assertEqual(result["template_candidates"], [])

    def test_llm_classification_adds_template_candidates_field(self) -> None:
        with patch("src.agent.router.load_router_excerpt", return_value=ROUTER_EXCERPT), patch(
            "src.agent.router.invoke_model",
            return_value=SimpleNamespace(response_text=fake_router_payload()),
        ):
            result = classify_intent({"user_question": "Wie viele Bestellungen gibt es?"})

        self.assertEqual(result["intent"], "aggregation")
        self.assertEqual(result["memory_intent_key"], "aggregation")
        self.assertEqual(result["template_candidates"], [])

    def test_router_graph_preserves_empty_template_candidates(self) -> None:
        with patch("src.agent.router.load_router_excerpt", return_value=ROUTER_EXCERPT), patch(
            "src.agent.router.invoke_model",
            return_value=SimpleNamespace(response_text=fake_router_payload()),
        ):
            result = build_router_graph().invoke(
                {
                    "user_question": "Wie viele Bestellungen gibt es?",
                    "llm_provider": "gemini",
                    "ollama_host": "http://localhost:11434",
                },
                {"recursion_limit": 10},
            )

        self.assertEqual(result["template_candidates"], [])


if __name__ == "__main__":
    unittest.main()
