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

    def test_date_plus_numeric_measure_returns_area_chart_when_requested(self) -> None:
        spec = build_spec(
            query_result(
                ["month", "total_revenue"],
                [("2024-02", 12), ("2024-01", 8)],
            )
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "area")
        self.assertEqual(spec["x_axis"], "month")
        self.assertEqual(spec["y_axis"], "total_revenue")
        self.assertEqual(spec["category_order"], ["2024-02", "2024-01"])

    def test_german_month_alias_returns_area_chart_when_requested(self) -> None:
        spec = build_spec(
            query_result(
                ["monat", "anzahl_auftraege"],
                [("2024-01", 8), ("2024-02", 12)],
            ),
            user_question="Zeige die Anzahl der Auftraege pro Monat als Trenddiagramm",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "area")
        self.assertEqual(spec["x_axis"], "monat")
        self.assertEqual(spec["y_axis"], "anzahl_auftraege")

    def test_yyyymm_integer_column_is_treated_as_time_dimension(self) -> None:
        # calendar_yearmonth stores compact integers like 202507 (July 2025)
        spec = build_spec(
            query_result(
                ["calendar_yearmonth", "revenue"],
                [(202507, 12345.67), (202508, 9876.54)],
            ),
            user_question="Zeige mir den Umsatz im Zeitverlauf",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "area")
        self.assertEqual(spec["x_axis"], "calendar_yearmonth")
        self.assertEqual(spec["y_axis"], "revenue")

    def test_yyyymm_single_row_is_treated_as_time_dimension(self) -> None:
        # 1-row result from a narrow date range should still render as area chart
        spec = build_spec(
            query_result(
                ["calendar_yearmonth", "revenue"],
                [(202507, 12345.67)],
            ),
            user_question="Umsatz im Zeitverlauf",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "area")

    def test_token_match_picks_share_column_when_anteil_in_question(self) -> None:
        # 2 numeric measures: count + share percentage
        # question contains "Anteil" → token "anteil" matches "anteil_prozent", not "anzahl_auftraege"
        spec = build_spec(
            query_result(
                ["kategorie", "anzahl_auftraege", "anteil_prozent"],
                [("Mehrere VZ", 5, 5.0), ("Nur 1 VZ", 95, 95.0)],
            ),
            user_question="Aufträge in mehreren VZ inklusive Anteil an allen Aufträgen in einem Diagramm",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["y_axis"], "anteil_prozent")
        self.assertTrue(spec["warnings"])

    def test_semantic_type_marks_numeric_code_column_as_dimension(self) -> None:
        # plant values look numeric ("9191") but the semantic layer says they are an
        # organizational dimension, so the result must be a bar (not a measure-only chart).
        spec = build_visualization_spec(
            user_question="Umsatz je Vertriebszentrum",
            router_context=requested_context(),
            query_result=query_result(["plant", "revenue"], [("9191", 100), ("9192", 80)]),
            execution_success=True,
            validation_success=True,
            row_count=2,
            final_sql="SELECT ...",
            source_tables=["wuerth.shipments"],
            semantic_metadata={"columns": {"plant": {"semantic_type": "organizational_code"}}},
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "bar")
        self.assertEqual(spec["x_axis"], "plant")
        self.assertEqual(spec["y_axis"], "revenue")

    def test_aliased_dimension_name_is_categorical_without_semantic_metadata(self) -> None:
        # SQL aliases the plant column to "vertriebszentrum", so semantic lookup misses.
        # The German dimension-name heuristic must still treat numeric codes as a dimension.
        spec = build_spec(
            query_result(["vertriebszentrum", "umsatz"], [("9191", 100), ("9192", 80)]),
            user_question="Umsatz je Vertriebszentrum",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "bar")
        self.assertEqual(spec["x_axis"], "vertriebszentrum")

    def test_wide_row_level_result_with_two_measures_falls_back_to_scatter(self) -> None:
        # "Umsatz und Lieferkosten je Lieferposition" returns a wide row-level table with
        # identifiers, a constant filter column (plant) and an incidental date. With the
        # semantic layer (as the app always passes it), none of the clean structures fit,
        # but two measures → scatter beats returning no chart.
        rows = [
            (1000 + i, 5000 + i, f"M{i}", f"C{i % 9}", f"2025-07-{(i % 28) + 1:02d}", "9981", float(100 + i), float(10 + i))
            for i in range(20)
        ]
        spec = build_visualization_spec(
            user_question="Zeige für jede Lieferposition aus Lager 9981 den Umsatz und die Lieferkosten",
            router_context=requested_context(),
            query_result=query_result(
                ["delivery_number", "order_number", "customer_material", "shiptoparty",
                 "shipment_date", "plant", "umsatz", "lieferkosten"],
                rows,
            ),
            execution_success=True,
            validation_success=True,
            row_count=20,
            final_sql="SELECT ...",
            source_tables=["wuerth.shipments"],
            semantic_metadata={
                "columns": {
                    "delivery_number": {"semantic_type": "delivery_identifier"},
                    "order_number": {"semantic_type": "identifier"},
                    "customer_material": {"semantic_type": "product_identifier"},
                    "shiptoparty": {"semantic_type": "customer_identifier"},
                    "shipment_date": {"semantic_type": "date"},
                    "plant": {"semantic_type": "organizational_code"},
                }
            },
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "scatter")
        self.assertEqual(spec["x_axis"], "umsatz")
        self.assertEqual(spec["y_axis"], "lieferkosten")

    def test_constant_filter_column_is_ignored_for_chart_structure(self) -> None:
        # plant is constant (all '9191' after WHERE plant='9191'); it must not be treated
        # as a dimension. month + revenue then form a clean time series.
        spec = build_spec(
            query_result(
                ["plant", "monat", "revenue"],
                [("9191", "2024-01", 10), ("9191", "2024-02", 12), ("9191", "2024-03", 9)],
            ),
            user_question="Umsatzentwicklung von Vertriebszentrum 9191 pro Monat",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "area")
        self.assertEqual(spec["x_axis"], "monat")

    def test_rank_helper_columns_are_excluded_so_faceted_bar_is_detected(self) -> None:
        # "Top 3 ... je Vertriebszentrum" produces RANK() helper columns. These ordinal
        # helpers must not count as measures, otherwise faceted_bar (2 dims + 2 measures)
        # is missed because the result appears to have 4 measures.
        # multiple Vertriebszentren (plant is not constant) — as in a real "je VZ" result
        rows = [(f"919{i % 4}", f"P{i % 5}", 1000.0 - i, 50 - i, (i % 3) + 1, (i % 3) + 1) for i in range(12)]
        spec = build_spec(
            query_result(
                ["plant", "product", "revenue", "lieferpositionen", "revenue_rank", "lieferpositionen_rank"],
                rows,
            ),
            user_question="Top 3 Produkte je Vertriebszentrum nach Umsatz und Lieferpositionen inklusive Diagramm",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "faceted_bar")
        self.assertIn("revenue", {spec["y_axis"], spec["second_metric"]})
        self.assertIn("lieferpositionen", {spec["y_axis"], spec["second_metric"]})

    def test_two_semantic_dimensions_plus_measure_returns_grouped_bar(self) -> None:
        spec = build_visualization_spec(
            user_question="Top Produkte je Vertriebszentrum",
            router_context=requested_context(),
            query_result=query_result(
                ["product", "plant", "revenue"],
                [("40010815", "9191", 100), ("40010816", "9192", 80), ("40010817", "9191", 60)],
            ),
            execution_success=True,
            validation_success=True,
            row_count=3,
            final_sql="SELECT ...",
            source_tables=["wuerth.shipments"],
            semantic_metadata={
                "columns": {
                    "product": {"semantic_type": "product_identifier"},
                    "plant": {"semantic_type": "organizational_code"},
                }
            },
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "grouped_bar")

    def test_pie_keyword_wins_over_default_bar(self) -> None:
        # vertriebszentrum (dimension) + measures + explicit "Kreisdiagramm" → pie, not bar.
        spec = build_spec(
            query_result(
                ["vertriebszentrum", "revenue", "umsatzanteil_prozent"],
                [("9191", 100, 33.3), ("9192", 120, 40.0), ("9193", 80, 26.7)],
            ),
            user_question="Umsatzanteil je Vertriebszentrum als Kreisdiagramm",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "pie")

    def test_semantic_identifier_is_not_used_as_axis(self) -> None:
        # order_number is an identifier per the semantic layer → not a chart dimension.
        spec = build_visualization_spec(
            user_question="Zeige Aufträge",
            router_context=requested_context(),
            query_result=query_result(["order_number", "revenue"], [("100", 10), ("101", 8)]),
            execution_success=True,
            validation_success=True,
            row_count=2,
            final_sql="SELECT ...",
            source_tables=["wuerth.invoices"],
            semantic_metadata={"columns": {"order_number": {"semantic_type": "identifier"}}},
        )

        self.assertFalse(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "none")

    def test_dimensionless_single_row_multi_measure_returns_measure_bar(self) -> None:
        # 1 row, two numeric measures, no category/time → fallback bar (one bar per measure)
        spec = build_spec(
            query_result(
                ["anzahl_auftraege", "anteil_prozent"],
                [(5, 5.0)],
            ),
            user_question="Aufträge in mehreren VZ inklusive Anteil in einem Diagramm",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "measure_bar")
        self.assertEqual(spec["measure_columns"], ["anzahl_auftraege", "anteil_prozent"])

    def test_dimensionless_multi_row_single_measure_returns_measure_bar(self) -> None:
        # Several rows, single numeric measure, no category/time dimension.
        # Shape avoids the 1x1 scalar guard, so it still produces a chart.
        spec = build_spec(
            query_result(
                ["anzahl_auftraege"],
                [(5,), (8,), (3,)],
            ),
            user_question="Anzahl Aufträge",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "measure_bar")
        self.assertEqual(spec["measure_columns"], ["anzahl_auftraege"])

    def test_auto_render_without_explicit_chart_request(self) -> None:
        spec = build_spec(
            query_result(["region", "total_revenue"], [("EUROPE", 10), ("ASIA", 8)]),
            router_context={},
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "bar")

    def test_ambiguous_multiple_measures_render_first_measure_with_warning(self) -> None:
        # Philosophy "rather one chart too many": an ambiguous multi-measure result
        # no longer aborts. It renders the first measure and attaches a warning.
        spec = build_spec(
            query_result(
                ["region", "total_revenue", "freight_costs"],
                [("EUROPE", 10, 2), ("ASIA", 8, 3)],
            ),
            user_question="show metrics by region",
        )

        self.assertTrue(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "bar")
        self.assertEqual(spec["y_axis"], "total_revenue")
        self.assertTrue(spec["warnings"])

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
