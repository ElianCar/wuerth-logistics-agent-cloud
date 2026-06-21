from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from src.agent.langgraph_sql_agent import (
    SQLAgentConfig,
    build_sql_prompt,
    format_memory_guidance_from_retrieval,
    run_sql_agent,
)
from src.agent.sql_validator import validate_generated_sql
from src.config.scenarios import SCENARIOS, reset_active_scenario_id, set_active_scenario_id


def template_data(
    *,
    scenario: str,
    template_id: str,
    title: str,
    intent: str,
    tables: list[str],
    columns: list[str],
    status: str = "approved",
    is_active: bool = True,
    source_sql: str = "",
) -> dict[str, object]:
    return {
        "id": template_id,
        "scenario": scenario,
        "status": status,
        "is_active": is_active,
        "title": title,
        "intent": intent,
        "trigger_phrases": [title],
        "searchable_summary": f"{title} searchable summary.",
        "searchable_terms": title.lower().split(),
        "synonyms": {},
        "required_tables": tables,
        "required_columns": columns,
        "business_rules": ["Use the verified metric definition."],
        "sql_pattern": "Aggregate the metric by the requested dimension.",
        "do_not_use_when": ["The requested metric or dimension differs."],
        "validation_checks": ["SQL must be read-only SELECT.", "Use only known schema columns."],
        "source_question": title,
        "source_sql": source_sql,
        "approved_by": "test",
        "approved_at": "2026-06-05T00:00:00",
        "version": 1,
    }


def write_template(memory_dir: Path, name: str, data: dict[str, object]) -> Path:
    approved_dir = memory_dir / "approved"
    approved_dir.mkdir(parents=True, exist_ok=True)
    path = approved_dir / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def retrieval_for(scenario: str, query: str, candidates: list[dict[str, object]], ambiguous: bool = False) -> dict[str, object]:
    return {
        "enabled": True,
        "method": "tfidf_vector_space",
        "scenario": scenario,
        "query_original": query,
        "query_preprocessed": query.lower(),
        "candidates": candidates,
        "no_match_reason": "",
        "ambiguous": ambiguous,
    }


def demo_schema_context() -> str:
    return """Scenario: demo
Dataset ID: demo_tpch
Backend: postgres
SQL dialect: PostgreSQL

PostgreSQL schema:
Table: customer
  - c_custkey: integer
  - c_name: text
Table: orders
  - o_orderkey: integer
  - o_custkey: integer
Table: lineitem
  - l_orderkey: integer
  - l_extendedprice: numeric
  - l_discount: numeric
"""


class SQLAgentMemoryGuidanceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_active_scenario_id()

    def tearDown(self) -> None:
        reset_active_scenario_id()

    def test_prompt_includes_demo_memory_guidance_when_candidates_are_provided(self) -> None:
        set_active_scenario_id("demo")
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            path = write_template(
                memory_dir,
                "revenue_by_customer.yaml",
                template_data(
                    scenario="demo",
                    template_id="demo_revenue_by_customer",
                    title="Revenue by customer",
                    intent="revenue_by_customer",
                    tables=["customer", "orders", "lineitem"],
                    columns=["l_extendedprice", "l_discount", "c_custkey"],
                    source_sql="SELECT c_custkey FROM customer",
                ),
            )
            memory_retrieval = retrieval_for(
                "demo",
                "Revenue by customer",
                [{"template_id": "demo_revenue_by_customer", "path": str(path), "matched_terms": ["revenue", "customer"]}],
            )
            original = SCENARIOS["demo"]
            SCENARIOS["demo"] = replace(original, memory_dir=memory_dir)
            try:
                prompt = build_sql_prompt(
                    {
                        "user_question": "Revenue by customer",
                        "schema_context": demo_schema_context(),
                        "use_approved_memory": True,
                        "memory_retrieval": memory_retrieval,
                    }
                )
            finally:
                SCENARIOS["demo"] = original

        self.assertIn("Approved memory template guidance (context only):", prompt)
        self.assertIn("template_id: demo_revenue_by_customer", prompt)
        self.assertIn("Approved memory templates are guidance only", prompt)
        self.assertIn("Final SQL must still pass SQL validation", prompt)
        self.assertIn("Do not copy source_sql blindly", prompt)

    def test_prompt_includes_wuerth_memory_guidance_when_candidates_are_provided(self) -> None:
        set_active_scenario_id("wuerth_local")
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            path = write_template(
                memory_dir,
                "freight_cost_by_customer.yaml",
                template_data(
                    scenario="wuerth_local",
                    template_id="freight_cost_by_customer",
                    title="Freight cost by customer",
                    intent="freight_cost_by_customer",
                    tables=["wuerth.shipments"],
                    columns=["freight_costs", "shiptoparty"],
                ),
            )
            memory_retrieval = retrieval_for(
                "wuerth_local",
                "Frachtkosten pro Kunde",
                [{"template_id": "freight_cost_by_customer", "path": str(path), "matched_terms": ["freight", "customer"]}],
            )
            original = SCENARIOS["wuerth_local"]
            SCENARIOS["wuerth_local"] = replace(original, memory_dir=memory_dir)
            try:
                guidance = format_memory_guidance_from_retrieval(memory_retrieval)
            finally:
                SCENARIOS["wuerth_local"] = original

        self.assertIn("template_id: freight_cost_by_customer", guidance)
        self.assertIn("Freight cost by customer", guidance)

    def test_prompt_does_not_include_memory_guidance_when_candidates_are_empty(self) -> None:
        set_active_scenario_id("demo")
        prompt = build_sql_prompt(
            {
                "user_question": "Revenue by customer",
                "schema_context": demo_schema_context(),
                "use_approved_memory": True,
                "memory_retrieval": retrieval_for("demo", "Revenue by customer", []),
            }
        )

        self.assertNotIn("Approved memory template guidance", prompt)

    def test_max_three_templates_are_included_and_ambiguous_is_represented(self) -> None:
        set_active_scenario_id("demo")
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            candidates = []
            for index in range(4):
                template_id = f"demo_template_{index}"
                path = write_template(
                    memory_dir,
                    f"{template_id}.yaml",
                    template_data(
                        scenario="demo",
                        template_id=template_id,
                        title=f"Revenue by customer {index}",
                        intent="revenue_by_customer",
                        tables=["customer"],
                        columns=["c_custkey"],
                    ),
                )
                candidates.append({"template_id": template_id, "path": str(path), "matched_terms": ["revenue"]})

            guidance = format_memory_guidance_from_retrieval(
                retrieval_for("demo", "Revenue by customer", candidates, ambiguous=True),
                memory_dir=memory_dir,
            )

        self.assertEqual(guidance.count("Template "), 3)
        self.assertIn("Ambiguity warning", guidance)
        self.assertNotIn("demo_template_3", guidance)

    def test_wrong_scenario_inactive_and_invalid_path_templates_are_ignored(self) -> None:
        set_active_scenario_id("demo")
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            wrong_path = write_template(
                memory_dir,
                "wrong.yaml",
                template_data(
                    scenario="wuerth_local",
                    template_id="wrong",
                    title="Wrong scenario",
                    intent="wrong",
                    tables=["wuerth.shipments"],
                    columns=["freight_costs"],
                ),
            )
            inactive_path = write_template(
                memory_dir,
                "inactive.yaml",
                template_data(
                    scenario="demo",
                    template_id="inactive",
                    title="Inactive",
                    intent="inactive",
                    tables=["customer"],
                    columns=["c_custkey"],
                    is_active=False,
                ),
            )
            outside_path = Path(temp_dir) / "outside.yaml"
            outside_path.write_text(
                yaml.safe_dump(
                    template_data(
                        scenario="demo",
                        template_id="outside",
                        title="Outside",
                        intent="outside",
                        tables=["customer"],
                        columns=["c_custkey"],
                    )
                ),
                encoding="utf-8",
            )
            memory_retrieval = retrieval_for(
                "demo",
                "Revenue by customer",
                [
                    {"template_id": "wrong", "path": str(wrong_path), "matched_terms": ["revenue"]},
                    {"template_id": "inactive", "path": str(inactive_path), "matched_terms": ["revenue"]},
                    {"template_id": "outside", "path": str(outside_path), "matched_terms": ["revenue"]},
                ],
            )

            guidance = format_memory_guidance_from_retrieval(memory_retrieval, memory_dir=memory_dir)

        self.assertEqual(guidance, "")

    def test_router_memory_skips_old_internal_retrieval_and_creates_one_guidance_block(self) -> None:
        set_active_scenario_id("demo")
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            path = write_template(
                memory_dir,
                "revenue_by_customer.yaml",
                template_data(
                    scenario="demo",
                    template_id="demo_revenue_by_customer",
                    title="Revenue by customer",
                    intent="revenue_by_customer",
                    tables=["customer"],
                    columns=["c_custkey"],
                ),
            )
            memory_retrieval = retrieval_for(
                "demo",
                "Revenue by customer",
                [{"template_id": "demo_revenue_by_customer", "path": str(path), "matched_terms": ["revenue"]}],
            )
            original = SCENARIOS["demo"]
            SCENARIOS["demo"] = replace(original, memory_dir=memory_dir)
            try:
                with patch("src.agent.langgraph_sql_agent.format_approved_template_context") as old_retrieval:
                    prompt = build_sql_prompt(
                        {
                            "user_question": "Revenue by customer",
                            "schema_context": demo_schema_context(),
                            "use_approved_memory": True,
                            "memory_retrieval": memory_retrieval,
                        }
                    )
            finally:
                SCENARIOS["demo"] = original

        old_retrieval.assert_not_called()
        self.assertEqual(prompt.count("Approved memory template guidance (context only):"), 1)
        self.assertNotIn("Approved reusable solution templates", prompt)

    def test_direct_prompt_does_not_load_legacy_memory_by_default(self) -> None:
        set_active_scenario_id("demo")

        with patch("src.agent.langgraph_sql_agent.format_approved_template_context") as old_retrieval:
            prompt = build_sql_prompt(
                {
                    "user_question": "Revenue by customer",
                    "schema_context": demo_schema_context(),
                    "use_approved_memory": True,
                }
            )

        old_retrieval.assert_not_called()
        self.assertNotIn("Approved memory template guidance", prompt)
        self.assertNotIn("Approved reusable solution templates", prompt)

    def test_legacy_memory_requires_explicit_opt_in(self) -> None:
        set_active_scenario_id("demo")

        with patch(
            "src.agent.langgraph_sql_agent.format_approved_template_context",
            return_value="\nLEGACY TEMPLATE GUIDANCE\n",
        ) as old_retrieval:
            prompt = build_sql_prompt(
                {
                    "user_question": "Revenue by customer",
                    "schema_context": demo_schema_context(),
                    "use_approved_memory": True,
                    "use_legacy_memory": True,
                }
            )

        old_retrieval.assert_called_once_with("Revenue by customer")
        self.assertIn("LEGACY TEMPLATE GUIDANCE", prompt)

    def test_router_memory_wins_even_when_legacy_opt_in_is_true(self) -> None:
        set_active_scenario_id("demo")
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            path = write_template(
                memory_dir,
                "revenue_by_customer.yaml",
                template_data(
                    scenario="demo",
                    template_id="demo_revenue_by_customer",
                    title="Revenue by customer",
                    intent="revenue_by_customer",
                    tables=["customer"],
                    columns=["c_custkey"],
                ),
            )
            memory_retrieval = retrieval_for(
                "demo",
                "Revenue by customer",
                [{"template_id": "demo_revenue_by_customer", "path": str(path), "matched_terms": ["revenue"]}],
            )
            original = SCENARIOS["demo"]
            SCENARIOS["demo"] = replace(original, memory_dir=memory_dir)
            try:
                with patch("src.agent.langgraph_sql_agent.format_approved_template_context") as old_retrieval:
                    prompt = build_sql_prompt(
                        {
                            "user_question": "Revenue by customer",
                            "schema_context": demo_schema_context(),
                            "use_approved_memory": True,
                            "use_legacy_memory": True,
                            "memory_retrieval": memory_retrieval,
                        }
                    )
            finally:
                SCENARIOS["demo"] = original

        old_retrieval.assert_not_called()
        self.assertEqual(prompt.count("Approved memory template guidance (context only):"), 1)
        self.assertNotIn("Approved reusable solution templates", prompt)

    def test_direct_run_sql_agent_does_not_load_legacy_memory_by_default(self) -> None:
        set_active_scenario_id("demo")
        captured_prompt: dict[str, str] = {}

        def fake_sql_generator(prompt: str, _model: str, _ollama_host: str, _node_name: str) -> str:
            captured_prompt["prompt"] = prompt
            return "SELECT COUNT(*) FROM customer"

        def fake_sql_executor(sql: str, _question: str) -> dict[str, object]:
            return {
                "columns": ["count"],
                "rows": [(1,)],
                "row_count": 1,
                "executed_sql": sql,
            }

        config = SQLAgentConfig(
            primary_model="test-primary",
            fallback_model="test-fallback",
            max_primary_attempts=1,
            llm_provider="gemini",
            ollama_host="http://localhost:11434",
        )

        with patch(
            "src.agent.langgraph_sql_agent.format_approved_template_context",
            side_effect=AssertionError("legacy retrieval must not run by default"),
        ) as old_retrieval:
            result = run_sql_agent(
                "Revenue by customer",
                config=config,
                schema_loader=demo_schema_context,
                sql_generator=fake_sql_generator,
                sql_executor=fake_sql_executor,
                log_to_query_log=False,
            )

        old_retrieval.assert_not_called()
        self.assertTrue(result["validation_success"], result.get("sql_error", ""))
        self.assertNotIn("Approved reusable solution templates", captured_prompt["prompt"])

    def test_sql_validation_still_blocks_destructive_sql_and_disallowed_tables(self) -> None:
        schema_context = demo_schema_context()

        destructive = validate_generated_sql("DROP TABLE customer", schema_context)
        disallowed = validate_generated_sql("SELECT COUNT(*) FROM wuerth.shipments", schema_context)

        self.assertFalse(destructive.is_valid)
        self.assertFalse(disallowed.is_valid)


if __name__ == "__main__":
    unittest.main()
