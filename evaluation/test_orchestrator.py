from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import src.agent.orchestrator as orchestrator
from src.agent.langgraph_sql_agent import SQLAgentConfig


def test_config() -> SQLAgentConfig:
    return SQLAgentConfig(
        primary_model="hard-primary",
        fallback_model="fallback-model",
        max_primary_attempts=3,
        llm_provider="gemini",
        ollama_host="http://localhost:11434",
    )


def router_state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "intent": "aggregation",
        "needs_sql": True,
        "needs_clarification": False,
        "blocked_or_unsafe": False,
        "output_mode": "table",
        "language": "de",
        "memory_intent_key": "aggregation",
        "complexity_tier": "hard",
        "complexity_reason": "requires SQL",
        "constraints": {"time_window": None, "grouping_level": []},
        "execution_plan": ["retrieve_templates", "run_sql_agent"],
        "clarification_question": "",
        "template_candidates": [],
    }
    state.update(overrides)
    return state


def sql_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "generated_sql": "SELECT 1",
        "final_sql": "SELECT 1",
        "query_result": {"columns": ["one"], "rows": [(1,)], "row_count": 1},
        "row_count": 1,
        "validation_success": True,
        "execution_success": True,
        "result_status": "im ersten Versuch erfolgreich",
        "final_answer": "Die Antwort ist 1.",
        "answer": "Die Antwort ist 1.",
        "source_tables": ["orders"],
        "total_attempts": 1,
        "fallback_used": False,
        "model_used": "hard-primary",
        "selected_model": "hard-primary",
        "trace_steps": ["SQL agent ran"],
        "error_type": "",
    }
    result.update(overrides)
    return result


class FakeRouter:
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output

    def invoke(self, _input: dict[str, object], _config: dict[str, object]) -> dict[str, object]:
        return self.output


