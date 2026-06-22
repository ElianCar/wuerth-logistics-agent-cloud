from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from src.agent.memory_index_builder import write_master_index
from src.agent.memory_vector_retriever import (
    preprocess_text,
    retrieve_memory_templates,
)


def template_data(**overrides: object) -> dict[str, object]:
    template: dict[str, object] = {
        "id": "revenue_by_shipping_point",
        "scenario": "wuerth_local",
        "status": "approved",
        "is_active": True,
        "title": "Revenue by shipping point",
        "intent": "revenue_by_dimension",
        "trigger_phrases": ["Umsatz pro Versandstelle", "Revenue by shipping point"],
        "searchable_summary": "Revenue grouped by shipping point and logistics location.",
        "searchable_terms": ["revenue", "shipping_point", "versandstelle"],
        "synonyms": {"umsatz": "revenue", "versandstelle": "shipping_point"},
        "required_tables": ["wuerth.invoices"],
        "required_columns": ["revenue", "shipping_point"],
        "business_rules": ["Use approved revenue columns only."],
        "sql_pattern": "Aggregate one metric by one dimension.",
        "do_not_use_when": ["Revenue is unsupported."],
        "validation_checks": ["SELECT only."],
        "source_question": "Umsatz pro Versandstelle",
        "source_sql": "",
        "approved_by": "manual_review",
        "approved_at": "2026-06-05T00:00:00",
        "version": 1,
    }
    template.update(overrides)
    return template


def write_template(memory_dir: Path, name: str, data: dict[str, object]) -> None:
    approved_dir = memory_dir / "approved"
    approved_dir.mkdir(parents=True, exist_ok=True)
    (approved_dir / name).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def add_retrieval_templates(memory_dir: Path) -> None:
    write_template(memory_dir, "revenue_by_shipping_point.yaml", template_data())
    write_template(
        memory_dir,
        "gross_profit_by_material.yaml",
        template_data(
            id="gross_profit_by_material",
            title="Gross profit by material",
            intent="gross_profit_by_material",
            trigger_phrases=["Rohertrag nach Artikel", "Gross profit by material"],
            searchable_summary="Gross profit grouped by material and article.",
            searchable_terms=["gross_profit", "material", "rohertrag", "artikel"],
            synonyms={"rohertrag": "gross_profit", "artikel": "material"},
            required_tables=["wuerth.invoices"],
            required_columns=["gross_profit", "material"],
            source_question="Rohertrag nach Artikel",
        ),
    )
    write_template(
        memory_dir,
        "freight_cost_by_customer.yaml",
        template_data(
            id="freight_cost_by_customer",
            title="Freight cost by customer",
            intent="freight_by_customer",
            trigger_phrases=["Frachtkosten pro Kunde", "Freight cost by customer"],
            searchable_summary="Freight costs grouped by customer.",
            searchable_terms=["freight", "customer", "fracht", "kunde"],
            synonyms={"frachtkosten": "freight", "kunde": "customer"},
            required_tables=["wuerth.shipments"],
            required_columns=["freight_costs", "customer"],
            source_question="Frachtkosten pro Kunde",
        ),
    )


def retrieval(memory_dir: Path, query: str, **kwargs: object) -> dict[str, object]:
    return retrieve_memory_templates(
        "wuerth_local",
        query,
        memory_dir=memory_dir,
        **kwargs,
    )["memory_retrieval"]


class MemoryPreprocessingTests(unittest.TestCase):
    def test_lowercases_removes_punctuation_and_normalizes_whitespace(self) -> None:
        self.assertEqual(preprocess_text("  Revenue,   by SHIPPING point!  "), "revenue shipping_point")

    def test_removes_german_stopwords(self) -> None:
        self.assertEqual(preprocess_text("Bitte zeige Umsatz pro Versandstelle"), "revenue shipping_point")

    def test_removes_english_stopwords(self) -> None:
        self.assertEqual(preprocess_text("Please show revenue by customer"), "revenue customer")

    def test_maps_umsatz_and_revenue_to_revenue(self) -> None:
        self.assertEqual(preprocess_text("Umsatz Revenue"), "revenue")

    def test_maps_versandstelle_and_shipping_point(self) -> None:
        self.assertEqual(preprocess_text("Versandstelle shipping point"), "shipping_point")

    def test_maps_rohertrag_to_gross_profit(self) -> None:
        self.assertEqual(preprocess_text("Rohertrag gross profit"), "gross_profit")

    def test_maps_frachtkosten_to_freight(self) -> None:
        self.assertEqual(preprocess_text("Frachtkosten freight cost"), "freight")

    def test_maps_artikel_to_material(self) -> None:
        self.assertEqual(preprocess_text("Artikel product material number"), "material")


