from __future__ import annotations

from io import BytesIO
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pptx import Presentation

from src.agent.presentation_export import (
    DEFAULT_TEMPLATE_PATH,
    PPTX_MIME_TYPE,
    SlideDeckSpec,
    SlideSpec,
    FIXED_PPTX_TIMESTAMP,
    build_claude_presentation_export,
    build_deterministic_presentation_export,
    build_presentation_export,
    build_slide_deck_spec,
    can_export_presentation,
    validate_slide_deck_spec,
    validate_template,
)
from src.agent.presentation_planner import (
    EvidenceChartPlan,
    EvidenceTablePage,
    ExecutiveBullet,
    PlanningAudit,
    PresentationPlanningConfig,
    PresentationPlan,
    TextSpan,
    build_presentation_plan,
    derive_presentation_title,
    format_management_number,
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


def pptx_text_values(content: bytes) -> list[str]:
    presentation = Presentation(BytesIO(content))
    text_values: list[str] = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text_values.append(shape.text)
    return text_values


def pptx_text(content: bytes) -> str:
    return "\n".join(pptx_text_values(content))


def pptx_slide_texts(content: bytes) -> list[str]:
    presentation = Presentation(BytesIO(content))
    slide_texts: list[str] = []
    for slide in presentation.slides:
        values: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                values.append(shape.text)
        slide_texts.append("\n".join(values))
    return slide_texts


def w05_many_category_rows() -> list[tuple[object, ...]]:
    materials = (
        ["MAT-01-LONG-LABEL"] * 5
        + ["MAT-02"] * 4
        + ["MAT-03"] * 3
        + ["MAT-04"] * 3
        + ["MAT-05"] * 2
        + ["MAT-06"] * 2
        + ["MAT-07"] * 2
        + ["MAT-08"] * 2
        + ["MAT-09"]
        + ["MAT-10"]
    )
    return [
        (f"45{index:03d}", f"SHIP-{index % 4}", material, 1, "sap", "n")
        for index, material in enumerate(materials, start=1)
    ]


class PresentationPlannerContractTests(unittest.TestCase):
    def test_derive_presentation_title_shortens_raw_question_to_german_title(self) -> None:
        raw_question = (
            "Which order numbers have shipment records but no matching invoice records, "
            "including ship-to party and customer material groups for the management deck?"
        )
        title = derive_presentation_title(orchestrator_record(user_question=raw_question))

        self.assertLessEqual(len(title), 52)
        self.assertNotEqual(title, raw_question)
        self.assertNotIn(raw_question, title)
        self.assertEqual(title, "Sendungen ohne passende Rechnung")

    def test_derive_presentation_title_uses_generic_fallback(self) -> None:
        self.assertEqual(derive_presentation_title({}), "Logistik-Auswertung")

    def test_format_management_number_uses_german_management_format(self) -> None:
        cases = [
            (12345, False, "12.345"),
            (12345.67, False, "12.345,67"),
            (1_250_000, False, "1,3 Mio."),
            (1_000_000, False, "1 Mio."),
            (2_500_000_000, False, "2,5 Mrd."),
            (0.1234, True, "12,3%"),
            (12, True, "12%"),
        ]

        for value, percentage, expected in cases:
            with self.subTest(value=value, percentage=percentage):
                self.assertEqual(format_management_number(value, percentage=percentage), expected)

    def test_planner_dataclasses_convert_to_json_serializable_dicts(self) -> None:
        bullet = ExecutiveBullet(
            spans=[
                TextSpan("12.345", bold=True),
                TextSpan(" Sendungen ohne passende Rechnung"),
            ]
        )
        chart = EvidenceChartPlan(
            chart_type="top_n_bar",
            title="Top Materialgruppen",
            rows=[{"label": "MAT-1", "value": 3}],
            orientation="horizontal",
            fallback_reason="",
        )
        table_page = EvidenceTablePage(
            page_number=1,
            columns=["order_number"],
            rows=[{"order_number": "1001"}],
            row_range_label="Zeilen 1-1 von 1",
            notes=["Zeilen 1-1 von 1"],
        )
        audit = PlanningAudit(
            planning_mode="deterministic",
            selected_chart_types=["top_n_bar"],
            row_truncated=False,
            column_truncated=False,
            fallback_reasons=[],
        )
        plan = PresentationPlan(
            title="Sendungen ohne passende Rechnung",
            executive_bullets=[bullet],
            charts=[chart],
            table_pages=[table_page],
            audit=audit,
        )

        payload = plan.to_dict()

        json.dumps(payload)
        self.assertEqual(payload["executive_bullets"][0]["text"], "12.345 Sendungen ohne passende Rechnung")
        self.assertEqual(payload["charts"][0]["chart_type"], "top_n_bar")
        self.assertEqual(payload["audit"]["planning_mode"], "deterministic")

    def test_planner_import_does_not_load_ui_pptx_database_or_model_clients(self) -> None:
        script = textwrap.dedent(
            """
            import sys

            import src.agent.presentation_planner  # noqa: F401

            forbidden = [
                "streamlit",
                "streamlit_app",
                "pptx",
                "anthropic",
                "langchain",
                "src.agent.db",
                "src.backends.factory",
            ]
            unexpected = [name for name in forbidden if name in sys.modules]
            if unexpected:
                raise SystemExit("unexpected imports: " + ", ".join(unexpected))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


def w05_result(rows: list[tuple[object, ...]], *, row_count: int | None = None) -> dict[str, object]:
    return query_result(
        ["order_number", "shiptoparty", "customer_material", "shipment_rows", "source_system", "extra_note"],
        rows,
    ) | {"row_count": row_count if row_count is not None else len(rows)}


def w05_record(rows: list[tuple[object, ...]], *, row_count: int | None = None) -> dict[str, object]:
    result = w05_result(rows, row_count=row_count)
    reporting = reporting_result(result, chart_render_allowed=False)
    reporting["chart_plan"] = {"chart_type": "none", "render_allowed": False, "reason": "table only"}
    return orchestrator_record(
        user_question="Which order numbers have shipment records but no matching invoice records?",
        query_result=result,
        row_count=result["row_count"],
        reporting_result=reporting,
        source_tables=["wuerth.shipments", "wuerth.invoices"],
    )


class PresentationPlannerEvidenceTests(unittest.TestCase):
    def test_table_pages_preserve_sql_order_and_visible_truncation_notes(self) -> None:
        rows = [
            (f"4500{index}", f"SHIP-{index % 3}", f"MAT-{index % 4}", index, "sap", f"note-{index}")
            for index in range(1, 13)
        ]

        plan = build_presentation_plan(record=w05_record(rows, row_count=50))

        first_page = plan.table_pages[0]
        self.assertEqual(first_page.row_range_label, "Zeilen 1-10 von 50")
        self.assertEqual(first_page.rows[0]["order_number"], rows[0][0])
        self.assertEqual(first_page.rows[-1]["order_number"], rows[9][0])
        self.assertEqual(len(first_page.columns), 5)
        self.assertIn("extra_note", first_page.hidden_columns)
        self.assertIn("Weitere Spalten ausgeblendet", " ".join(first_page.notes))
        self.assertTrue(plan.audit.row_truncated)
        self.assertTrue(plan.audit.column_truncated)

    def test_w05_profile_builds_management_bullets_from_order_material_and_shipto(self) -> None:
        rows = [
            ("45001", "SHIP-A", "MAT-A", 3, "sap", "a"),
            ("45001", "SHIP-A", "MAT-A", 2, "sap", "b"),
            ("45002", "SHIP-A", "MAT-B", 1, "sap", "c"),
            ("45003", "SHIP-B", "MAT-A", 4, "sap", "d"),
        ]

        plan = build_presentation_plan(record=w05_record(rows))
        bullet_text = "\n".join(bullet.text for bullet in plan.executive_bullets)

        self.assertIn("3 Auftraege", bullet_text)
        self.assertIn("4 Evidenzzeilen", bullet_text)
        self.assertIn("10 Sendungszeilen", bullet_text)
        self.assertIn("45001", bullet_text)
        self.assertIn("MAT-A", bullet_text)
        self.assertIn("SHIP-A", bullet_text)

    def test_top_n_categorical_chart_aggregates_excess_categories_as_sonstige(self) -> None:
        materials = (
            ["MAT-01" * 7] * 5
            + ["MAT-02"] * 4
            + ["MAT-03"] * 3
            + ["MAT-04"] * 3
            + ["MAT-05"] * 2
            + ["MAT-06"] * 2
            + ["MAT-07"] * 2
            + ["MAT-08"] * 2
            + ["MAT-09"]
            + ["MAT-10"]
        )
        rows = [
            (f"45{index:03d}", f"SHIP-{index % 4}", material, 1, "sap", "n")
            for index, material in enumerate(materials, start=1)
        ]

        plan = build_presentation_plan(record=w05_record(rows))
        chart = next(chart for chart in plan.charts if chart.chart_type == "top_n_bar")
        labels = [row["label"] for row in chart.rows]
        values = [row["value"] for row in chart.rows]

        self.assertEqual(chart.orientation, "horizontal")
        self.assertEqual(labels.count("Sonstige"), 1)
        self.assertLessEqual(max(len(label) for label in labels), 32)
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertIn("top_n_bar", plan.audit.selected_chart_types)

    def test_unsupported_chart_shape_returns_german_fallback_and_table_plan(self) -> None:
        result = query_result(["region", "shipment_count", "cost"], [("Sued", 90, 12), ("Nord", 80, 8)])
        reporting = reporting_result(result)
        reporting["chart_plan"] = {
            "chart_type": "heatmap",
            "render_allowed": True,
            "x_axis": "region",
            "y_axis": "shipment_count",
            "reason": "User requested heatmap.",
        }

        plan = build_presentation_plan(
            record=orchestrator_record(query_result=result, row_count=2, reporting_result=reporting)
        )

        fallback = next(chart for chart in plan.charts if chart.chart_type == "none")
        self.assertIn("nicht unterstuetzt", fallback.fallback_reason)
        self.assertIn("Tabelle", fallback.fallback_reason)
        self.assertTrue(plan.table_pages)
        self.assertIn(fallback.fallback_reason, plan.audit.fallback_reasons)

    def test_empty_result_planning_is_deterministic_while_export_eligibility_stays_separate(self) -> None:
        result = {"columns": ["region", "shipment_count"], "rows": [], "row_count": 0}
        record = orchestrator_record(query_result=result, row_count=0)

        plan = build_presentation_plan(record=record)
        eligibility = can_export_presentation(record)

        self.assertEqual(plan.audit.planning_mode, "deterministic")
        self.assertFalse(plan.table_pages)
        self.assertTrue(plan.audit.fallback_reasons)
        self.assertFalse(eligibility.can_export)
        self.assertIn("row", eligibility.reason)


class PresentationPlanningJsonModeTests(unittest.TestCase):
    def _valid_json_plan(self) -> str:
        return json.dumps({
            "title": "Regionale Lieferanalyse",
            "language": "de",
            "executive_bullets": [
                {
                    "spans": [
                        {"text": "90", "bold": True},
                        {"text": " Lieferungen in Sued bilden den Spitzenwert.", "bold": False},
                    ]
                }
            ],
            "charts": [
                {
                    "chart_type": "top_n_bar",
                    "title": "Top Regionen",
                    "rows": [
                        {"label": "Sued", "value": 90},
                        {"label": "Nord", "value": 75},
                    ],
                    "orientation": "horizontal",
                    "render_allowed": True,
                    "x_label": "Region",
                    "y_label": "Lieferungen",
                    "notes": ["Validierte Ergebnisdaten"],
                    "category_column": "region",
                }
            ],
            "table_pages": [
                {
                    "page_number": 1,
                    "columns": ["region", "shipment_count"],
                    "rows": [
                        {"region": "Sued", "shipment_count": "90"},
                        {"region": "Nord", "shipment_count": "75"},
                    ],
                    "row_range_label": "Zeilen 1-2 von 9",
                    "notes": ["Zeilen 1-2 von 9"],
                    "hidden_columns": [],
                    "start_row": 1,
                    "end_row": 2,
                    "total_rows": 9,
                }
            ],
            "caveats": ["Keine Ursachenableitung aus Aggregaten."],
            "warnings": ["planner_note"],
            "audit": {"fallback_reasons": []},
        })

    def test_from_env_defaults_to_deterministic_and_never_calls_fake_invocation(self) -> None:
        calls: list[str] = []

        with patch.dict(os.environ, {}, clear=True):
            config = PresentationPlanningConfig.from_env()
            plan = build_presentation_plan(
                record=valid_record(),
                config=config,
                planner_invocation=lambda prompt: calls.append(prompt) or self._valid_json_plan(),
            )

        self.assertEqual(config.mode, "deterministic")
        self.assertEqual(plan.audit.planning_mode, "deterministic")
        self.assertEqual(calls, [])

    def test_llm_mode_applies_valid_json_after_strict_local_validation(self) -> None:
        captured: dict[str, str] = {}

        def fake_invocation(prompt: str) -> str:
            captured["prompt"] = prompt
            return self._valid_json_plan()

        with patch.dict(
            os.environ,
            {
                "PRESENTATION_PLANNING_MODE": "llm",
                "PRESENTATION_PLANNING_MAX_ROWS": "2",
            },
            clear=False,
        ):
            config = PresentationPlanningConfig.from_env()
            plan = build_presentation_plan(
                record=valid_record(),
                config=config,
                planner_invocation=fake_invocation,
            )

        payload = json.loads(captured["prompt"].split("PLANNER_PAYLOAD_JSON:\n", 1)[1])
        self.assertEqual(config.mode, "llm")
        self.assertEqual(plan.audit.planning_mode, "llm")
        self.assertEqual(plan.title, "Regionale Lieferanalyse")
        self.assertEqual(plan.executive_bullets[0].spans[0].text, "90")
        self.assertTrue(plan.executive_bullets[0].spans[0].bold)
        self.assertEqual(plan.charts[0].chart_type, "top_n_bar")
        self.assertEqual(plan.charts[0].category_column, "region")
        self.assertEqual(plan.caveats, ["Keine Ursachenableitung aus Aggregaten."])
        self.assertLessEqual(len(payload["result_sample"]["rows"]), 2)
        self.assertIn("column_profiles", payload)
        self.assertIn("aggregates", payload)
        self.assertIn("deterministic_defaults", payload)
        self.assertNotIn("\x00", json.dumps(payload))

    def test_llm_mode_falls_back_for_invalid_refused_malformed_or_over_budget_output(self) -> None:
        cases: list[tuple[str, object]] = [
            ("invalid_json", "{not-json"),
            ("missing_key", json.dumps({"title": "Unvollstaendig"})),
            ("refused", json.dumps({"refusal": "I cannot comply."})),
            (
                "unsupported_chart",
                json.dumps({
                    **json.loads(self._valid_json_plan()),
                    "charts": [{"chart_type": "heatmap", "title": "Heatmap"}],
                }),
            ),
            (
                "over_budget_title",
                json.dumps({
                    **json.loads(self._valid_json_plan()),
                    "title": "x" * 90,
                }),
            ),
            ("exception", TimeoutError("SECRET_ORDER_45001_TOKEN")),
        ]

        for name, response in cases:
            with self.subTest(name=name):
                calls: list[str] = []

                def fake_invocation(prompt: str) -> str:
                    calls.append(prompt)
                    if isinstance(response, Exception):
                        raise response
                    return str(response)

                config = PresentationPlanningConfig(mode="llm")
                plan = build_presentation_plan(
                    record=valid_record(),
                    config=config,
                    planner_invocation=fake_invocation,
                )

                self.assertEqual(len(calls), 1)
                self.assertEqual(plan.audit.planning_mode, "fallback")
                self.assertEqual(plan.title, "Lieferungen nach Region")
                self.assertTrue(any("planner_fallback" in warning for warning in plan.warnings))
                self.assertTrue(plan.audit.fallback_reasons)
                if name == "exception":
                    warning_text = json.dumps(plan.warnings + plan.audit.fallback_reasons)
                    self.assertIn("planner_exception:TimeoutError", warning_text)
                    self.assertNotIn("SECRET_ORDER_45001_TOKEN", warning_text)

    def test_non_llm_mode_is_the_only_path_that_can_call_injected_invocation(self) -> None:
        calls: list[str] = []

        config = PresentationPlanningConfig(mode="experimental")
        plan = build_presentation_plan(
            record=valid_record(),
            config=config,
            planner_invocation=lambda prompt: calls.append(prompt) or self._valid_json_plan(),
        )

        self.assertEqual(plan.audit.planning_mode, "deterministic")
        self.assertEqual(calls, [])

    def test_env_example_documents_non_secret_planner_toggles(self) -> None:
        env_text = Path(".env.example").read_text(encoding="utf-8")

        self.assertIn("PRESENTATION_EXPORT_MODE=deterministic", env_text)
        self.assertIn("PRESENTATION_PLANNING_MODE=deterministic", env_text)
        self.assertIn("PRESENTATION_PLANNING_MODEL=claude-sonnet-4-6", env_text)
        self.assertIn("PRESENTATION_PLANNING_TIMEOUT_SECONDS=30", env_text)
        self.assertIn("PRESENTATION_PLANNING_MAX_ROWS=50", env_text)
        self.assertIn("PRESENTATION_PLANNING_MAX_TOKENS=2048", env_text)
        self.assertNotIn("PRESENTATION_PLANNING_API_KEY", env_text)
        self.assertNotIn("OPENAI_API_KEY", env_text)

    def test_deterministic_export_remains_available_when_json_planner_fails(self) -> None:
        def failing_invocation(prompt: str) -> str:
            raise RuntimeError("SECRET_ORDER_45001_TOKEN")

        with patch.dict(os.environ, {"PRESENTATION_PLANNING_MODE": "llm"}, clear=False):
            export = build_deterministic_presentation_export(
                record=valid_record(),
                planner_invocation=failing_invocation,
            )

        self.assertTrue(export.available, export.warnings)
        Presentation(BytesIO(export.content))
        self.assertIsNotNone(export.deck_spec)
        self.assertEqual(export.deck_spec.metadata["planning_mode"], "fallback")
        self.assertIn("planner_exception:RuntimeError", export.deck_spec.metadata["planning_fallback_reasons"])
        self.assertTrue(any("planner_fallback" in warning for warning in export.warnings))
        self.assertEqual(len(export.warnings), len(set(export.warnings)))
        self.assertTrue(any("embedded object" in warning.lower() for warning in export.warnings))
        warning_text = json.dumps(
            [
                *export.warnings,
                export.deck_spec.metadata,
            ],
            sort_keys=True,
        )
        self.assertNotIn("SECRET_ORDER_45001_TOKEN", warning_text)

    def test_planner_fallback_metadata_excludes_unbounded_result_rows(self) -> None:
        rows = [
            (f"Region-{index}", index)
            for index in range(1, 15)
        ]
        result = query_result(["region", "shipment_count"], rows)

        with patch.dict(os.environ, {"PRESENTATION_PLANNING_MODE": "llm"}, clear=False):
            spec = build_slide_deck_spec(
                record=orchestrator_record(query_result=result, row_count=14),
                planner_invocation=lambda prompt: "{not-json",
            )

        metadata_text = json.dumps(spec.metadata, sort_keys=True)
        self.assertEqual(spec.metadata["planning_mode"], "fallback")
        self.assertIn("planner_fallback_reasons", spec.metadata)
        self.assertIn("invalid_json", spec.metadata["planning_fallback_reasons"])
        self.assertNotIn("Region-14", metadata_text)
        self.assertNotIn("shipment_count", spec.metadata["planner_warning_codes"])


class PresentationExportPlanRenderingTests(unittest.TestCase):
    def test_build_slide_deck_spec_calls_planner_after_eligibility_passes(self) -> None:
        with patch(
            "src.agent.presentation_export.build_presentation_plan",
            wraps=build_presentation_plan,
        ) as planner:
            spec = build_slide_deck_spec(record=valid_record())

        planner.assert_called_once()
        self.assertEqual(spec.title, "Lieferungen nach Region")
        self.assertEqual(spec.metadata["planning_mode"], "deterministic")

    def test_build_slide_deck_spec_rejects_ineligible_record_before_planning(self) -> None:
        with patch("src.agent.presentation_export.build_presentation_plan") as planner:
            with self.assertRaisesRegex(Exception, "execution"):
                build_slide_deck_spec(record=orchestrator_record(execution_success=False))

        planner.assert_not_called()

    def test_reopened_pptx_uses_german_labels_and_visible_table_notes(self) -> None:
        rows = [
            (f"4500{index}", f"SHIP-{index % 3}", f"MAT-{index % 4}", index, "sap", f"note-{index}")
            for index in range(1, 13)
        ]

        export = build_deterministic_presentation_export(record=w05_record(rows, row_count=50))

        self.assertTrue(export.available, export.warnings)
        rendered_text = pptx_text(export.content)
        self.assertIn("Management-Zusammenfassung", rendered_text)
        self.assertIn("Kennzahlen", rendered_text)
        self.assertIn("Evidenz", rendered_text)
        self.assertIn("Datenbasis und Grenzen", rendered_text)
        self.assertIn("Technischer Anhang", rendered_text)
        self.assertIn("Zeilen 1-10 von 50", rendered_text)
        self.assertIn("Weitere Spalten ausgeblendet", rendered_text)

    def test_cover_uses_short_planned_title_instead_of_long_raw_question(self) -> None:
        raw_question = (
            "Which order numbers have shipment records but no matching invoice records, "
            "including ship-to party and customer material groups for the management deck?"
        )
        rows = [("45001", "SHIP-A", "MAT-A", 3, "sap", "a")]

        export = build_deterministic_presentation_export(
            record=w05_record(rows) | {"user_question": raw_question}
        )

        self.assertTrue(export.available, export.warnings)
        first_slide_text = "\n".join(pptx_text_values(export.content)[:4])
        self.assertIn("Sendungen ohne passende Rechnung", first_slide_text)
        self.assertNotIn(raw_question, first_slide_text)

    def test_unsupported_chart_fallback_remains_exportable_and_visible(self) -> None:
        result = query_result(["region", "shipment_count", "cost"], [("Sued", 90, 12), ("Nord", 80, 8)])
        reporting = reporting_result(result)
        reporting["chart_plan"] = {
            "chart_type": "heatmap",
            "render_allowed": True,
            "x_axis": "region",
            "y_axis": "shipment_count",
            "reason": "User requested heatmap.",
        }

        export = build_deterministic_presentation_export(
            record=orchestrator_record(query_result=result, row_count=2, reporting_result=reporting)
        )

        self.assertTrue(export.available, export.warnings)
        rendered_text = pptx_text(export.content)
        self.assertIn("Darstellungshinweis", rendered_text)
        self.assertIn("nicht unterstuetzt", rendered_text)


class PresentationExportRichEvidenceTests(unittest.TestCase):
    def test_executive_summary_uses_bold_runs_and_keeps_bullet_text_readable(self) -> None:
        rows = [
            ("45001", "SHIP-A", "MAT-A", 3, "sap", "a"),
            ("45001", "SHIP-A", "MAT-A", 2, "sap", "b"),
            ("45002", "SHIP-A", "MAT-B", 1, "sap", "c"),
            ("45003", "SHIP-B", "MAT-A", 4, "sap", "d"),
        ]

        export = build_deterministic_presentation_export(record=w05_record(rows))

        self.assertTrue(export.available, export.warnings)
        presentation = Presentation(BytesIO(export.content))
        summary_slide = next(
            slide for slide in presentation.slides if "Management-Zusammenfassung" in "\n".join(
                shape.text for shape in slide.shapes if getattr(shape, "has_text_frame", False)
            )
        )
        bold_text: list[str] = []
        full_text: list[str] = []
        for shape in summary_slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            for paragraph in shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    full_text.append(run.text)
                    if run.font.bold:
                        bold_text.append(run.text)

        joined_text = "".join(full_text)
        self.assertIn("Auftraege ohne passende Rechnung", joined_text)
        self.assertTrue(any(text.strip() in {"3", "4", "10", "45001", "MAT-A", "SHIP-A"} for text in bold_text))

    def test_top_n_categorical_record_produces_chart_image_and_sonstige_metadata(self) -> None:
        record = w05_record(w05_many_category_rows())

        spec = build_slide_deck_spec(record=record)
        chart_slide = next(slide for slide in spec.slides if slide.slide_type == "chart_evidence")

        self.assertEqual(chart_slide.metadata["chart_type"], "top_n_bar")
        self.assertEqual(chart_slide.metadata["chart_orientation"], "horizontal")
        self.assertTrue(any(row[0] == "Sonstige" for row in chart_slide.table_rows))

        export = build_deterministic_presentation_export(record=record)
        self.assertTrue(export.available, export.warnings)
        presentation = Presentation(BytesIO(export.content))
        chart_ppt_slide = next(
            slide for slide, text in zip(presentation.slides, pptx_slide_texts(export.content))
            if chart_slide.title in text
        )
        self.assertTrue(any(getattr(shape, "shape_type", None) == 13 for shape in chart_ppt_slide.shapes))

    def test_top_n_chart_rendering_keeps_pptx_bytes_deterministic(self) -> None:
        record = w05_record(w05_many_category_rows())

        first = build_deterministic_presentation_export(record=record)
        second = build_deterministic_presentation_export(record=record)

        self.assertTrue(first.available, first.warnings)
        self.assertTrue(second.available, second.warnings)
        self.assertEqual(first.content, second.content)

    def test_chart_image_failure_falls_back_to_visible_text(self) -> None:
        with patch("src.agent.presentation_export._chart_image", return_value=None):
            export = build_deterministic_presentation_export(record=w05_record(w05_many_category_rows()))

        self.assertTrue(export.available, export.warnings)
        rendered_text = pptx_text(export.content)
        self.assertIn("Diagramm konnte nicht gerendert werden", rendered_text)
        self.assertIn("Evidenzwerte werden tabellarisch gezeigt", rendered_text)

    def test_validate_slide_deck_spec_checks_rich_body_runs(self) -> None:
        valid_spec = SlideDeckSpec(
            title="Deck",
            slides=[
                SlideSpec(
                    slide_type="cover",
                    layout_name="agent_01_cover",
                    title="Cover",
                    body=["Untertitel"],
                ),
                SlideSpec(
                    slide_type="executive_summary",
                    layout_name="agent_02_summary",
                    title="Management-Zusammenfassung",
                    body=["12 Auftraege betroffen"],
                    rich_body=[
                        [
                            {"text": "12", "bold": True},
                            {"text": " Auftraege betroffen", "bold": False},
                        ]
                    ],
                ),
            ],
        )
        invalid_spec = SlideDeckSpec(
            title="Deck",
            slides=[
                SlideSpec(
                    slide_type="cover",
                    layout_name="agent_01_cover",
                    title="Cover",
                    body=["Untertitel"],
                ),
                SlideSpec(
                    slide_type="executive_summary",
                    layout_name="agent_02_summary",
                    title="Management-Zusammenfassung",
                    body=["12 Auftraege betroffen"],
                    rich_body=[[{"text": "13", "bold": True}]],
                ),
            ],
        )

        self.assertFalse([error for error in validate_slide_deck_spec(valid_spec) if "rich text" in error.lower()])
        self.assertTrue(any("rich text" in error.lower() for error in validate_slide_deck_spec(invalid_spec)))


class PresentationExportRegressionTests(unittest.TestCase):
    def test_w05_style_reopened_deck_keeps_readable_evidence_and_bold_summary(self) -> None:
        raw_question = (
            "Which order numbers have shipment records but no matching invoice records, "
            "including ship-to party, customer material, shipment rows, source details, "
            "and a management explanation that would be much too long for a cover title?"
        )
        rows = [
            (
                order_number,
                shiptoparty,
                customer_material,
                shipment_rows,
                source_system,
                (
                    "Sehr langer Pruefhinweis fuer die Regression mit Zusatztext, "
                    f"der nicht die Folien ueberlaufen darf: {index}"
                ),
            )
            for index, (
                order_number,
                shiptoparty,
                customer_material,
                shipment_rows,
                source_system,
                _note,
            ) in enumerate(w05_many_category_rows(), start=1)
        ]
        record = w05_record(rows, row_count=50) | {
            "user_question": raw_question,
            "final_answer": "Sehr lange Antwort, die nur als Quelle fuer kurze Foliencopy dienen darf.",
        }

        with patch.dict(os.environ, {"PRESENTATION_EXPORT_MODE": "deterministic"}, clear=False):
            export = build_presentation_export(record=record)

        self.assertTrue(export.available, export.warnings)
        self.assertLessEqual(len(export.deck_spec.title), 52)
        presentation = Presentation(BytesIO(export.content))
        slide_texts = pptx_slide_texts(export.content)
        rendered_text = "\n".join(slide_texts)

        self.assertIn("Sendungen ohne passende Rechnung", slide_texts[0])
        self.assertNotIn(raw_question, slide_texts[0])
        self.assertIn("Management-Zusammenfassung", rendered_text)
        self.assertIn("Kennzahlen", rendered_text)
        self.assertIn("Zeilen 1-10 von 50", rendered_text)
        self.assertIn("Weitere Spalten ausgeblendet", rendered_text)
        self.assertIn("Diagramm aus validierten Ergebnisdaten.", rendered_text)
        self.assertIn("Sonstige", rendered_text)

        summary_slide = next(
            slide for slide, text in zip(presentation.slides, slide_texts)
            if "Management-Zusammenfassung" in text
        )
        bold_runs = [
            run.text.strip()
            for shape in summary_slide.shapes
            if getattr(shape, "has_text_frame", False)
            for paragraph in shape.text_frame.paragraphs
            for run in paragraph.runs
            if run.font.bold and run.text.strip()
        ]
        self.assertTrue(any(text == "25" for text in bold_runs), bold_runs)

    def test_empty_result_export_remains_unavailable_with_existing_reason(self) -> None:
        result = {"columns": ["region", "shipment_count"], "rows": [], "row_count": 0}
        record = orchestrator_record(
            query_result=result,
            row_count=0,
            reporting_result=reporting_result(result),
        )

        with patch.dict(os.environ, {"PRESENTATION_EXPORT_MODE": "deterministic"}, clear=False):
            export = build_presentation_export(record=record)

        self.assertFalse(export.available)
        self.assertEqual(export.content, b"")
        self.assertEqual(export.unavailable_reason, "missing_query_rows")

    def test_unsupported_chart_shape_stays_available_with_visible_german_fallback(self) -> None:
        result = query_result(
            ["region", "shipment_count", "cost"],
            [("Sued", 90, 12), ("Nord", 80, 8), ("West", 70, 5)],
        )
        reporting = reporting_result(result)
        reporting["chart_plan"] = {
            "chart_type": "heatmap",
            "render_allowed": True,
            "x_axis": "region",
            "y_axis": "shipment_count",
            "reason": "User requested heatmap.",
        }

        with patch.dict(os.environ, {"PRESENTATION_EXPORT_MODE": "deterministic"}, clear=False):
            export = build_presentation_export(
                record=orchestrator_record(
                    query_result=result,
                    row_count=3,
                    reporting_result=reporting,
                )
            )

        self.assertTrue(export.available, export.warnings)
        rendered_text = pptx_text(export.content)
        self.assertIn("Darstellungshinweis", rendered_text)
        self.assertIn("Diagrammtyp heatmap", rendered_text)
        self.assertIn("nicht unterstuetzt", rendered_text)
        self.assertIn("Die Evidenz wird als geordnete Tabelle gezeigt.", rendered_text)


def generated_pptx_bytes() -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    slide.shapes.title.text = "Generated Wuerth Deck"
    output = BytesIO()
    presentation.save(output)
    return output.getvalue()


class FakeClaudeFiles:
    def __init__(self, *, generated_content: bytes | None = None) -> None:
        self.generated_content = generated_content or generated_pptx_bytes()
        self.uploads: list[dict[str, object]] = []
        self.deleted: list[str] = []

    def upload(self, *, file: object, **kwargs: object) -> object:
        if isinstance(file, tuple):
            filename = str(file[0])
            handle = file[1]
            mime_type = str(file[2]) if len(file) > 2 else ""
        else:
            filename = str(getattr(file, "name", "uploaded-file"))
            handle = file
            mime_type = ""
        content = handle.read() if hasattr(handle, "read") else b""
        if isinstance(content, str):
            content = content.encode("utf-8")
        file_id = f"upload-{len(self.uploads) + 1}"
        self.uploads.append({
            "file_id": file_id,
            "filename": filename,
            "mime_type": mime_type,
            "content": content,
            "kwargs": kwargs,
        })
        return types.SimpleNamespace(id=file_id, filename=filename, mime_type=mime_type)

    def retrieve_metadata(self, file_id: str, **kwargs: object) -> object:
        return types.SimpleNamespace(
            id=file_id,
            filename="claude-generated-wuerth.pptx",
            mime_type=PPTX_MIME_TYPE,
        )

    def download(self, file_id: str, **kwargs: object) -> object:
        return types.SimpleNamespace(read=lambda: self.generated_content)

    def delete(self, file_id: str, **kwargs: object) -> object:
        self.deleted.append(file_id)
        return types.SimpleNamespace(id=file_id, deleted=True)


class FakeClaudeMessages:
    def __init__(self, *, file_id: str = "generated-pptx", raise_error: Exception | None = None) -> None:
        self.file_id = file_id
        self.raise_error = raise_error
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.raise_error is not None:
            raise self.raise_error
        return types.SimpleNamespace(
            stop_reason="end_turn",
            content=[
                types.SimpleNamespace(
                    type="bash_code_execution_tool_result",
                    content=types.SimpleNamespace(
                        type="bash_code_execution_result",
                        content=[types.SimpleNamespace(file_id=self.file_id)],
                    ),
                )
            ],
            container=types.SimpleNamespace(id="container-1"),
        )


class FakeClaudeClient:
    def __init__(
        self,
        *,
        generated_content: bytes | None = None,
        messages: FakeClaudeMessages | None = None,
    ) -> None:
        self.beta = types.SimpleNamespace(
            files=FakeClaudeFiles(generated_content=generated_content),
            messages=messages or FakeClaudeMessages(),
        )


class PresentationExportSuccessTests(unittest.TestCase):
    def test_successful_record_returns_dynamic_pptx_export(self) -> None:
        export = build_deterministic_presentation_export(record=valid_record())

        self.assertTrue(export.available)
        self.assertIsInstance(export.content, bytes)
        self.assertGreater(len(export.content), 0)
        self.assertTrue(export.filename.endswith(".pptx"))
        self.assertEqual(export.mime_type, PPTX_MIME_TYPE)
        self.assertGreater(export.slide_count, 0)
        self.assertNotEqual(export.slide_count, 9)

    def test_generated_pptx_bytes_reopen_without_powerpoint(self) -> None:
        export = build_deterministic_presentation_export(record=valid_record())

        presentation = Presentation(BytesIO(export.content))

        self.assertEqual(len(presentation.slides), export.slide_count)
        self.assertGreater(len(presentation.slides), 1)

    def test_successful_record_produces_repeatable_pptx_bytes(self) -> None:
        first = build_deterministic_presentation_export(record=valid_record())
        second = build_deterministic_presentation_export(record=valid_record())

        self.assertTrue(first.available)
        self.assertTrue(second.available)
        self.assertEqual(first.content, second.content)
        with zipfile.ZipFile(BytesIO(first.content)) as package:
            self.assertEqual(package.namelist(), sorted(package.namelist()))
            self.assertTrue(
                all(info.date_time == FIXED_PPTX_TIMESTAMP for info in package.infolist())
            )

    def test_rendered_deck_populates_named_template_placeholders(self) -> None:
        export = build_deterministic_presentation_export(record=valid_record())

        self.assertTrue(export.available)
        presentation = Presentation(BytesIO(export.content))
        text_values: list[str] = []
        has_table = False
        for slide in presentation.slides:
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    text_values.append(shape.text)
                if getattr(shape, "has_table", False):
                    has_table = True

        rendered_text = "\n".join(text_values)
        self.assertIn("Management-Zusammenfassung", rendered_text)
        self.assertIn("Kennzahlen", rendered_text)
        self.assertIn("Evidenz", rendered_text)
        self.assertIn("Lieferungen nach Region", rendered_text)
        self.assertNotIn("Zeige Lieferungen nach Region als Praesentation", rendered_text)
        self.assertTrue(has_table)
        for stale_fragment in (
            "Click to add",
            "Mastertextformat",
            "Mastertitelformat",
            "Master-Untertitelformat",
            "Inhalte ein",
            "Schlagwort",
            "Erlaeuterung",
        ):
            self.assertNotIn(stale_fragment, rendered_text)

    def test_missing_generated_at_and_run_id_use_deterministic_fallbacks(self) -> None:
        record = orchestrator_record(run_id="", generated_at="")

        export = build_deterministic_presentation_export(record=record)
        spec = build_slide_deck_spec(record=record)

        self.assertTrue(export.available)
        self.assertEqual(export.filename, "wuerth_logistics_analysis.pptx")
        metadata_slide = next(slide for slide in spec.slides if slide.layout_name == "agent_08_appendix_metadata")
        self.assertIn("Erstellt am: nicht erfasst", metadata_slide.body)

    def test_slide_deck_spec_is_ordered_dynamic_and_excludes_default_closing(self) -> None:
        spec = build_slide_deck_spec(record=valid_record())

        layout_names = [slide.layout_name for slide in spec.slides]

        self.assertEqual(layout_names[0], "agent_01_cover")
        self.assertIn("agent_02_summary", layout_names)
        self.assertIn("agent_03_three_cards", layout_names)
        self.assertEqual(layout_names.count("agent_05_full_content"), 2)
        self.assertIn("agent_07_caveats_sources", layout_names)
        self.assertIn("agent_08_appendix_metadata", layout_names)
        self.assertNotIn("agent_09_closing", layout_names)
        self.assertNotEqual(layout_names, [
            "agent_01_cover",
            "agent_02_summary",
            "agent_03_three_cards",
            "agent_04_two_column",
            "agent_05_full_content",
            "agent_06_two_cards",
            "agent_07_caveats_sources",
            "agent_08_appendix_metadata",
            "agent_09_closing",
        ])

    def test_slide_deck_spec_includes_one_closing_when_requested(self) -> None:
        spec = build_slide_deck_spec(record=valid_record(), include_closing=True)

        layout_names = [slide.layout_name for slide in spec.slides]

        self.assertEqual(layout_names.count("agent_09_closing"), 1)
        self.assertEqual(layout_names[-1], "agent_09_closing")

    def test_backend_contract_does_not_import_streamlit_surfaces(self) -> None:
        script = textwrap.dedent(
            """
            import sys

            from src.agent.presentation_export import build_slide_deck_spec

            record = {
                "run_id": "subprocess-boundary",
                "user_question": "Boundary check",
                "query_result": {
                    "columns": ["region", "shipment_count"],
                    "rows": [("Sued", 90)],
                    "row_count": 1,
                },
                "row_count": 1,
                "execution_success": True,
                "validation_success": True,
                "sql_valid": True,
                "source_tables": ["wuerth.shipments"],
                "reporting_result": {
                    "summary": "Kurzantwort: Test.",
                    "interpretation": "Test.",
                    "chart_plan": {"render_allowed": False},
                    "kpi_cards": [],
                    "caveats": [],
                    "display_notes": [],
                },
            }
            build_slide_deck_spec(record=record)
            unexpected = [name for name in ("streamlit", "streamlit_app") if name in sys.modules]
            if unexpected:
                raise SystemExit("unexpected imports: " + ", ".join(unexpected))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_unsupported_chart_plan_is_rendered_as_visible_fallback(self) -> None:
        result = query_result(["region", "shipment_count"], [("Sued", 90), ("Nord", 75)])
        reporting = reporting_result(result)
        reporting["chart_plan"] = {
            "chart_type": "heatmap",
            "title": "Unsupported chart",
            "render_allowed": True,
            "x_axis": "region",
            "y_axis": "shipment_count",
        }

        spec = build_slide_deck_spec(
            record=orchestrator_record(query_result=result, reporting_result=reporting, row_count=2)
        )

        fallback_slides = [
            slide for slide in spec.slides
            if slide.slide_type == "caveats_sources" and slide.title == "Darstellungshinweis"
        ]
        self.assertTrue(fallback_slides)
        self.assertTrue(any("nicht unterstuetzt" in " ".join(slide.body) for slide in fallback_slides))


class ClaudePresentationExportTests(unittest.TestCase):
    def test_default_export_mode_uses_claude_pptx_skill(self) -> None:
        client = FakeClaudeClient()

        with patch.dict(os.environ, {"PRESENTATION_EXPORT_MODE": "claude"}, clear=False):
            export = build_presentation_export(record=valid_record(), anthropic_client=client)

        self.assertTrue(export.available)
        self.assertEqual(export.mime_type, PPTX_MIME_TYPE)
        self.assertGreater(export.slide_count, 0)
        self.assertEqual(len(client.beta.messages.calls), 1)
        call = client.beta.messages.calls[0]
        self.assertIn("skills-2025-10-02", call["betas"])
        self.assertIn("files-api-2025-04-14", call["betas"])
        self.assertEqual(call["container"]["skills"][0]["skill_id"], "pptx")
        self.assertEqual(call["tools"][0]["type"], "code_execution_20250825")
        content_blocks = call["messages"][0]["content"]
        self.assertEqual([block["type"] for block in content_blocks], ["text", "container_upload", "container_upload"])
        prompt = content_blocks[0]["text"]
        self.assertIn("Use the uploaded Wuerth PowerPoint as the actual base template", prompt)
        self.assertIn("Do not dump all result rows", prompt)
        self.assertIn("4 to 6 slides", prompt)
        self.assertIn("No overlapping text", prompt)

    def test_claude_payload_caps_rows_and_preserves_evidence_profile(self) -> None:
        rows = [(f"order-{index % 3}", f"party-{index}", f"material-{index}") for index in range(20)]
        result = query_result(["order_number", "shiptoparty", "customer_material"], rows)
        client = FakeClaudeClient()

        with patch.dict(os.environ, {"PRESENTATION_MAX_ROWS_FOR_CLAUDE": "6"}, clear=False):
            export = build_claude_presentation_export(
                record=orchestrator_record(query_result=result, row_count=20),
                anthropic_client=client,
            )

        self.assertTrue(export.available)
        payload_upload = next(upload for upload in client.beta.files.uploads if upload["filename"] == "analysis_payload.json")
        payload = json.loads(payload_upload["content"].decode("utf-8"))
        self.assertEqual(payload["result"]["rows_in_payload"], 6)
        self.assertEqual(payload["result"]["profile"]["distinct_order_number"], 3)
        self.assertIn("raw row dump", payload["deck_rules"]["avoid"])

    def test_claude_generation_failure_is_not_deterministic_fallback(self) -> None:
        client = FakeClaudeClient(messages=FakeClaudeMessages(raise_error=RuntimeError("api down")))

        export = build_claude_presentation_export(record=valid_record(), anthropic_client=client)

        self.assertFalse(export.available)
        self.assertEqual(export.content, b"")
        self.assertEqual(export.unavailable_reason, "claude_generation_failed")

    def test_claude_output_missing_returns_structured_failure(self) -> None:
        class EmptyMessages(FakeClaudeMessages):
            def create(self, **kwargs: object) -> object:
                self.calls.append(kwargs)
                return types.SimpleNamespace(
                    stop_reason="end_turn",
                    content=[types.SimpleNamespace(type="text", text="I could not create the deck.")],
                    container=types.SimpleNamespace(id="container-1"),
                )

        client = FakeClaudeClient(messages=EmptyMessages())

        export = build_claude_presentation_export(record=valid_record(), anthropic_client=client)

        self.assertFalse(export.available)
        self.assertEqual(export.unavailable_reason, "claude_output_missing")
        self.assertTrue(any("could not create" in warning.lower() for warning in export.warnings))


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

    def test_render_failure_returns_structured_unavailable_export(self) -> None:
        with patch("src.agent.presentation_export._render_presentation", side_effect=RuntimeError("boom")):
            export = build_deterministic_presentation_export(record=valid_record())

        self.assert_unavailable_export(export, "render")
        self.assertIsNotNone(export.template_audit)
        self.assertIsNotNone(export.deck_spec)

    def test_corrupt_rendered_bytes_return_structured_unavailable_export(self) -> None:
        with patch("src.agent.presentation_export._render_presentation", return_value=b"not a pptx"):
            export = build_deterministic_presentation_export(record=valid_record())

        self.assert_unavailable_export(export, "render")
        self.assertIsNotNone(export.template_audit)
        self.assertIsNotNone(export.deck_spec)


class PresentationExportTemplateSafetyTests(unittest.TestCase):
    def test_real_template_validates_with_known_ole_warnings_only(self) -> None:
        audit = validate_template(template_path=DEFAULT_TEMPLATE_PATH)

        self.assertTrue(audit.available)
        self.assertFalse(audit.errors)
        self.assertGreaterEqual(len(audit.ole_entries), 1)
        self.assertTrue(any("ole" in warning.lower() for warning in audit.warnings))

    def test_macro_enabled_template_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            unsafe_template = Path(temp_dir) / "macro-template.pptx"
            shutil.copyfile(DEFAULT_TEMPLATE_PATH, unsafe_template)
            with zipfile.ZipFile(unsafe_template, "a") as package:
                package.writestr("ppt/vbaProject.bin", b"macro payload")

            audit = validate_template(template_path=unsafe_template)

        self.assertFalse(audit.available)
        self.assertTrue(audit.macro_entries)
        self.assertTrue(any("macro" in error.lower() for error in audit.errors))

    def test_external_relationship_template_is_blocked(self) -> None:
        external_relationship = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com/data.xlsx" TargetMode = "External"/>
</Relationships>
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            unsafe_template = Path(temp_dir) / "external-template.pptx"
            shutil.copyfile(DEFAULT_TEMPLATE_PATH, unsafe_template)
            with zipfile.ZipFile(unsafe_template, "a") as package:
                package.writestr("ppt/slides/_rels/slide999.xml.rels", external_relationship)

            audit = validate_template(template_path=unsafe_template)

        self.assertFalse(audit.available)
        self.assertTrue(audit.external_relationships)
        self.assertTrue(any("external" in error.lower() for error in audit.errors))

    def test_template_hash_mismatch_with_embedded_objects_warns_but_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            unsafe_template = Path(temp_dir) / "modified-ole-template.pptx"
            shutil.copyfile(DEFAULT_TEMPLATE_PATH, unsafe_template)
            with zipfile.ZipFile(unsafe_template, "a") as package:
                package.writestr("docProps/custom.xml", b"modified template marker")

            audit = validate_template(template_path=unsafe_template)

        self.assertTrue(audit.available)
        self.assertGreaterEqual(len(audit.ole_entries), 1)
        self.assertFalse(audit.errors)
        self.assertTrue(any("sha256 differs" in warning.lower() for warning in audit.warnings))

    def test_invalid_slide_specs_are_rejected_before_rendering(self) -> None:
        cases = [
            (
                "unsupported_slide_type",
                SlideDeckSpec(
                    title="Deck",
                    slides=[
                        SlideSpec(
                            slide_type="unsupported_type",
                            layout_name="agent_01_cover",
                            title="Cover",
                            body=["Question"],
                        )
                    ],
                ),
                "unsupported slide type",
            ),
            (
                "missing_required_content",
                SlideDeckSpec(
                    title="Deck",
                    slides=[
                        SlideSpec(
                            slide_type="executive_summary",
                            layout_name="agent_01_cover",
                            title="Summary",
                        )
                    ],
                ),
                "required content",
            ),
            (
                "text_budget_overflow",
                SlideDeckSpec(
                    title="Deck",
                    slides=[
                        SlideSpec(
                            slide_type="cover",
                            layout_name="agent_01_cover",
                            title="Cover",
                            body=["x" * 701],
                        )
                    ],
                ),
                "text budget",
            ),
            (
                "table_row_limit",
                SlideDeckSpec(
                    title="Deck",
                    slides=[
                        SlideSpec(
                            slide_type="table_evidence",
                            layout_name="agent_05_full_content",
                            title="Table",
                            table_columns=["region"],
                            table_rows=[["Sued"]] * 11,
                        )
                    ],
                ),
                "row limit",
            ),
            (
                "table_column_limit",
                SlideDeckSpec(
                    title="Deck",
                    slides=[
                        SlideSpec(
                            slide_type="table_evidence",
                            layout_name="agent_05_full_content",
                            title="Table",
                            table_columns=["c1", "c2", "c3", "c4", "c5", "c6", "c7"],
                            table_rows=[["1", "2", "3", "4", "5", "6", "7"]],
                        )
                    ],
                ),
                "column limit",
            ),
            (
                "unsupported_chart_payload",
                SlideDeckSpec(
                    title="Deck",
                    slides=[
                        SlideSpec(
                            slide_type="chart_evidence",
                            layout_name="agent_05_full_content",
                            title="Chart",
                            body=["Unsupported chart"],
                            metadata={"chart_type": "heatmap"},
                        )
                    ],
                ),
                "unsupported chart",
            ),
            (
                "chart_missing_result_data",
                SlideDeckSpec(
                    title="Deck",
                    slides=[
                        SlideSpec(
                            slide_type="chart_evidence",
                            layout_name="agent_05_full_content",
                            title="Chart",
                            body=["Chart"],
                            metadata={"chart_type": "bar"},
                        )
                    ],
                ),
                "chart evidence",
            ),
        ]

        for name, deck_spec, expected_error_part in cases:
            with self.subTest(name=name):
                errors = validate_slide_deck_spec(deck_spec)

                self.assertTrue(errors)
                self.assertTrue(
                    any(expected_error_part in error.lower() for error in errors),
                    errors,
                )


if __name__ == "__main__":
    unittest.main()
