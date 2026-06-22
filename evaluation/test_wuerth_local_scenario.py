from __future__ import annotations

import csv
import unittest
from pathlib import Path

import yaml

from src.agent.sql_validator import validate_generated_sql
from src.config.scenarios import (
    SCENARIOS,
    get_scenario_options,
    load_semantic_layer_text,
    reset_active_scenario_id,
    set_active_scenario_id,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WUERTH_CSV_DIR = PROJECT_ROOT / "database" / "exports" / "Wuerth"
WUERTH_SCHEMA_CONTEXT = """Scenario: wuerth_local
Dataset ID: wuerth_local_shipment_invoice_csv_v1
Backend: postgres
SQL dialect: PostgreSQL

PostgreSQL schema:
Table: wuerth.invoices
  - order_date: date
  - order_reason_statistic: text
  - order_number: text
  - order_item: text
  - sales_area: text
  - order_entry_date: date
  - customer: text
  - market_segment: text
  - material_price: text
  - pack_size: text
Table: wuerth.shipments
  - order_number: text
  - number_delivery_items: bigint
  - actual_quantity_delivered_in_sales_units: numeric
  - customer_material: text
  - priority_of_delivery: text
  - delivery_type: text
  - shiptoparty: text
  - soldtoparty: text
  - delivery_number: text
  - freight_costs: numeric

Semantic layer:
(test context)
"""


def csv_header(file_name: str) -> set[str]:
    with (WUERTH_CSV_DIR / file_name).open("r", newline="", encoding="utf-8-sig") as file:
        return {column.strip().lower() for column in next(csv.reader(file))}


class WuerthLocalScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_active_scenario_id()

    def tearDown(self) -> None:
        reset_active_scenario_id()

    def test_sidebar_options_include_supported_scenarios(self) -> None:
        self.assertEqual(
            [scenario.scenario_id for scenario in get_scenario_options()],
            ["demo", "wuerth_local", "databricks"],
        )

    def test_wuerth_local_scenario_uses_postgres_and_local_allowed_tables(self) -> None:
        scenario = SCENARIOS["wuerth_local"]

        self.assertEqual(scenario.backend_name, "postgres")
        self.assertEqual(scenario.sql_dialect, "PostgreSQL")
        self.assertEqual(scenario.allowed_tables, ("wuerth.invoices", "wuerth.shipments"))

    def test_wuerth_semantic_layer_loads_for_wuerth_local(self) -> None:
        set_active_scenario_id("wuerth_local")
        semantic_layer_text = load_semantic_layer_text()

        self.assertIn("wuerth.invoices", semantic_layer_text)
        self.assertIn("wuerth.shipments", semantic_layer_text)
        self.assertIn("not_supported_with_current_local_csv", semantic_layer_text)

    @unittest.skipUnless(WUERTH_CSV_DIR.exists(), "Local Würth CSV exports are not present.")
    def test_wuerth_semantic_layer_matches_current_csv_headers(self) -> None:
        semantic = yaml.safe_load(SCENARIOS["wuerth_local"].semantic_layer_path.read_text(encoding="utf-8"))
        invoice_columns = set(semantic["tables"]["invoices"]["columns"])
        shipment_columns = set(semantic["tables"]["shipments"]["columns"])

        self.assertLessEqual(invoice_columns, csv_header("Wuerth_invoices.csv"))
        self.assertLessEqual(shipment_columns, csv_header("Wuerth_shipments.csv"))

    def test_wuerth_semantic_layer_documents_join_key_mapping(self) -> None:
        semantic = yaml.safe_load(SCENARIOS["wuerth_local"].semantic_layer_path.read_text(encoding="utf-8"))
        join_conditions = semantic["joins"]["invoices_to_shipments"]["join_condition"]
        pairs = {(condition["left_column"], condition["right_column"]) for condition in join_conditions}

        self.assertIn(("order_number", "order_number"), pairs)
        self.assertIn(("customer", "shiptoparty"), pairs)
        self.assertIn(("material_price", "customer_material"), pairs)

    def test_wuerth_validator_allows_only_wuerth_tables(self) -> None:
        valid = validate_generated_sql(
            "SELECT SUM(freight_costs) AS total_freight_costs FROM wuerth.shipments",
            WUERTH_SCHEMA_CONTEXT,
        )
        invalid = validate_generated_sql(
            "SELECT COUNT(*) FROM lineitem",
            WUERTH_SCHEMA_CONTEXT,
        )

        self.assertTrue(valid.is_valid, valid.error)
        self.assertFalse(invalid.is_valid)
        self.assertIn("Unbekannte oder nicht erlaubte Tabellenreferenz", invalid.error)

    def test_literal_limitation_query_is_valid_in_wuerth_context(self) -> None:
        result = validate_generated_sql(
            "SELECT 'The requested revenue metric is unsupported because no revenue or turnover column is present in the local Würth invoice CSV.' AS limitation",
            WUERTH_SCHEMA_CONTEXT,
        )

        self.assertTrue(result.is_valid, result.error)

    def test_databricks_remains_explicitly_available(self) -> None:
        self.assertEqual(SCENARIOS["databricks"].backend_name, "databricks")


if __name__ == "__main__":
    unittest.main()
