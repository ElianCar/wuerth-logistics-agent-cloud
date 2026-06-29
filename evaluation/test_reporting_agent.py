from __future__ import annotations

from decimal import Decimal
import unittest
from unittest import mock

import pandas as pd

from src.agent import reporting_agent
from src.agent.profiles import ResponseProfile
from src.agent.reporting_agent import _parse_four_part, build_reporting_result, rerender_summary


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
    def setUp(self) -> None:
        # These tests assert the exact deterministic summary text. Force the
        # deterministic fallback so an LLM (if an API key is present in the
        # environment) never rephrases the output under test.
        patcher = mock.patch.object(reporting_agent, "_render_summary_with_llm", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

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

        self.assertEqual(report["chart_plan"]["chart_type"], "area")
        self.assertIn("sichtbare Verlauf", report["interpretation"])
        self.assertIn("2024-01", report["interpretation"])
        self.assertIn("2024-02", report["interpretation"])
        self.assertNotIn("höchste sichtbare Wert", report["interpretation"])
        self.assertNotIn("hÃ¶chste sichtbare Wert", report["interpretation"])

    def test_dimensionless_single_row_two_measures_does_not_crash(self) -> None:
        # Regression: a measure_bar chart sets x_axis == y_axis == a measure. The
        # reporting layer must not promote that to a grouping column, otherwise
        # df[[grouping, metric]] selects duplicate columns and pd.to_numeric crashes
        # with "arg must be a list, tuple, 1-d array, or Series".
        report = build_report(
            query_result(["anzahl_auftraege", "anteil_prozent"], [(42, Decimal("3.7"))]),
            user_question="Wie viele Aufträge in mehr als einem Vertriebszentrum, inklusive Anteil",
            sql="SELECT anzahl_auftraege, anteil_prozent FROM result",
        )

        self.assertEqual(report["chart_plan"]["chart_type"], "measure_bar")
        self.assertTrue(report["chart_plan"]["render_allowed"])
        self.assertIn("Kurzantwort", report["summary"])
        # The dimensionless measure must not be promoted to a grouping column.
        self.assertNotIn("anzahl_auftraege", report["audit"]["grouping_columns"])

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


class RoleBasedSummaryTests(unittest.TestCase):
    FAKE_LLM_TEXT = (
        "Kurzantwort: Knappe Aussage.\n\n"
        "Berechnungslogik: Kurze Logik.\n\n"
        "Auffälligkeit: Kurze Auffälligkeit.\n\n"
        "Einschränkungen: Kurze Einschränkung."
    )

    def _build(self, response_profile, *, invoke_model):
        with mock.patch.object(reporting_agent, "invoke_model", invoke_model):
            return build_reporting_result(
                user_question="Zeige Umsatz nach Land",
                router_state=requested_router(),
                sql="SELECT n_name, SUM(revenue) AS total_revenue FROM result GROUP BY n_name",
                query_result=query_result(["n_name", "total_revenue"], [("ARGENTINA", 10), ("CHINA", 40)]),
                row_count=2,
                source_tables=["orders"],
                execution_success=True,
                validation_success=True,
                response_profile=response_profile,
            )

    def test_llm_rendering_is_used_when_available(self) -> None:
        fake = mock.Mock(return_value=mock.Mock(response_text=self.FAKE_LLM_TEXT))
        report = self._build(ResponseProfile.MANAGEMENT, invoke_model=fake)

        self.assertEqual(report["audit"]["summary_source"], "llm")
        self.assertEqual(report["audit"]["response_profile"], "management")
        self.assertIn("Knappe Aussage", report["summary"])
        self.assertEqual(report["interpretation"], "Kurze Auffälligkeit.")

    def test_falls_back_to_deterministic_when_llm_fails(self) -> None:
        failing = mock.Mock(side_effect=RuntimeError("no api key"))
        report = self._build(ResponseProfile.ANALYST, invoke_model=failing)

        self.assertEqual(report["audit"]["summary_source"], "deterministic")
        self.assertEqual(report["audit"]["response_profile"], "analyst")
        for heading in ("Kurzantwort", "Berechnungslogik", "Auffälligkeit", "Einschränkungen"):
            self.assertIn(heading, report["summary"])

    def test_invalid_llm_output_triggers_deterministic_fallback(self) -> None:
        incomplete = mock.Mock(return_value=mock.Mock(response_text="Kurzantwort: nur ein Abschnitt"))
        report = self._build(ResponseProfile.MANAGEMENT, invoke_model=incomplete)

        self.assertEqual(report["audit"]["summary_source"], "deterministic")

    def test_profile_depth_instruction_reaches_prompt(self) -> None:
        markers = {
            ResponseProfile.MANAGEMENT: "Management-Ebene",
            ResponseProfile.ANALYST: "Business-Analyst-Ebene",
            ResponseProfile.TECHNICAL: "Technische Ebene",
        }
        for profile, marker in markers.items():
            captured: dict[str, str] = {}

            def _capture(prompt, *args, **kwargs):
                captured["prompt"] = prompt
                return mock.Mock(response_text=self.FAKE_LLM_TEXT)

            self._build(profile, invoke_model=mock.Mock(side_effect=_capture))
            self.assertIn(marker, captured["prompt"])

    def test_default_profile_is_management_when_none(self) -> None:
        report = self._build(None, invoke_model=mock.Mock(side_effect=RuntimeError))
        self.assertEqual(report["audit"]["response_profile"], "management")

    def _deterministic_report(self) -> dict:
        # Build a normal report with the LLM disabled, so summary_facts are stored
        # and the deterministic baseline is the summary.
        with mock.patch.object(reporting_agent, "invoke_model", mock.Mock(side_effect=RuntimeError)):
            return build_reporting_result(
                user_question="Zeige Umsatz nach Land",
                router_state=requested_router(),
                sql="SELECT n_name, SUM(revenue) AS total_revenue FROM result GROUP BY n_name",
                query_result=query_result(["n_name", "total_revenue"], [("ARGENTINA", 10), ("CHINA", 40)]),
                row_count=2,
                source_tables=["orders"],
                execution_success=True,
                validation_success=True,
                response_profile=ResponseProfile.MANAGEMENT,
            )

    def test_rerender_summary_switches_profile_via_llm(self) -> None:
        report = self._deterministic_report()
        self.assertIsNotNone(report["summary_facts"])

        fake = mock.Mock(return_value=mock.Mock(response_text=self.FAKE_LLM_TEXT))
        with mock.patch.object(reporting_agent, "invoke_model", fake):
            updated = rerender_summary(report, response_profile=ResponseProfile.ANALYST, language="de")

        self.assertEqual(updated["audit"]["response_profile"], "analyst")
        self.assertEqual(updated["audit"]["summary_source"], "llm")
        self.assertIn("Knappe Aussage", updated["summary"])
        # Original record is not mutated in place.
        self.assertEqual(report["audit"]["response_profile"], "management")

    def test_rerender_summary_falls_back_to_baseline(self) -> None:
        report = self._deterministic_report()
        baseline = report["summary"]
        with mock.patch.object(reporting_agent, "invoke_model", mock.Mock(side_effect=RuntimeError)):
            updated = rerender_summary(report, response_profile=ResponseProfile.TECHNICAL, language="de")

        self.assertEqual(updated["audit"]["response_profile"], "technical")
        self.assertEqual(updated["audit"]["summary_source"], "deterministic")
        self.assertEqual(updated["summary"], baseline)

    def test_rerender_summary_without_facts_only_stamps_profile(self) -> None:
        report = build_reporting_result(
            user_question="Zeige Umsatz nach Land",
            router_state=requested_router(),
            sql="",
            query_result=query_result(["n_name", "total_revenue"], []),
            row_count=0,
            source_tables=[],
            execution_success=False,
            validation_success=False,
            response_profile=ResponseProfile.MANAGEMENT,
        )
        self.assertIsNone(report["summary_facts"])
        called = mock.Mock(side_effect=AssertionError("LLM must not be called without facts"))
        with mock.patch.object(reporting_agent, "invoke_model", called):
            updated = rerender_summary(report, response_profile=ResponseProfile.ANALYST)
        self.assertEqual(updated["audit"]["response_profile"], "analyst")

    def test_parse_four_part_requires_all_sections(self) -> None:
        self.assertIsNone(_parse_four_part(""))
        self.assertIsNone(_parse_four_part("Kurzantwort: x\n\nBerechnungslogik: y"))
        parsed = _parse_four_part(self.FAKE_LLM_TEXT)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["interpretation"], "Kurze Auffälligkeit.")


if __name__ == "__main__":
    unittest.main()
