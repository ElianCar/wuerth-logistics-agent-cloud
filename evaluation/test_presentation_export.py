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
    validate_slide_deck_spec,
    validate_template,
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
        self.assertIn("Executive Summary", rendered_text)
        self.assertIn("Result Snapshot", rendered_text)
        self.assertIn("Evidence Table", rendered_text)
        self.assertIn("Zeige Lieferungen nach Region als Praesentation", rendered_text)
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
        self.assertIn("Generated at: not recorded", metadata_slide.body)

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

    def test_unbacked_chart_plan_is_skipped_with_warning(self) -> None:
        result = query_result(["region", "shipment_count"], [("Sued", 90)])
        reporting = reporting_result(result)
        reporting["chart_plan"] = {
            "chart_type": "bar",
            "title": "Broken chart",
            "render_allowed": True,
            "x_axis": "missing_region",
            "y_axis": "shipment_count",
        }

        spec = build_slide_deck_spec(
            record=orchestrator_record(query_result=result, reporting_result=reporting, row_count=1)
        )

        self.assertFalse(any(slide.slide_type == "chart_evidence" for slide in spec.slides))
        self.assertTrue(any("chart evidence was skipped" in warning.lower() for warning in spec.warnings))


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
