from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from src.agent.memory_index_builder import write_master_index
from src.agent.router_template_retriever import retrieve_memory_for_router


def template_data(
    *,
    scenario: str,
    template_id: str,
    title: str,
    intent: str,
    terms: list[str],
    tables: list[str],
    columns: list[str],
    status: str = "approved",
    is_active: bool = True,
) -> dict[str, object]:
    return {
        "id": template_id,
        "scenario": scenario,
        "status": status,
        "is_active": is_active,
        "title": title,
        "intent": intent,
        "trigger_phrases": [title],
        "searchable_summary": f"{title} reusable query pattern.",
        "searchable_terms": terms,
        "synonyms": {},
        "required_tables": tables,
        "required_columns": columns,
        "business_rules": ["Use verified tables and columns only."],
        "sql_pattern": "Aggregate one metric by one dimension.",
        "do_not_use_when": ["The current question asks for a different metric."],
        "validation_checks": ["SQL must be read-only SELECT."],
        "source_question": title,
        "source_sql": "",
        "approved_by": "test",
        "approved_at": "2026-06-05T00:00:00",
        "version": 1,
    }


def write_template(memory_dir: Path, name: str, data: dict[str, object]) -> None:
    approved_dir = memory_dir / "approved"
    approved_dir.mkdir(parents=True, exist_ok=True)
    (approved_dir / name).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def enabled_retrieval(scenario: str, query: str, memory_dir: Path) -> dict[str, object]:
    with patch.dict(os.environ, {"MEMORY_RETRIEVAL_ENABLED": "true"}, clear=False):
        return retrieve_memory_for_router(
            query,
            scenario=scenario,
            memory_dir=memory_dir,
        )


