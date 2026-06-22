from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from src.agent.memory_index_builder import build_master_index, write_master_index
from src.agent.memory_template_schema import load_and_validate_template
from src.agent.memory_vector_retriever import retrieve_memory_templates


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WUERTH_MEMORY_DIR = PROJECT_ROOT / "memory" / "wuerth_local"
WUERTH_INDEX_PATH = WUERTH_MEMORY_DIR / "master_index.yaml"

EXPECTED_TEMPLATE_IDS = {
    "shipment_delivery_count_by_customer",
    "delivered_quantity_by_customer",
    "freight_cost_by_customer",
    "shipment_delivery_count_by_delivery_type",
    "delivered_quantity_by_delivery_type",
    "invoice_order_count_by_customer",
    "invoice_order_count_by_market_segment",
    "invoice_records_without_matching_shipments",
    "shipment_records_without_matching_invoices",
}


def wuerth_retrieval(query: str, **kwargs: object) -> dict[str, object]:
    return retrieve_memory_templates(
        "wuerth_local",
        query,
        memory_dir=WUERTH_MEMORY_DIR,
        **kwargs,
    )["memory_retrieval"]


class WuerthMemoryRetrievalQualityTests(unittest.TestCase):
    def test_production_wuerth_templates_are_schema_valid(self) -> None:
        template_paths = sorted((WUERTH_MEMORY_DIR / "approved").glob("*.yaml"))

        self.assertEqual({path.stem for path in template_paths}, EXPECTED_TEMPLATE_IDS)
        for path in template_paths:
            result = load_and_validate_template(path, expected_scenario="wuerth_local")
            self.assertTrue(result.is_valid, f"{path.name}: {result.errors}")

    def test_generated_wuerth_index_contains_expected_templates(self) -> None:
        index = yaml.safe_load(WUERTH_INDEX_PATH.read_text(encoding="utf-8"))
        template_ids = {record["id"] for record in index["templates"]}

        self.assertEqual(index["scenario"], "wuerth_local")
        self.assertEqual(index["template_count"], 9)
        self.assertEqual(template_ids, EXPECTED_TEMPLATE_IDS)
        for record in index["templates"]:
            self.assertEqual(record["status"], "approved")
            self.assertIs(record["is_active"], True)
            self.assertTrue(record["path"].startswith("memory/wuerth_local/approved/"))
            self.assertTrue(record["checksum"].startswith("sha256:"))
            self.assertTrue(record["searchable_text"].strip())

    def test_builder_regenerates_same_template_ids_from_approved_files(self) -> None:
        index = build_master_index("wuerth_local", memory_dir=WUERTH_MEMORY_DIR)

        self.assertEqual(index["template_count"], 9)
        self.assertEqual({record["id"] for record in index["templates"]}, EXPECTED_TEMPLATE_IDS)

    def assert_top_template(
        self,
        query: str,
        expected_template_id: str,
        expected_terms: set[str],
    ) -> None:
        result = wuerth_retrieval(query)

        self.assertTrue(result["enabled"])
        self.assertEqual(result["no_match_reason"], "")
        self.assertGreaterEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["template_id"], expected_template_id, query)
        self.assertGreaterEqual(candidate["score"], 0.20, query)
        self.assertTrue(expected_terms <= set(candidate["matched_terms"]), query)

    def test_shipment_count_by_customer_german_and_english(self) -> None:
        self.assert_top_template(
            "Lieferungen pro Kunde",
            "shipment_delivery_count_by_customer",
            {"delivery_count", "customer"},
        )
        self.assert_top_template(
            "Shipments by customer",
            "shipment_delivery_count_by_customer",
            {"delivery_count", "customer"},
        )

    def test_freight_cost_by_customer_german_and_english(self) -> None:
        self.assert_top_template(
            "Frachtkosten pro Kunde",
            "freight_cost_by_customer",
            {"freight", "customer"},
        )
        self.assert_top_template(
            "Freight cost by customer",
            "freight_cost_by_customer",
            {"freight", "customer"},
        )

    def test_delivered_quantity_by_customer_german_and_english(self) -> None:
        self.assert_top_template(
            "Gelieferte Menge pro Kunde",
            "delivered_quantity_by_customer",
            {"delivered_quantity", "customer"},
        )
        self.assert_top_template(
            "Delivered quantity by customer",
            "delivered_quantity_by_customer",
            {"delivered_quantity", "customer"},
        )

    def test_shipment_count_by_delivery_type_german_and_english(self) -> None:
        self.assert_top_template(
            "Lieferungen nach Lieferart",
            "shipment_delivery_count_by_delivery_type",
            {"delivery_count", "delivery_type"},
        )
        self.assert_top_template(
            "Shipments by delivery type",
            "shipment_delivery_count_by_delivery_type",
            {"delivery_count", "delivery_type"},
        )

    def test_invoice_order_count_by_customer_german_and_english(self) -> None:
        self.assert_top_template(
            "Aufträge pro Kunde",
            "invoice_order_count_by_customer",
            {"order", "customer"},
        )
        self.assert_top_template(
            "Invoice orders by customer",
            "invoice_order_count_by_customer",
            {"invoice", "order", "customer"},
        )

    def test_invoice_order_count_by_market_segment_german_and_english(self) -> None:
        self.assert_top_template(
            "Aufträge nach Marktsegment",
            "invoice_order_count_by_market_segment",
            {"order", "market_segment"},
        )
        self.assert_top_template(
            "Invoice orders by market segment",
            "invoice_order_count_by_market_segment",
            {"invoice", "order", "market_segment"},
        )

    def test_unmatched_invoice_and_shipment_patterns_are_directional(self) -> None:
        self.assert_top_template(
            "Rechnungen ohne passende Lieferungen",
            "invoice_records_without_matching_shipments",
            {"invoice_without_shipment"},
        )
        self.assert_top_template(
            "Invoices without shipments",
            "invoice_records_without_matching_shipments",
            {"invoice_without_shipment"},
        )
        self.assert_top_template(
            "Lieferungen ohne passende Rechnungen",
            "shipment_records_without_matching_invoices",
            {"shipment_without_invoice"},
        )
        self.assert_top_template(
            "Shipments without invoices",
            "shipment_records_without_matching_invoices",
            {"shipment_without_invoice"},
        )

    def test_broader_wuerth_questions_keep_expected_template_in_top_three(self) -> None:
        cases = [
            ("Top customers by freight cost", "freight_cost_by_customer"),
            ("Welche Kunden haben die meisten Lieferungen?", "shipment_delivery_count_by_customer"),
            ("Welche Lieferart hat die höchste Liefermenge?", "delivered_quantity_by_delivery_type"),
        ]
        for query, expected_template_id in cases:
            result = wuerth_retrieval(query)
            self.assertIn(
                expected_template_id,
                [candidate["template_id"] for candidate in result["candidates"]],
                query,
            )

    def test_unavailable_or_deferred_kpis_return_no_candidates(self) -> None:
        unsupported_queries = [
            "Umsatz pro Kunde",
            "Revenue by customer",
            "Top customers by revenue",
            "Umsatz pro Artikel",
            "Revenue by material",
            "Sales by material number",
            "Umsatz über Zeit",
            "Revenue trend by date",
            "Lieferungen pro Tag",
            "Shipments per day",
            "Verpackungskosten pro Kunde",
            "Packing cost by customer",
            "Rohertrag nach Artikel",
            "Gross profit by material",
        ]

        for query in unsupported_queries:
            result = wuerth_retrieval(query)
            self.assertEqual(result["candidates"], [], query)
            self.assertIn(
                result["no_match_reason"],
                {"no_template_above_threshold", "unsafe_or_non_analytical_query"},
                query,
            )

    def test_unrelated_and_destructive_queries_return_no_candidates(self) -> None:
        negative_queries = [
            "Tell me a joke",
            "What is the weather?",
            "Delete all invoices",
            "Create a shipment",
            "Explain Python decorators",
        ]

        for query in negative_queries:
            result = wuerth_retrieval(query)
            self.assertEqual(result["candidates"], [], query)

    def test_wrong_scenario_records_do_not_appear_in_wuerth_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            approved_dir = memory_dir / "approved"
            approved_dir.mkdir(parents=True)
            source_template = yaml.safe_load(
                (WUERTH_MEMORY_DIR / "approved" / "freight_cost_by_customer.yaml").read_text(
                    encoding="utf-8"
                )
            )
            demo_template = dict(source_template, id="demo_freight", scenario="demo")
            databricks_template = dict(source_template, id="databricks_freight", scenario="databricks")
            good_template = dict(source_template, id="wuerth_freight")
            for name, template in [
                ("demo.yaml", demo_template),
                ("databricks.yaml", databricks_template),
                ("wuerth.yaml", good_template),
            ]:
                (approved_dir / name).write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")

            index = write_master_index("wuerth_local", memory_dir=memory_dir)
            result = retrieve_memory_templates(
                "wuerth_local",
                "Freight cost by customer",
                memory_dir=memory_dir,
            )["memory_retrieval"]

        self.assertEqual(index["template_count"], 1)
        self.assertEqual(result["candidates"][0]["template_id"], "wuerth_freight")

    def test_wuerth_index_does_not_retrieve_for_demo_scenario(self) -> None:
        result = retrieve_memory_templates(
            "demo",
            "Freight cost by customer",
            memory_dir=WUERTH_MEMORY_DIR,
            index_path=WUERTH_INDEX_PATH,
        )["memory_retrieval"]

        self.assertFalse(result["enabled"])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["no_match_reason"], "index_scenario_mismatch")

    def test_template_path_containment_blocks_outside_index_records(self) -> None:
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
                        "id": "outside",
                        "path": "../demo/approved/outside.yaml",
                        "status": "approved",
                        "is_active": True,
                        "scenario": "wuerth_local",
                        "intent": "freight_cost_by_customer",
                        "title": "Freight cost by customer",
                        "searchable_text": "freight customer",
                        "tables": ["wuerth.shipments"],
                        "columns": ["freight_costs", "shiptoparty"],
                        "tags": ["freight", "customer"],
                        "checksum": "sha256:test",
                        "version": 1,
                    }
                ],
            }
            (memory_dir / "master_index.yaml").write_text(
                yaml.safe_dump(index, sort_keys=False),
                encoding="utf-8",
            )

            result = retrieve_memory_templates(
                "wuerth_local",
                "Freight cost by customer",
                memory_dir=memory_dir,
            )["memory_retrieval"]

        self.assertFalse(result["enabled"])
        self.assertEqual(result["candidates"], [])


if __name__ == "__main__":
    unittest.main()