class MemoryVectorRetrieverTests(unittest.TestCase):
    def build_index(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp = tempfile.TemporaryDirectory()
        memory_dir = Path(temp.name) / "wuerth_local"
        add_retrieval_templates(memory_dir)
        write_master_index("wuerth_local", memory_dir=memory_dir)
        return temp, memory_dir

    def test_german_revenue_by_shipping_point_retrieves_top_template(self) -> None:
        temp, memory_dir = self.build_index()
        with temp:
            result = retrieval(memory_dir, "Umsatz pro Versandstelle")

        self.assertEqual(result["candidates"][0]["template_id"], "revenue_by_shipping_point")
        self.assertIn("revenue", result["candidates"][0]["matched_terms"])
        self.assertIn("shipping_point", result["candidates"][0]["matched_terms"])

    def test_english_revenue_by_shipping_point_retrieves_top_template(self) -> None:
        temp, memory_dir = self.build_index()
        with temp:
            result = retrieval(memory_dir, "Revenue by shipping point")

        self.assertEqual(result["candidates"][0]["template_id"], "revenue_by_shipping_point")

    def test_german_gross_profit_by_material_retrieves_top_template(self) -> None:
        temp, memory_dir = self.build_index()
        with temp:
            result = retrieval(memory_dir, "Rohertrag nach Artikel")

        self.assertEqual(result["candidates"][0]["template_id"], "gross_profit_by_material")

    def test_english_gross_profit_by_material_retrieves_top_template(self) -> None:
        temp, memory_dir = self.build_index()
        with temp:
            result = retrieval(memory_dir, "Gross profit by material")

        self.assertEqual(result["candidates"][0]["template_id"], "gross_profit_by_material")

    def test_german_freight_cost_by_customer_retrieves_top_template(self) -> None:
        temp, memory_dir = self.build_index()
        with temp:
            result = retrieval(memory_dir, "Frachtkosten pro Kunde")

        self.assertEqual(result["candidates"][0]["template_id"], "freight_cost_by_customer")

    def test_english_freight_cost_by_customer_retrieves_top_template(self) -> None:
        temp, memory_dir = self.build_index()
        with temp:
            result = retrieval(memory_dir, "Freight cost by customer")

        self.assertEqual(result["candidates"][0]["template_id"], "freight_cost_by_customer")

    def test_unrelated_query_returns_no_candidates(self) -> None:
        temp, memory_dir = self.build_index()
        with temp:
            result = retrieval(memory_dir, "Tell me a joke")

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["no_match_reason"], "no_template_above_threshold")

    def test_low_score_threshold_returns_no_candidates(self) -> None:
        temp, memory_dir = self.build_index()
        with temp:
            result = retrieval(memory_dir, "Revenue by shipping point", min_score=0.99)

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["no_match_reason"], "no_template_above_threshold")

    def test_top_k_limits_number_of_candidates(self) -> None:
        temp, memory_dir = self.build_index()
        with temp:
            result = retrieval(
                memory_dir,
                "revenue customer material freight shipping point",
                top_k=2,
                min_score=0.01,
            )

        self.assertEqual(len(result["candidates"]), 2)

    def test_ambiguity_flag_is_true_when_top_scores_are_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(memory_dir, "a.yaml", template_data(id="a", title="Revenue by customer"))
            write_template(memory_dir, "b.yaml", template_data(id="b", title="Revenue by region"))
            write_master_index("wuerth_local", memory_dir=memory_dir)

            result = retrieval(memory_dir, "revenue shipping point", min_score=0.01)

        self.assertTrue(result["ambiguous"])
        self.assertEqual(len(result["candidates"]), 2)

    def test_wrong_scenario_templates_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(memory_dir, "wrong.yaml", template_data(id="wrong", scenario="demo"))
            write_master_index("wuerth_local", memory_dir=memory_dir)

            result = retrieval(memory_dir, "Revenue by shipping point")

        self.assertFalse(result["enabled"])
        self.assertEqual(result["candidates"], [])

    def test_inactive_and_pending_templates_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(memory_dir, "inactive.yaml", template_data(id="inactive", is_active=False))
            write_template(memory_dir, "pending.yaml", template_data(id="pending", status="pending_review"))
            write_master_index("wuerth_local", memory_dir=memory_dir)

            result = retrieval(memory_dir, "Revenue by shipping point")

        self.assertFalse(result["enabled"])
        self.assertEqual(result["no_match_reason"], "master_index_missing_or_empty")

    def test_missing_master_index_returns_disabled_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"

            result = retrieval(memory_dir, "Umsatz pro Versandstelle")

        self.assertFalse(result["enabled"])
        self.assertEqual(result["query_preprocessed"], "revenue shipping_point")
        self.assertEqual(result["no_match_reason"], "master_index_missing_or_empty")

    def test_retriever_filters_unsafe_index_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            memory_dir.mkdir(parents=True)
            index = {
                "schema_version": 1,
                "scenario": "wuerth_local",
                "generated_at": "2026-06-05T00:00:00Z",
                "template_count": 1,
                "templates": [
                    {
                        "id": "unsafe",
                        "path": "../demo/approved/unsafe.yaml",
                        "status": "approved",
                        "is_active": True,
                        "scenario": "wuerth_local",
                        "intent": "revenue",
                        "title": "Revenue",
                        "searchable_text": "revenue shipping_point",
                        "tables": ["wuerth.invoices"],
                        "columns": ["revenue"],
                        "tags": ["revenue"],
                        "checksum": "sha256:test",
                        "version": 1,
                    }
                ],
            }
            (memory_dir / "master_index.yaml").write_text(
                yaml.safe_dump(index, sort_keys=False),
                encoding="utf-8",
            )

            result = retrieval(memory_dir, "Revenue by shipping point")

        self.assertFalse(result["enabled"])
        self.assertEqual(result["candidates"], [])

    def test_explicit_index_path_requires_fixture_memory_dir_when_outside_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outside_index = Path(temp_dir) / "master_index.yaml"
            outside_index.write_text(
                yaml.safe_dump({"schema_version": 1, "scenario": "wuerth_local", "templates": []}),
                encoding="utf-8",
            )

            result = retrieve_memory_templates(
                "wuerth_local",
                "Revenue by shipping point",
                index_path=outside_index,
            )["memory_retrieval"]

        self.assertFalse(result["enabled"])
        self.assertEqual(result["no_match_reason"], "index_path_outside_scenario_memory_dir")


if __name__ == "__main__":
    unittest.main()
