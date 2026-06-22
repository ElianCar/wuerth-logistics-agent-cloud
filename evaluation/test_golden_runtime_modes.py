from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import streamlit_app
from src.agent import golden_test_runner as runner
from src.agent.langgraph_sql_agent import SQLAgentConfig
from src.config.scenarios import (
    get_active_scenario_id,
    reset_active_scenario_id,
    set_active_scenario_id,
)


def test_config() -> SQLAgentConfig:
    return SQLAgentConfig(
        primary_model="sonnet",
        fallback_model="opus",
        max_primary_attempts=1,
        llm_provider="anthropic",
        ollama_host="http://localhost:11434",
        secondary_fallback_model="opus",
    )


def valid_sql(sql: str) -> SimpleNamespace:
    return SimpleNamespace(is_valid=True, sql=sql, error="")


def query_result() -> dict[str, object]:
    return {
        "columns": ["value"],
        "rows": [(1,)],
        "row_count": 1,
        "executed_sql": "SELECT 1 AS value",
    }


class GoldenRuntimeModeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_active_scenario_id()

    def tearDown(self) -> None:
        reset_active_scenario_id()

    def test_golden_runner_defaults_to_orchestrator_mode(self) -> None:
        with patch("src.agent.golden_test_runner.load_golden_question_map", return_value={"Q1": {"question_id": "Q1"}}), patch(
            "src.agent.golden_test_runner.load_schema_context",
            return_value="schema",
        ), patch("src.agent.golden_test_runner.append_golden_result"), patch(
            "src.agent.golden_test_runner.evaluate_golden_question",
            return_value={"question_id": "Q1", "passed": True, "runtime_seconds": 0.0},
        ) as evaluate_mock:
            runner.run_golden_tests(["Q1"])

        self.assertEqual(evaluate_mock.call_args.kwargs["runtime_mode"], "orchestrator")

    def test_streamlit_golden_ui_default_runtime_is_orchestrator(self) -> None:
        self.assertEqual(streamlit_app.DEFAULT_GOLDEN_RUNTIME_MODE, "orchestrator")
        self.assertEqual(streamlit_app.GOLDEN_RUNTIME_MODES[0], "orchestrator")
        self.assertIn("Orchestrator", streamlit_app.GOLDEN_RUNTIME_LABELS["orchestrator"])
        self.assertIn("Debug", streamlit_app.GOLDEN_RUNTIME_LABELS["direct_sql_agent"])

    def test_run_golden_agent_calls_orchestrator_for_orchestrator_mode(self) -> None:
        sql_mock = Mock()
        orchestrator_mock = Mock(return_value={"generated_sql": "SELECT 1 AS value"})

        with patch("src.agent.orchestrator.run_orchestrator", orchestrator_mock), patch(
            "src.agent.golden_test_runner.run_sql_agent",
            sql_mock,
        ):
            runner.run_golden_agent(
                {"question": "How many rows?"},
                schema_context="schema",
                use_approved_memory=True,
                config=test_config(),
                runtime_mode="orchestrator",
            )

        orchestrator_mock.assert_called_once()
        sql_mock.assert_not_called()
        self.assertEqual(orchestrator_mock.call_args.kwargs["run_context"], "golden_test_orchestrator")
        self.assertFalse(orchestrator_mock.call_args.kwargs["enable_memory_candidate_generation"])

    def test_run_golden_agent_calls_direct_sql_agent_only_for_direct_mode(self) -> None:
        sql_mock = Mock(return_value={"generated_sql": "SELECT 1 AS value"})

        with patch("src.agent.golden_test_runner.run_sql_agent", sql_mock):
            runner.run_golden_agent(
                {"question": "How many rows?"},
                schema_context="schema",
                use_approved_memory=True,
                config=test_config(),
                runtime_mode="direct_sql_agent",
            )

        sql_mock.assert_called_once()
        self.assertEqual(sql_mock.call_args.args[0], "How many rows?")
        self.assertEqual(sql_mock.call_args.kwargs["run_context"], "golden_test")
        self.assertFalse(sql_mock.call_args.kwargs["use_legacy_memory"])

    def test_use_orchestrator_compatibility_maps_to_runtime_mode(self) -> None:
        self.assertEqual(runner.resolve_golden_runtime_mode(use_orchestrator=True), "orchestrator")
        self.assertEqual(runner.resolve_golden_runtime_mode(use_orchestrator=False), "direct_sql_agent")
        self.assertEqual(
            runner.resolve_golden_runtime_mode("orchestrator", use_orchestrator=False),
            "orchestrator",
        )

    def test_orchestrator_golden_uses_active_demo_scenario_context(self) -> None:
        set_active_scenario_id("demo")
        seen_scenarios: list[str] = []

        def fake_orchestrator(*_args: object, **_kwargs: object) -> dict[str, object]:
            seen_scenarios.append(get_active_scenario_id())
            return {"generated_sql": "SELECT 1 AS value"}

        with patch("src.agent.orchestrator.run_orchestrator", side_effect=fake_orchestrator):
            runner.run_orchestrator_for_golden(
                {"question": "How many rows?"},
                schema_context="schema",
                use_approved_memory=True,
                config=test_config(),
            )

        self.assertEqual(seen_scenarios, ["demo"])

    def test_orchestrator_golden_uses_active_wuerth_scenario_context(self) -> None:
        set_active_scenario_id("wuerth_local")
        seen_scenarios: list[str] = []

        def fake_orchestrator(*_args: object, **_kwargs: object) -> dict[str, object]:
            seen_scenarios.append(get_active_scenario_id())
            return {"generated_sql": "SELECT 1 AS value"}

        with patch("src.agent.orchestrator.run_orchestrator", side_effect=fake_orchestrator):
            runner.run_orchestrator_for_golden(
                {"question": "How many rows?"},
                schema_context="schema",
                use_approved_memory=True,
                config=test_config(),
            )

        self.assertEqual(seen_scenarios, ["wuerth_local"])

    def test_normalized_orchestrator_result_exposes_memory_and_model_metadata(self) -> None:
        normalized = runner._normalize_golden_runtime_result(
            {
                "run_id": "run-1",
                "generated_sql": "SELECT 1 AS value",
                "query_result": query_result(),
                "intent": "aggregation",
                "complexity_tier": "hard",
                "selected_model": "claude-opus-4-8",
                "fallback_model": "claude-opus-4-8",
                "model_used": "claude-opus-4-8",
                "memory_retrieval": {
                    "enabled": True,
                    "method": "tfidf_vector_space",
                    "scenario": "demo",
                    "no_match_reason": "",
                    "ambiguous": False,
                    "candidates": [{"template_id": "demo_template", "score": 0.91}],
                },
                "trace_steps": ["Router decision"],
            },
            "orchestrator",
            active_scenario="demo",
        )

        self.assertEqual(normalized["runtime_mode"], "orchestrator")
        self.assertEqual(normalized["active_scenario"], "demo")
        self.assertEqual(normalized["route_status"], "routed_to_sql")
        self.assertEqual(normalized["complexity_tier"], "hard")
        self.assertEqual(normalized["model_used"], "claude-opus-4-8")
        self.assertEqual(normalized["memory_candidate_ids"], "demo_template")
        self.assertEqual(normalized["memory_candidate_scores"], "0.91")

    def test_evaluate_golden_question_compares_normalized_orchestrator_result(self) -> None:
        raw_orchestrator_result = {
            "run_id": "run-1",
            "generated_sql": "SELECT 1 AS value",
            "query_result": query_result(),
            "validation_success": True,
            "execution_success": True,
            "selected_model": "claude-opus-4-8",
            "model_used": "claude-opus-4-8",
            "intent": "aggregation",
            "complexity_tier": "hard",
            "memory_retrieval": {
                "enabled": True,
                "method": "tfidf_vector_space",
                "scenario": "demo",
                "candidates": [{"template_id": "demo_template", "score": 0.9}],
            },
            "trace_steps": ["Router decision", "Model selection"],
        }

        with patch("src.agent.golden_test_runner.read_solution_sql", return_value="SELECT 1 AS value"), patch(
            "src.agent.golden_test_runner.validate_generated_sql",
            side_effect=lambda sql, _schema: valid_sql(sql),
        ), patch(
            "src.agent.golden_test_runner.execute_read_only_sql_full",
            side_effect=[query_result(), query_result()],
        ), patch(
            "src.agent.golden_test_runner.run_golden_agent",
            return_value=raw_orchestrator_result,
        ), patch("src.agent.golden_test_runner.active_backend_name", return_value="postgres"):
            result = runner.evaluate_golden_question(
                {"question_id": "Q1", "question": "How many?", "solution_sql_file": "q1.sql"},
                batch_run_id="golden-run",
                schema_context="schema",
                use_approved_memory=True,
                config=test_config(),
                runtime_mode="orchestrator",
            )

        self.assertTrue(result["passed"], result.get("failure_reason", ""))
        self.assertEqual(result["runtime_mode"], "orchestrator")
        self.assertEqual(result["route_status"], "routed_to_sql")
        self.assertEqual(result["memory_candidate_ids"], "demo_template")
        self.assertEqual(result["model_used"], "claude-opus-4-8")

    def test_orchestrator_non_sql_route_fails_golden_clearly(self) -> None:
        with patch("src.agent.golden_test_runner.read_solution_sql", return_value="SELECT 1 AS value"), patch(
            "src.agent.golden_test_runner.validate_generated_sql",
            side_effect=lambda sql, _schema: valid_sql(sql),
        ), patch(
            "src.agent.golden_test_runner.execute_read_only_sql_full",
            return_value=query_result(),
        ), patch(
            "src.agent.golden_test_runner.run_golden_agent",
            return_value={
                "needs_sql": False,
                "needs_clarification": True,
                "final_answer": "Welche Kennzahl meinst du?",
                "trace_steps": ["Router decision"],
            },
        ), patch("src.agent.golden_test_runner.active_backend_name", return_value="postgres"):
            result = runner.evaluate_golden_question(
                {"question_id": "Q1", "question": "How many?", "solution_sql_file": "q1.sql"},
                batch_run_id="golden-run",
                schema_context="schema",
                use_approved_memory=True,
                config=test_config(),
                runtime_mode="orchestrator",
            )

        self.assertFalse(result["passed"])
        self.assertEqual(result["failure_type"], "router_not_routed_to_sql")
        self.assertEqual(result["route_status"], "needs_clarification")

    def test_direct_sql_agent_debug_mode_remains_explicit_in_run_golden_tests(self) -> None:
        with patch("src.agent.golden_test_runner.load_golden_question_map", return_value={"Q1": {"question_id": "Q1"}}), patch(
            "src.agent.golden_test_runner.load_schema_context",
            return_value="schema",
        ), patch("src.agent.golden_test_runner.append_golden_result"), patch(
            "src.agent.golden_test_runner.evaluate_golden_question",
            return_value={"question_id": "Q1", "passed": True, "runtime_seconds": 0.0},
        ) as evaluate_mock:
            runner.run_golden_tests(["Q1"], runtime_mode="direct_sql_agent")

        self.assertEqual(evaluate_mock.call_args.kwargs["runtime_mode"], "direct_sql_agent")


if __name__ == "__main__":
    unittest.main()
