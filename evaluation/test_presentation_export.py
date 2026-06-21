from __future__ import annotations

from io import BytesIO
import sys
import tempfile
import unittest
from pathlib import Path

from pptx import Presentation

from src.agent.presentation_export import (
    PPTX_MIME_TYPE,
    build_presentation_export,
    build_slide_deck_spec,
)


def query_result(columns: list[str], rows: list[tuple[object, ...]]) -> dict[str, object]:
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


def reporting_result(
    result: dict[str, object],
    *,
    chart_render_allowed: bool = True,
) -> dict[str, object]:
    return {
        "summary": (
            "Kurzantwort: Die Liefermengen unterscheiden sich sichtbar nach Region.\n\n"
            "Berechnungslogik: Ausgewertet wurden validierte Ergebniszeilen nach Region.\n\n"
            "Auffaelligkeit: Sued zeigt den hoechsten sichtbaren Wert.\n\n"
            "Einschraenkungen: Es werden nur die zurueckgegebenen Zeilen bewertet."
        ),
        "interpretation": "Sued zeigt den hoechsten sichtbaren Wert.",
        "caveats": [
            "Die Aussage basiert nur auf den zurueckgegebenen Zeilen.",
            "Aus deskriptiven Aggregaten wird keine Ursache abgeleitet.",
        ],
        "chart_plan": {
            "chart_type": "bar",
            "title": "Liefermenge nach Region",
            "render_allowed": chart_render_allowed,
            "x_axis": "region",
            "y_axis": "shipment_count",
            "reason": "Chart requested and result has one categorical dimension with one numeric measure.",
            "warnings": [],
        },
        "table_plan": {
            "render_allowed": True,
            "row_count": int(result.get("row_count", 0) or 0),
            "columns": list(result.get("columns", [])),
            "preserve_sql_order": True,
        },
        "kpi_cards": [
            {"label": "Lieferungen", "value": "9", "note": "Validierte Ergebniszeilen"},
            {"label": "Top Region", "value": "Sued", "note": "Hoechster sichtbarer Wert"},
        ],
        "display_notes": ["Die Darstellung folgt der Reihenfolge des SQL Ergebnisses."],
        "audit": {
            "sql_success": True,
            "row_count": int(result.get("row_count", 0) or 0),
            "chart_type": "bar",
            "source_tables": ["wuerth.shipments"],
            "warnings": [],
            "table_order_preserved": True,
        },
    }


def orchestrator_record(**overrides: object) -> dict[str, object]:
    result = query_result(
        ["region", "shipment_count"],
        [
            ("Sued", 90),
            ("Nord", 75),
            ("West", 68),
            ("Ost", 62),
            ("Mitte", 55),
            ("Export", 48),
            ("Direkt", 44),
            ("Partner", 39),
            ("Retouren", 12),
        ],
    )
    record: dict[str, object] = {
        "run_id": "run-ppt-001",
        "user_question": "Zeige Lieferungen nach Region als Praesentation",
        "final_sql": "SELECT region, COUNT(*) AS shipment_count FROM wuerth.shipments GROUP BY region",
        "query_result": result,
        "row_count": result["row_count"],
        "execution_success": True,
        "validation_success": True,
        "sql_valid": True,
        "source_tables": ["wuerth.shipments"],
        "reporting_result": reporting_result(result),
        "result_status": "success",
        "error_type": "",
    }
    record.update(overrides)
    return record


def valid_record() -> dict[str, object]:
    return orchestrator_record()


