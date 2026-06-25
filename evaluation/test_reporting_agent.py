from __future__ import annotations

from decimal import Decimal
import unittest

import pandas as pd

from src.agent.reporting_agent import build_reporting_result


def requested_router(**overrides: object) -> dict[str, object]:
    router = {"output_mode": "chart_plus_table", "language": "de"}
    router.update(overrides)
    return router


def query_result(columns: list[str], rows: list[tuple[object, ...]]) -> dict[str, object]:
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


def build_report(
    result: dict[str, object],
    *,
    user_question: str = "Zeige Umsatz nach Land als Diagramm",
    router_state: dict[str, object] | None = None,
    sql: str = "SELECT n_name, SUM(revenue) AS total_revenue FROM result GROUP BY n_name",
) -> dict[str, object]:
    return build_reporting_result(
        user_question=user_question,
        router_state=router_state if router_state is not None else requested_router(),
        sql=sql,
        query_result=result,
        row_count=int(result.get("row_count", 0) or 0),
        source_tables=["orders"],
        execution_success=True,
        validation_success=True,
        language="de",
    )


class ReportingAgentTests(unittest.TestCase):
    def test_successful_categorical_metric_result_produces_german_summary(self) -> None:
        report = build_report(query_result(["n_name", "total_revenue"], [("ARGENTINA", 10), ("CHINA", 40)]))

        self.assertIn("Kurzantwort", report["summary"])
        self.assertIn("Berechnungslogik", report["summary"])
        self.assertIn("Auffälligkeit", report["summary"])
        self.assertIn("Einschränkungen", report["summary"])
        self.assertEqual(report["audit"]["summary_language"], "de")

    def test_summary_mentions_metric_and_grouping_when_detectable(self) -> None:
        report = build_report(query_result(["n_name", "total_revenue"], [("ARGENTINA", 10), ("CHINA", 40)]))

        self.assertIn("Total Revenue", report["summary"])
        self.assertIn("N Name", report["summary"])

    def test_time_series_summary_uses_trend_wording_before_category_extremes(self) -> None:
        report = build_report(
            query_result(["monat", "anzahl_auftraege"], [("2024-01", 8), ("2024-02", 12)]),
            user_question="Zeige die Anzahl der Auftraege pro Monat als Trenddiagramm",
            sql="SELECT monat, anzahl_auftraege FROM result ORDER BY monat",
        )

        self.assertEqual(report["chart_plan"]["chart_type"], "line")
        self.assertIn("sichtbare Verlauf", report["interpretation"])
        self.assertIn("2024-01", report["interpretation"])
        self.assertIn("2024-02", report["interpretation"])
        self.assertNotIn("höchste sichtbare Wert", report["interpretation"])
        self.assertNotIn("hÃ¶chste sichtbare Wert", report["interpretation"])

    def test_summary_does_not_invent_units(self) -> None:
        report = build_report(query_result(["n_name", "total_revenue"], [("ARGENTINA", 10)]))

        self.assertIn("Einheiten werden nicht automatisch abgeleitet", report["summary"])
        self.assertNotIn("EUR", report["summary"])

    def test_summary_does_not_invent_causes(self) -> None:
        report = build_report(query_result(["n_name", "total_revenue"], [("ARGENTINA", 10), ("CHINA", 40)]))

        self.assertIn("Ursache", report["summary"])
        self.assertIn("nicht ableitbar", report["summary"])

    def test_empty_result_is_handled_safely(self) -> None:
        report = build_report(query_result(["n_name", "total_revenue"], []))

        self.assertIn("keine Ergebniszeilen", report["summary"])
        self.assertFalse(report["table_plan"]["render_allowed"])
        self.assertFalse(report["chart_plan"]["render_allowed"])

    def test_single_kpi_result_is_handled_safely(self) -> None:
        report = build_report(query_result(["total_revenue"], [(Decimal("42.5"),)]), router_state=requested_router(output_mode="table"))

        self.assertIn("Einzelwert", report["summary"])
        self.assertEqual(report["kpi_cards"], [{"label": "Total Revenue", "value": "42,50"}])

    def test_numeric_identifier_is_not_selected_as_metric_when_real_metric_exists(self) -> None:
        report = build_report(
            query_result(["order_id", "total_revenue"], [(1001, 10), (1002, 20)]),
            router_state=requested_router(output_mode="table"),
        )

        self.assertEqual(report["audit"]["metric_columns"], ["total_revenue"])
        self.assertIn("Total Revenue", report["summary"])
        self.assertNotIn("Kennwert Order Id", report["summary"])

    def test_single_row_identifier_and_metric_creates_kpi_card_only_for_metric(self) -> None:
        report = build_report(
            query_result(["order_id", "total_revenue"], [(1001, Decimal("42.5"))]),
            router_state=requested_router(output_mode="table"),
        )

        self.assertEqual(report["kpi_cards"], [{"label": "Total Revenue", "value": "42,50"}])

    def test_only_numeric_identifiers_do_not_create_metric_summary_or_kpi_cards(self) -> None:
        report = build_report(
            query_result(["order_id", "customer_id"], [(1001, 2002)]),
            router_state=requested_router(output_mode="table"),
        )

        self.assertEqual(report["audit"]["metric_columns"], [])
        self.assertEqual(report["kpi_cards"], [])
        self.assertIn("zurückgegebenen Ergebniszeilen", report["summary"])
        self.assertNotIn("Kennwert Order Id", report["summary"])

    def test_single_numeric_identifier_scalar_does_not_create_kpi_card(self) -> None:
        report = build_report(
            query_result(["invoice_number"], [(9001,)]),
            router_state=requested_router(output_mode="table"),
        )

        self.assertEqual(report["audit"]["metric_columns"], [])
        self.assertEqual(report["kpi_cards"], [])

    def test_more_than_50_rows_mentions_chart_truncation(self) -> None:
        rows = [(f"Country {index}", index) for index in range(55)]
        report = build_report(query_result(["n_name", "total_revenue"], rows))

        self.assertTrue(report["audit"]["chart_truncated"])
        self.assertIn("ersten 50 Zeilen", report["summary"])
        self.assertIn("ersten 50 Zeilen", report["display_notes"][0])

    def test_chart_order_and_truncation_are_audited(self) -> None:
        rows = [(f"Country {index}", index) for index in range(55)]
        report = build_report(query_result(["n_name", "total_revenue"], rows))

        self.assertEqual(report["audit"]["chart_order"], "sql_result_order")
        self.assertEqual(report["audit"]["chart_cap"], 50)
        self.assertEqual(report["audit"]["rows_visualized"], 50)

    def test_explicit_sort_request_is_audited(self) -> None:
        report = build_report(
            query_result(["n_name", "total_revenue"], [("CHINA", 40), ("ARGENTINA", 10)]),
            user_question="Zeige Umsatz nach Land alphabetisch sortiert",
        )

        self.assertEqual(report["chart_plan"]["category_order"], ["ARGENTINA", "CHINA"])
        self.assertEqual(report["audit"]["chart_order"], "explicit_user_sort")
        self.assertTrue(report["audit"]["explicit_sort_applied"])

    def test_chart_order_is_encoded_explicitly(self) -> None:
        report = build_report(query_result(["n_name", "total_revenue"], [("CHINA", 40), ("ARGENTINA", 10)]))

        self.assertEqual(report["chart_plan"]["category_order"], ["CHINA", "ARGENTINA"])

    def test_table_rows_are_not_truncated_when_chart_is_truncated(self) -> None:
        rows = [(f"Country {index}", index) for index in range(55)]
        report = build_report(query_result(["n_name", "total_revenue"], rows))

        self.assertEqual(report["table_plan"]["row_count"], 55)
        self.assertEqual(len(report["chart_plan"]["category_order"]), 50)

    def test_summary_generation_does_not_modify_dataframe(self) -> None:
        df = pd.DataFrame(
            [("CHINA", 40), ("ARGENTINA", 10)],
            columns=["n_name", "total_revenue"],
        )
        original = df.copy(deep=True)

        build_reporting_result(
            user_question="Zeige Umsatz nach Land",
            router_state=requested_router(),
            sql="SELECT n_name, total_revenue FROM result",
            result_dataframe=df,
            row_count=len(df.index),
            source_tables=["orders"],
            execution_success=True,
            validation_success=True,
        )

        pd.testing.assert_frame_equal(df, original)

    def test_failed_sql_result_has_no_chart_and_no_business_interpretation(self) -> None:
        report = build_reporting_result(
            user_question="Zeige Umsatz nach Land",
            router_state=requested_router(),
            sql="",
            query_result=query_result(["n_name", "total_revenue"], []),
            row_count=0,
            source_tables=[],
            execution_success=False,
            validation_success=False,
        )

        self.assertFalse(report["chart_plan"]["render_allowed"])
        self.assertIn("kein erfolgreiches SQL Ergebnis", report["summary"])


if __name__ == "__main__":
    unittest.main()