class OrchestratorTests(unittest.TestCase):
    def run_with_fake_router(
        self,
        router_output: dict[str, object],
        sql_output: dict[str, object] | None = None,
        **kwargs: object,
    ) -> tuple[dict[str, object], Mock]:
        sql_mock = Mock(return_value=sql_output or sql_result())
        with patch("src.agent.orchestrator._get_compiled_router", return_value=FakeRouter(router_output)), patch(
            "src.agent.orchestrator.run_sql_agent",
            sql_mock,
        ):
            result = orchestrator.run_orchestrator(
                "Wie viele Bestellungen gibt es?",
                config=test_config(),
                log_to_query_log=False,
                **kwargs,
            )
        return result, sql_mock

    def test_successful_sql_run_preserves_public_contract_fields(self) -> None:
        result, sql_mock = self.run_with_fake_router(router_state())

        sql_mock.assert_called_once()
        router_context = sql_mock.call_args.kwargs["router_context"]
        self.assertEqual(router_context["intent"], "aggregation")
        self.assertEqual(router_context["needs_sql"], True)
        self.assertEqual(router_context["output_mode"], "table")
        self.assertEqual(router_context["language"], "de")
        self.assertEqual(router_context["constraints"], {"time_window": None, "grouping_level": []})
        self.assertEqual(router_context["execution_plan"], ["retrieve_templates", "run_sql_agent"])
        self.assertEqual(router_context["template_candidates"], [])
        for field in (
            "final_sql",
            "generated_sql",
            "row_count",
            "validation_success",
            "execution_success",
            "result_status",
            "final_answer",
            "source_tables",
            "total_attempts",
            "fallback_used",
            "model_used",
            "trace_steps",
        ):
            self.assertIn(field, result)
        self.assertEqual(result["final_sql"], "SELECT 1")
        self.assertEqual(result["template_candidates"], [])

    def test_force_fallback_skips_router_and_cannot_be_overwritten(self) -> None:
        sql_mock = Mock(return_value=sql_result(model_used="fallback-model", selected_model="fallback-model"))
        router_factory = Mock(return_value=FakeRouter(router_state(complexity_tier="easy")))

        with patch("src.agent.orchestrator._get_compiled_router", router_factory), patch(
            "src.agent.orchestrator.run_sql_agent",
            sql_mock,
        ):
            result = orchestrator.run_orchestrator(
                "Wie viele Bestellungen gibt es?",
                config=test_config(),
                force_fallback=True,
                log_to_query_log=False,
            )

        router_factory.assert_not_called()
        called_config = sql_mock.call_args.kwargs["config"]
        self.assertEqual(called_config.primary_model, "fallback-model")
        self.assertEqual(called_config.fallback_model, "fallback-model")
        self.assertTrue(sql_mock.call_args.kwargs["force_fallback"])
        self.assertEqual(result["selected_model"], "fallback-model")

    def test_retry_context_is_forwarded_to_sql_agent(self) -> None:
        _, sql_mock = self.run_with_fake_router(
            router_state(),
            previous_failed_sql="SELECT broken",
            previous_sql_error="syntax error",
            previous_final_answer="old answer",
            user_correction="use revenue instead",
        )

        kwargs = sql_mock.call_args.kwargs
        self.assertEqual(kwargs["previous_failed_sql"], "SELECT broken")
        self.assertEqual(kwargs["previous_sql_error"], "syntax error")
        self.assertEqual(kwargs["previous_final_answer"], "old answer")
        self.assertEqual(kwargs["user_correction"], "use revenue instead")

    def test_needs_clarification_stops_before_sql_execution(self) -> None:
        result, sql_mock = self.run_with_fake_router(
            router_state(
                needs_sql=False,
                needs_clarification=True,
                clarification_question="Welche Kennzahl meinst du?",
            )
        )

        sql_mock.assert_not_called()
        self.assertEqual(result["result_status"], "clarification_needed")
        self.assertEqual(result["final_answer"], "Welche Kennzahl meinst du?")

    def test_blocked_or_unsafe_stops_before_sql_execution(self) -> None:
        result, sql_mock = self.run_with_fake_router(
            router_state(
                intent="blocked",
                needs_sql=False,
                blocked_or_unsafe=True,
                clarification_question="Diese Anfrage kann aus Sicherheitsgründen nicht verarbeitet werden.",
            )
        )

        sql_mock.assert_not_called()
        self.assertEqual(result["result_status"], "blocked")
        self.assertEqual(result["error_type"], "blocked_request")

    def test_needs_sql_false_returns_non_sql_response(self) -> None:
        result, sql_mock = self.run_with_fake_router(
            router_state(
                intent="explanation",
                needs_sql=False,
                execution_plan=["run_reporting_agent"],
            )
        )

        sql_mock.assert_not_called()
        self.assertEqual(result["result_status"], "no_sql_needed")
        self.assertEqual(result["final_sql"], "")

    def test_easy_router_classification_selects_easy_model(self) -> None:
        with patch.dict(orchestrator.GEMINI_TIER_MODELS, {"easy": "easy-model"}):
            _, sql_mock = self.run_with_fake_router(router_state(complexity_tier="easy"))

        called_config = sql_mock.call_args.kwargs["config"]
        self.assertEqual(called_config.primary_model, "easy-model")

    def test_medium_router_classification_selects_medium_model(self) -> None:
        with patch.dict(orchestrator.GEMINI_TIER_MODELS, {"medium": "medium-model"}):
            _, sql_mock = self.run_with_fake_router(router_state(complexity_tier="medium"))

        called_config = sql_mock.call_args.kwargs["config"]
        self.assertEqual(called_config.primary_model, "medium-model")

    def test_hard_router_classification_selects_configured_primary_model(self) -> None:
        _, sql_mock = self.run_with_fake_router(router_state(complexity_tier="hard"))

        called_config = sql_mock.call_args.kwargs["config"]
        self.assertEqual(called_config.primary_model, "hard-primary")

    def test_memory_intent_key_is_preserved_as_router_context_metadata(self) -> None:
        result, sql_mock = self.run_with_fake_router(
            router_state(memory_intent_key="ranking", intent="ranking")
        )

        self.assertEqual(result["memory_intent_key"], "ranking")
        self.assertNotIn("memory_intent_key", sql_mock.call_args.kwargs)
        self.assertEqual(sql_mock.call_args.kwargs["router_context"]["memory_intent_key"], "ranking")

    def test_chart_spec_is_added_after_successful_sql_when_router_requests_chart(self) -> None:
        result, _sql_mock = self.run_with_fake_router(
            router_state(output_mode="chart_plus_table"),
            sql_result(
                query_result={
                    "columns": ["region", "total_revenue"],
                    "rows": [("EUROPE", 10), ("ASIA", 8)],
                    "row_count": 2,
                },
                row_count=2,
            ),
        )

        chart_spec = result["chart_spec"]
        self.assertTrue(chart_spec["render_allowed"])
        self.assertEqual(chart_spec["chart_type"], "bar")
        self.assertEqual(chart_spec["x_axis"], "region")
        self.assertEqual(chart_spec["y_axis"], "total_revenue")
        self.assertEqual(chart_spec["category_order"], ["EUROPE", "ASIA"])
        self.assertIn("reporting_result", result)
        self.assertIn("Kurzantwort", result["reporting_result"]["summary"])
        self.assertEqual(result["reporting_result"]["audit"]["chart_order"], "sql_result_order")

    def test_chart_spec_is_non_renderable_when_router_requests_table_only(self) -> None:
        result, _sql_mock = self.run_with_fake_router(
            router_state(output_mode="table"),
            sql_result(
                query_result={
                    "columns": ["region", "total_revenue"],
                    "rows": [("EUROPE", 10), ("ASIA", 8)],
                    "row_count": 2,
                },
                row_count=2,
            ),
        )

        chart_spec = result["chart_spec"]
        self.assertFalse(chart_spec["render_allowed"])
        self.assertEqual(chart_spec["chart_type"], "none")

    def test_reporting_failure_preserves_successful_sql_result(self) -> None:
        sql_output = sql_result(
            final_sql="SELECT COUNT(*) AS order_count FROM orders",
            query_result={"columns": ["order_count"], "rows": [(42,)], "row_count": 1},
            row_count=1,
            final_answer="Die Antwort ist 42.",
        )
        sql_mock = Mock(return_value=sql_output)
        with patch("src.agent.orchestrator._get_compiled_router", return_value=FakeRouter(router_state())), patch(
            "src.agent.orchestrator.run_sql_agent",
            sql_mock,
        ), patch("src.agent.orchestrator.build_reporting_result", side_effect=RuntimeError("reporting boom")):
            result = orchestrator.run_orchestrator(
                "Wie viele Bestellungen gibt es?",
                config=test_config(),
                log_to_query_log=False,
            )

        self.assertEqual(result["final_sql"], "SELECT COUNT(*) AS order_count FROM orders")
        self.assertEqual(result["final_answer"], "Die Antwort ist 42.")
        self.assertTrue(result["execution_success"])
        self.assertFalse(result["chart_spec"]["render_allowed"])
        self.assertEqual(result["chart_spec"]["chart_type"], "none")
        self.assertEqual(result["reporting_result"]["summary"], "")
        self.assertEqual(result["reporting_result"]["kpi_cards"], [])
        self.assertTrue(result["reporting_result"]["audit"]["reporting_failed"])
        self.assertEqual(result["reporting_result"]["audit"]["reporting_error_type"], "RuntimeError")

    def test_reporting_failure_does_not_hide_sql_error_flow(self) -> None:
        sql_output = sql_result(
            generated_sql="SELECT broken",
            final_sql="",
            query_result={"columns": [], "rows": [], "row_count": 0},
            row_count=0,
            validation_success=False,
            execution_success=False,
            result_status="failed",
            final_answer="SQL failed.",
            sql_error="syntax error near broken",
            error_type="sql_validation",
        )
        sql_mock = Mock(return_value=sql_output)
        with patch("src.agent.orchestrator._get_compiled_router", return_value=FakeRouter(router_state())), patch(
            "src.agent.orchestrator.run_sql_agent",
            sql_mock,
        ), patch("src.agent.orchestrator.build_reporting_result", side_effect=RuntimeError("reporting boom")):
            result = orchestrator.run_orchestrator(
                "Wie viele Bestellungen gibt es?",
                config=test_config(),
                log_to_query_log=False,
            )

        self.assertFalse(result["execution_success"])
        self.assertFalse(result["validation_success"])
        self.assertEqual(result["sql_error"], "syntax error near broken")
        self.assertEqual(result["error_type"], "sql_validation")
        self.assertFalse(result["chart_spec"]["render_allowed"])
        self.assertTrue(result["reporting_result"]["audit"]["reporting_failed"])
        self.assertFalse(result["reporting_result"]["audit"]["sql_success"])

    def test_reporting_failure_preserves_terminal_response(self) -> None:
        with patch(
            "src.agent.orchestrator._get_compiled_router",
            return_value=FakeRouter(
                router_state(
                    needs_sql=False,
                    needs_clarification=True,
                    clarification_question="Welche Kennzahl meinst du?",
                )
            ),
        ), patch("src.agent.orchestrator.build_reporting_result", side_effect=RuntimeError("reporting boom")):
            result = orchestrator.run_orchestrator(
                "Berichte über alles.",
                config=test_config(),
                log_to_query_log=False,
            )

        self.assertEqual(result["result_status"], "clarification_needed")
        self.assertEqual(result["final_answer"], "Welche Kennzahl meinst du?")
        self.assertFalse(result["chart_spec"]["render_allowed"])
        self.assertTrue(result["reporting_result"]["audit"]["reporting_failed"])

    def test_router_logging_handles_empty_template_candidate_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sql_mock = Mock(return_value=sql_result())
            with patch("src.agent.orchestrator.get_log_dir", return_value=Path(temp_dir)), patch(
                "src.agent.orchestrator._get_compiled_router",
                return_value=FakeRouter(router_state()),
            ), patch("src.agent.orchestrator.run_sql_agent", sql_mock):
                result = orchestrator.run_orchestrator(
                    "Wie viele Bestellungen gibt es?",
                    config=test_config(),
                    log_to_query_log=True,
                )

            log_path = Path(temp_dir) / "router_log.csv"
            with log_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], result["run_id"])
        self.assertEqual(rows[0]["template_candidate_ids"], "")
        self.assertEqual(rows[0]["template_candidate_scores"], "")


if __name__ == "__main__":
    unittest.main()