class PresentationExportSuccessTests(unittest.TestCase):
    def test_successful_record_returns_dynamic_pptx_export(self) -> None:
        export = build_presentation_export(record=valid_record())

        self.assertTrue(export.available)
        self.assertIsInstance(export.content, bytes)
        self.assertGreater(len(export.content), 0)
        self.assertTrue(export.filename.endswith(".pptx"))
        self.assertEqual(export.mime_type, PPTX_MIME_TYPE)
        self.assertGreater(export.slide_count, 0)
        self.assertNotEqual(export.slide_count, 9)

    def test_generated_pptx_bytes_reopen_without_powerpoint(self) -> None:
        export = build_presentation_export(record=valid_record())

        presentation = Presentation(BytesIO(export.content))

        self.assertEqual(len(presentation.slides), export.slide_count)
        self.assertGreater(len(presentation.slides), 1)

    def test_slide_deck_spec_is_ordered_dynamic_and_excludes_default_closing(self) -> None:
        spec = build_slide_deck_spec(record=valid_record())

        layout_names = [slide.layout_name for slide in spec.slides]

        self.assertEqual(layout_names[0], "Agent 01 Cover")
        self.assertIn("Agent 02 Executive Summary", layout_names)
        self.assertIn("Agent 03 KPI Overview", layout_names)
        self.assertIn("Agent 04 Chart Evidence", layout_names)
        self.assertGreaterEqual(layout_names.count("Agent 05 Table Evidence"), 2)
        self.assertIn("Agent 07 Caveats And Sources", layout_names)
        self.assertIn("Agent 08 Appendix Metadata", layout_names)
        self.assertNotIn("Agent 09 Closing", layout_names)
        self.assertNotEqual(layout_names, [
            "Agent 01 Cover",
            "Agent 02 Executive Summary",
            "Agent 03 KPI Overview",
            "Agent 04 Chart Evidence",
            "Agent 05 Table Evidence",
            "Agent 06 Comparison",
            "Agent 07 Caveats And Sources",
            "Agent 08 Appendix Metadata",
            "Agent 09 Closing",
        ])

    def test_slide_deck_spec_includes_one_closing_when_requested(self) -> None:
        spec = build_slide_deck_spec(record=valid_record(), include_closing=True)

        layout_names = [slide.layout_name for slide in spec.slides]

        self.assertEqual(layout_names.count("Agent 09 Closing"), 1)
        self.assertEqual(layout_names[-1], "Agent 09 Closing")

    def test_backend_contract_does_not_import_streamlit_surfaces(self) -> None:
        build_slide_deck_spec(record=valid_record())

        self.assertNotIn("streamlit", sys.modules)
        self.assertNotIn("streamlit_app", sys.modules)


class PresentationExportEligibilityTests(unittest.TestCase):
    def assert_unavailable_export(self, export: object, expected_reason_part: str) -> None:
        self.assertFalse(export.available)
        self.assertEqual(export.content, b"")
        self.assertTrue(export.unavailable_reason)
        self.assertIn(expected_reason_part, export.unavailable_reason.lower())

    def test_ineligible_records_return_unavailable_without_pptx_bytes(self) -> None:
        cases = [
            (
                "failed_execution",
                {"execution_success": False},
                "execution",
            ),
            (
                "failed_validation",
                {"validation_success": False, "sql_valid": True},
                "validation",
            ),
            (
                "invalid_sql",
                {"validation_success": True, "sql_valid": False},
                "validation",
            ),
            (
                "needs_clarification",
                {"needs_clarification": True},
                "clarification",
            ),
            (
                "blocked_or_unsafe",
                {"blocked_or_unsafe": True},
                "blocked",
            ),
            (
                "missing_columns",
                {"query_result": {"rows": [("Sued", 90)], "row_count": 1}, "row_count": 1},
                "columns",
            ),
            (
                "missing_rows",
                {"query_result": {"columns": ["region", "shipment_count"], "row_count": 1}, "row_count": 1},
                "rows",
            ),
            (
                "zero_row_count",
                {
                    "query_result": {
                        "columns": ["region", "shipment_count"],
                        "rows": [("Sued", 90)],
                        "row_count": 0,
                    },
                    "row_count": 0,
                },
                "row",
            ),
        ]

        for name, overrides, expected_reason_part in cases:
            with self.subTest(name=name):
                export = build_presentation_export(record=orchestrator_record(**overrides))

                self.assert_unavailable_export(export, expected_reason_part)

    def test_valid_record_with_missing_template_returns_structured_template_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_template = Path(temp_dir) / "missing-template.pptx"

            export = build_presentation_export(record=valid_record(), template_path=missing_template)

        self.assert_unavailable_export(export, "template")
        self.assertIsNotNone(export.template_audit)
        self.assertTrue(export.template_audit.errors)

    def test_ineligible_record_reports_eligibility_before_template_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_template = Path(temp_dir) / "missing-template.pptx"

            export = build_presentation_export(
                record=orchestrator_record(execution_success=False),
                template_path=missing_template,
            )

        self.assert_unavailable_export(export, "execution")
        self.assertIsNone(export.template_audit)


if __name__ == "__main__":
    unittest.main()