class RouterTemplateRetrieverTests(unittest.TestCase):
    def test_disabled_memory_returns_enabled_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {}, clear=True):
            result = retrieve_memory_for_router(
                "Revenue by customer",
                scenario="demo",
                memory_dir=Path(temp_dir) / "demo",
            )

        self.assertFalse(result["enabled"])
        self.assertEqual(result["method"], "tfidf_vector_space")
        self.assertEqual(result["scenario"], "demo")
        self.assertEqual(result["query_preprocessed"], "")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["no_match_reason"], "memory_retrieval_disabled")
        self.assertFalse(result["ambiguous"])

    def test_missing_demo_index_degrades_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = enabled_retrieval("demo", "Revenue by customer", Path(temp_dir) / "demo")

        self.assertTrue(result["enabled"])
        self.assertEqual(result["scenario"], "demo")
        self.assertEqual(result["query_preprocessed"], "revenue customer")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["no_match_reason"], "master_index_missing_or_empty")

    def test_missing_wuerth_index_degrades_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = enabled_retrieval("wuerth_local", "Umsatz pro Kunde", Path(temp_dir) / "wuerth_local")

        self.assertTrue(result["enabled"])
        self.assertEqual(result["scenario"], "wuerth_local")
        self.assertEqual(result["query_preprocessed"], "revenue customer")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["no_match_reason"], "master_index_missing_or_empty")

    def test_empty_demo_index_returns_no_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            write_master_index("demo", memory_dir=memory_dir)
            result = enabled_retrieval("demo", "Revenue by customer", memory_dir)

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["no_match_reason"], "master_index_missing_or_empty")

    def test_empty_wuerth_index_returns_no_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_master_index("wuerth_local", memory_dir=memory_dir)
            result = enabled_retrieval("wuerth_local", "Frachtkosten pro Kunde", memory_dir)

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["no_match_reason"], "master_index_missing_or_empty")

    def test_valid_demo_fixture_index_returns_demo_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            write_template(
                memory_dir,
                "revenue_by_customer.yaml",
                template_data(
                    scenario="demo",
                    template_id="demo_revenue_by_customer",
                    title="Revenue by customer",
                    intent="revenue_by_customer",
                    terms=["revenue", "customer"],
                    tables=["customer", "orders", "lineitem"],
                    columns=["c_custkey", "o_orderkey", "l_extendedprice", "l_discount"],
                ),
            )
            write_master_index("demo", memory_dir=memory_dir)
            result = enabled_retrieval("demo", "Revenue by customer", memory_dir)

        self.assertEqual(result["candidates"][0]["template_id"], "demo_revenue_by_customer")
        self.assertIn("revenue", result["candidates"][0]["matched_terms"])

    def test_valid_wuerth_fixture_index_returns_wuerth_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(
                memory_dir,
                "freight_cost_by_customer.yaml",
                template_data(
                    scenario="wuerth_local",
                    template_id="wuerth_freight_by_customer",
                    title="Freight cost by customer",
                    intent="freight_cost_by_customer",
                    terms=["freight", "customer", "fracht", "kunde"],
                    tables=["wuerth.shipments"],
                    columns=["freight_costs", "shiptoparty"],
                ),
            )
            write_master_index("wuerth_local", memory_dir=memory_dir)
            result = enabled_retrieval("wuerth_local", "Frachtkosten pro Kunde", memory_dir)

        self.assertEqual(result["candidates"][0]["template_id"], "wuerth_freight_by_customer")
        self.assertIn("freight", result["candidates"][0]["matched_terms"])

    def test_demo_retrieval_does_not_return_wuerth_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            write_template(
                memory_dir,
                "wrong.yaml",
                template_data(
                    scenario="wuerth_local",
                    template_id="wrong_wuerth",
                    title="Freight cost by customer",
                    intent="freight_cost_by_customer",
                    terms=["freight", "customer"],
                    tables=["wuerth.shipments"],
                    columns=["freight_costs"],
                ),
            )
            write_master_index("demo", memory_dir=memory_dir)
            result = enabled_retrieval("demo", "Freight cost by customer", memory_dir)

        self.assertEqual(result["candidates"], [])

    def test_wuerth_retrieval_does_not_return_demo_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(
                memory_dir,
                "wrong.yaml",
                template_data(
                    scenario="demo",
                    template_id="wrong_demo",
                    title="Revenue by customer",
                    intent="revenue_by_customer",
                    terms=["revenue", "customer"],
                    tables=["customer", "orders", "lineitem"],
                    columns=["l_extendedprice"],
                ),
            )
            write_master_index("wuerth_local", memory_dir=memory_dir)
            result = enabled_retrieval("wuerth_local", "Revenue by customer", memory_dir)

        self.assertEqual(result["candidates"], [])

    def test_inactive_pending_and_wrong_scenario_templates_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            base = template_data(
                scenario="demo",
                template_id="base",
                title="Revenue by customer",
                intent="revenue_by_customer",
                terms=["revenue", "customer"],
                tables=["customer"],
                columns=["c_custkey"],
            )
            write_template(memory_dir, "inactive.yaml", dict(base, id="inactive", is_active=False))
            write_template(memory_dir, "pending.yaml", dict(base, id="pending", status="pending_review"))
            write_template(memory_dir, "wrong.yaml", dict(base, id="wrong", scenario="wuerth_local"))
            write_master_index("demo", memory_dir=memory_dir)
            result = enabled_retrieval("demo", "Revenue by customer", memory_dir)

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["no_match_reason"], "master_index_missing_or_empty")

    def test_unrelated_query_returns_no_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            write_template(
                memory_dir,
                "revenue_by_customer.yaml",
                template_data(
                    scenario="demo",
                    template_id="demo_revenue_by_customer",
                    title="Revenue by customer",
                    intent="revenue_by_customer",
                    terms=["revenue", "customer"],
                    tables=["customer"],
                    columns=["c_custkey"],
                ),
            )
            write_master_index("demo", memory_dir=memory_dir)
            result = enabled_retrieval("demo", "Tell me a joke", memory_dir)

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["no_match_reason"], "no_template_above_threshold")


if __name__ == "__main__":
    unittest.main()
