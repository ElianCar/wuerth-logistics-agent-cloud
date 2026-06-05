from __future__ import annotations

from decimal import Decimal
import json
import unittest

from src.agent.visualization_spec import build_visualization_spec


def requested_context(**overrides: object) -> dict[str, object]:
    context: dict[str, object] = {"output_mode": "chart_plus_table"}
    context.update(overrides)
    return context


def query_result(columns: list[str], rows: list[tuple[object, ...]]) -> dict[str, object]:
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "executed_sql": "SELECT ...",
    }


def build_spec(
    result: dict[str, object],
    *,
    router_context: dict[str, object] | None = None,
    execution_success: bool = True,
    validation_success: bool = True,
    user_question: str = "show chart",
) -> dict[str, object]:
    return build_visualization_spec(
        user_question=user_question,
        router_context=router_context if router_context is not None else requested_context(),
        query_result=result,
        execution_success=execution_success,
        validation_success=validation_success,
        row_count=int(result.get("row_count", 0) or 0),
        final_sql=str(result.get("executed_sql", "")),
        source_tables=["orders"],
    )


class VisualizationSpecTests(unittest.TestCase):
    def test_empty_result_returns_no_chart(self) -> None:
        spec = build_spec(query_result(["region", "total_revenue"], []))

        self.assertFalse(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "none")
        self.assertIn("empty", str(spec["reason"]).lower())

    def test_failed_sql_returns_no_chart(self) -> None:
        spec = build_spec(
            query_result(["region", "total_revenue"], [("EUROPE", 10)]),
            execution_success=False,
        )

        self.assertFalse(spec["render_allowed"])
        self.assertIn("execution", str(spec["reason"]).lower())

    def test_failed_validation_returns_no_chart(self) -> None:
        spec = build_spec(
            query_result(["region", "total_revenue"], [("EUROPE", 10)]),
            validation_success=False,
        )

        self.assertFalse(spec["render_allowed"])
        self.assertIn("validation", str(spec["reason"]).lower())

    def test_single_scalar_result_returns_no_chart(self) -> None:
        spec = build_spec(query_result(["total_revenue"], [(Decimal("42.5"),)]))

        self.assertFalse(spec["render_allowed"])
        self.assertIn("scalar", str(spec["reason"]).lower())

    def test_generic_non_numeric_table_returns_no_chart(self) -> None:
        spec = build_spec(query_result(["region", "status"], [("EUROPE", "open")]))

        self.assertFalse(spec["render_allowed"])
        self.assertIn("numeric measure", str(spec["reason"]).lower())

    def test_category_plus_numeric_measure_returns_bar_chart_when_requested(self) -> None:
        spec = build_spec(
            query_result(
                ["region", "total_revenue"],
                [("EUROPE", Decimal("10.5")), ("ASIA", Decimal("8.0"))],
            )
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "bar")
        self.assertEqual(spec["x_axis"], "region")
        self.assertEqual(spec["y_axis"], "total_revenue")
        self.assertEqual(spec["x_type"], "categorical")
        self.assertEqual(spec["y_type"], "quantitative")
        self.assertTrue(spec["value_axis_starts_at_zero"])

    def test_date_plus_numeric_measure_returns_line_chart_when_requested(self) -> None:
        spec = build_spec(
            query_result(
                ["month", "total_revenue"],
                [("2024-02", 12), ("2024-01", 8)],
            )
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "line")
        self.assertEqual(spec["x_axis"], "month")
        self.assertEqual(spec["y_axis"], "total_revenue")
        self.assertEqual(spec["category_order"], ["2024-02", "2024-01"])

    def test_no_explicit_chart_request_returns_no_renderable_chart(self) -> None:
        spec = build_spec(
            query_result(["region", "total_revenue"], [("EUROPE", 10)]),
            router_context={"output_mode": "table"},
        )

        self.assertFalse(spec["render_allowed"])
        self.assertIn("no explicit chart request", str(spec["reason"]).lower())

    def test_multiple_numeric_measures_are_rejected_when_ambiguous(self) -> None:
        spec = build_spec(
            query_result(
                ["region", "total_revenue", "freight_costs"],
                [("EUROPE", 10, 2), ("ASIA", 8, 3)],
            ),
            user_question="show metrics by region",
        )

        self.assertFalse(spec["render_allowed"])
        self.assertIn("multiple numeric measures", str(spec["reason"]).lower())

    def test_multiple_numeric_measures_select_requested_measure_with_warning(self) -> None:
        spec = build_spec(
            query_result(
                ["region", "total_revenue", "freight_costs"],
                [("EUROPE", 10, 2), ("ASIA", 8, 3)],
            ),
            user_question="show total revenue by region",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["y_axis"], "total_revenue")
        self.assertTrue(spec["warnings"])

    def test_chart_display_cap_is_50(self) -> None:
        rows = [(f"Category {index}", index) for index in range(50)]
        spec = build_spec(query_result(["category", "total_revenue"], rows))

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["display_row_limit"], 50)
        self.assertEqual(len(spec["category_order"]), 50)

    def test_more_than_50_rows_are_truncated_to_first_50_with_note(self) -> None:
        rows = [(f"Category {index}", index) for index in range(51)]
        spec = build_spec(query_result(["category", "total_revenue"], rows))

        self.assertTrue(spec["render_allowed"])
        self.assertTrue(spec["truncated"])
        self.assertEqual(len(spec["category_order"]), 50)
        self.assertEqual(spec["category_order"][0], "Category 0")
        self.assertEqual(spec["category_order"][-1], "Category 49")
        self.assertIn("ersten 50 Zeilen", str(spec["note"]))

    def test_numeric_identifier_columns_are_not_measures(self) -> None:
        spec = build_spec(query_result(["order_id", "customer"], [(1001, "A"), (1002, "B")]))

        self.assertFalse(spec["render_allowed"])
        self.assertIn("numeric measure", str(spec["reason"]).lower())

    def test_identifier_columns_are_not_used_as_categorical_x_axis(self) -> None:
        spec = build_spec(query_result(["order_id", "total_revenue"], [(1001, 10), (1002, 8)]))

        self.assertFalse(spec["render_allowed"])
        self.assertIn("categorical", str(spec["reason"]).lower())

    def test_missing_semantic_labels_falls_back_to_raw_column_names(self) -> None:
        spec = build_spec(query_result(["region", "total_revenue"], [("EUROPE", 10)]))

        self.assertEqual(spec["x_label"], "Region")
        self.assertEqual(spec["y_label"], "Total Revenue")

    def test_semantic_labels_and_units_are_used_when_available(self) -> None:
        spec = build_visualization_spec(
            user_question="show chart",
            router_context=requested_context(),
            query_result=query_result(["region", "freight_costs"], [("EUROPE", 10)]),
            execution_success=True,
            validation_success=True,
            row_count=1,
            final_sql="SELECT ...",
            source_tables=["wuerth.shipments"],
            semantic_metadata={
                "columns": {
                    "region": {"business_name": "Sales Region"},
                    "freight_costs": {"business_name": "Freight Costs", "unit": "EUR"},
                }
            },
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["x_label"], "Sales Region")
        self.assertEqual(spec["y_label"], "Freight Costs")
        self.assertEqual(spec["unit"], "EUR")

    def test_table_only_output_mode_prevents_chart_rendering(self) -> None:
        spec = build_spec(
            query_result(["region", "total_revenue"], [("EUROPE", 10)]),
            router_context={"output_mode": "table"},
        )

        self.assertFalse(spec["render_allowed"])

    def test_chart_request_with_unsuitable_shape_is_rejected(self) -> None:
        spec = build_spec(query_result(["region"], [("EUROPE",), ("ASIA",)]))

        self.assertFalse(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "none")

    def test_chart_spec_is_json_serializable(self) -> None:
        spec = build_spec(query_result(["region", "total_revenue"], [("EUROPE", Decimal("10.5"))]))

        json.dumps(spec)

    def test_chart_preserves_sql_table_row_order(self) -> None:
        spec = build_spec(
            query_result(
                ["n_name", "total_revenue"],
                [
                    ("ARGENTINA", 10),
                    ("CHINA", 40),
                    ("FRANCE", 30),
                    ("GERMANY", 20),
                    ("INDIA", 50),
                ],
            )
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["category_order"], ["ARGENTINA", "CHINA", "FRANCE", "GERMANY", "INDIA"])
        self.assertEqual(spec["sort"]["mode"], "sql_result_order")

    def test_chart_does_not_sort_categories_alphabetically_by_default(self) -> None:
        spec = build_spec(query_result(["n_name", "total_revenue"], [("CHINA", 40), ("ARGENTINA", 10)]))

        self.assertEqual(spec["category_order"], ["CHINA", "ARGENTINA"])

    def test_categorical_axis_contains_names_not_numeric_metric_values(self) -> None:
        spec = build_spec(query_result(["n_name", "total_revenue"], [("CHINA", 40), ("ARGENTINA", 10)]))

        self.assertEqual(spec["x_axis"], "n_name")
        self.assertEqual(spec["y_axis"], "total_revenue")
        self.assertEqual(spec["category_order"], ["CHINA", "ARGENTINA"])
        self.assertNotIn("40", spec["category_order"])

    def test_explicit_alphabetical_sort_request_overrides_sql_row_order_for_chart_only(self) -> None:
        spec = build_spec(
            query_result(["n_name", "total_revenue"], [("CHINA", 40), ("ARGENTINA", 10)]),
            user_question="Show revenue by country sorted alphabetically",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["category_order"], ["ARGENTINA", "CHINA"])
        self.assertTrue(spec["sort"]["explicit"])

    def test_explicit_metric_sort_request_overrides_sql_row_order_for_chart_only(self) -> None:
        spec = build_spec(
            query_result(
                ["n_name", "total_revenue"],
                [("ARGENTINA", 10), ("CHINA", 40), ("FRANCE", 30)],
            ),
            user_question="Show revenue by country descending revenue",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["category_order"], ["CHINA", "FRANCE", "ARGENTINA"])
        self.assertEqual(spec["sort"]["mode"], "measure")

    def test_query_result_is_not_mutated_when_no_chart_is_rendered(self) -> None:
        result = query_result(["total_revenue"], [(10,)])
        original = dict(result)

        spec = build_spec(result)

        self.assertFalse(spec["render_allowed"])
        self.assertEqual(result, original)

    def test_table_rows_are_not_mutated_when_chart_is_truncated(self) -> None:
        rows = [(f"Category {index}", index) for index in range(55)]
        result = query_result(["category", "total_revenue"], rows)
        original_rows = list(result["rows"])

        spec = build_spec(result)

        self.assertTrue(spec["render_allowed"])
        self.assertTrue(spec["truncated"])
        self.assertEqual(result["rows"], original_rows)
        self.assertEqual(len(result["rows"]), 55)


if __name__ == "__main__":
    unittest.main()
