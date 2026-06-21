from __future__ import annotations

import ast
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_APP_PATH = PROJECT_ROOT / "streamlit_app.py"


class _SessionState(dict):
    def __getattr__(self, name: str) -> object:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


def _module(name: str, **attributes: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _load_streamlit_app() -> types.ModuleType:
    fake_streamlit = _module("streamlit", session_state=_SessionState())
    fake_pandas = _module("pandas", DataFrame=object)
    fake_altair = _module("altair")
    fake_yaml = _module("yaml")
    fake_db = _module("src.agent.db", get_active_backend_metadata=lambda: {})
    fake_golden = _module(
        "src.agent.golden_test_runner",
        load_golden_questions=lambda: [],
        run_golden_tests=lambda *args, **kwargs: [],
    )

    class _FakeSQLAgentConfig:
        @classmethod
        def from_env(cls) -> "_FakeSQLAgentConfig":
            return cls()

        @classmethod
        def from_provider(cls, _provider: str) -> "_FakeSQLAgentConfig":
            return cls()

        def __init__(self, **kwargs: object) -> None:
            self.llm_provider = str(kwargs.get("llm_provider", "ollama"))
            self.primary_model = str(kwargs.get("primary_model", "primary"))
            self.fallback_model = str(kwargs.get("fallback_model", "fallback"))
            self.max_primary_attempts = int(kwargs.get("max_primary_attempts", 1))
            self.ollama_host = str(kwargs.get("ollama_host", ""))

    fake_sql_agent = _module("src.agent.langgraph_sql_agent", SQLAgentConfig=_FakeSQLAgentConfig)
    fake_orchestrator = _module("src.agent.orchestrator", run_orchestrator=lambda *args, **kwargs: {})
    fake_logging = _module("src.agent.logging_utils", log_feedback=lambda **kwargs: "")
    fake_presentation_export = _module(
        "src.agent.presentation_export",
        PPTX_MIME_TYPE="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        build_presentation_export=lambda **kwargs: types.SimpleNamespace(
            available=True,
            content=b"pptx",
            filename="wuerth_logistics_run.pptx",
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            slide_count=5,
            warnings=[],
            unavailable_reason="",
        ),
        can_export_presentation=lambda record: types.SimpleNamespace(can_export=True, reason=""),
    )
    fake_memory_store = _module(
        "src.agent.memory_store",
        MemoryStoreError=RuntimeError,
        approve_candidate=lambda *args, **kwargs: None,
        audit_candidate_validation=lambda *args, **kwargs: None,
        create_candidate_from_run=lambda *args, **kwargs: {},
        disable_template=lambda *args, **kwargs: None,
        initialize_memory_files=lambda: None,
        load_candidates=lambda: [],
        load_templates=lambda: [],
        mark_candidate_needs_changes=lambda *args, **kwargs: None,
        parse_source_tables=lambda value: [],
        reactivate_template=lambda *args, **kwargs: None,
        reject_candidate=lambda *args, **kwargs: None,
        update_candidate_proposed_template=lambda *args, **kwargs: None,
    )
    fake_memory_validation = _module(
        "src.agent.memory_validation",
        validate_proposed_template=lambda *args, **kwargs: [],
    )
    fake_scenarios = _module(
        "src.config.scenarios",
        SCENARIOS={},
        get_active_scenario=lambda: types.SimpleNamespace(label="Demo", allowed_tables=()),
        get_active_scenario_id=lambda: "demo",
        get_scenario_options=lambda: [],
        set_active_scenario_id=lambda scenario_id: None,
    )
    fake_model_adapter = _module(
        "src.llm.model_adapter",
        DEFAULT_ANTHROPIC_FALLBACK_MODEL="anthropic-fallback",
        DEFAULT_ANTHROPIC_MEDIUM_MODEL="anthropic-medium",
        DEFAULT_GEMINI_BACKUP_MODEL="gemini-backup",
        DEFAULT_GEMINI_PRIMARY_MODEL="gemini-primary",
        DEFAULT_OLLAMA_BACKUP_MODEL="ollama-backup",
        DEFAULT_OLLAMA_MODEL="ollama-model",
        anthropic_api_key_is_placeholder=lambda: False,
        gemini_api_key_is_placeholder=lambda: False,
        get_provider=lambda: "ollama",
    )

    fake_modules = {
        "streamlit": fake_streamlit,
        "pandas": fake_pandas,
        "altair": fake_altair,
        "yaml": fake_yaml,
        "src.agent.db": fake_db,
        "src.agent.golden_test_runner": fake_golden,
        "src.agent.langgraph_sql_agent": fake_sql_agent,
        "src.agent.orchestrator": fake_orchestrator,
        "src.agent.logging_utils": fake_logging,
        "src.agent.presentation_export": fake_presentation_export,
        "src.agent.memory_store": fake_memory_store,
        "src.agent.memory_validation": fake_memory_validation,
        "src.config.scenarios": fake_scenarios,
        "src.llm.model_adapter": fake_model_adapter,
    }

    with patch.dict(sys.modules, fake_modules):
        sys.modules.pop("streamlit_app", None)
        module = importlib.import_module("streamlit_app")
    return module


def _imported_symbols(source: str) -> set[str]:
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported.add(module)
            imported.update(alias.name for alias in node.names)
    return imported


class StreamlitPresentationExportHelperTests(unittest.TestCase):
    def test_presentation_export_key_uses_run_id_and_active_chat(self) -> None:
        app = _load_streamlit_app()

        key = app.presentation_export_key(
            {"run_id": "run-123"},
            7,
            active_chat_id="chat-a",
        )

        self.assertEqual(key, "ppt_export_chat-a_run-123")

    def test_presentation_export_key_uses_index_fallback(self) -> None:
        app = _load_streamlit_app()

        key = app.presentation_export_key(
            {},
            7,
            active_chat_id="chat-a",
        )

        self.assertEqual(key, "ppt_export_chat-a_7")

    def test_presentation_exports_state_initializes_dict(self) -> None:
        app = _load_streamlit_app()
        session_state: dict[str, object] = {}

        exports = app.presentation_exports_state(session_state)

        self.assertIs(exports, session_state["presentation_exports"])
        self.assertEqual(exports, {})

    def test_presentation_exports_state_preserves_existing_dict(self) -> None:
        app = _load_streamlit_app()
        existing: dict[str, object] = {"ppt_export_chat-a_run-123": object()}
        session_state: dict[str, object] = {"presentation_exports": existing}

        exports = app.presentation_exports_state(session_state)

        self.assertIs(exports, existing)
        self.assertEqual(session_state["presentation_exports"], existing)

    def test_unavailable_reason_copy_matches_ui_spec(self) -> None:
        app = _load_streamlit_app()
        cases = {
            "record_missing": "No analysis record was found.",
            "blocked_request": "This request was blocked for safety.",
            "clarification_needed": "This run needs clarification before export.",
            "sql_execution_failed": "SQL execution did not finish successfully.",
            "sql_validation_failed": "SQL validation did not pass.",
            "missing_query_result": "No query result is available.",
            "missing_query_columns": "The query result has no columns.",
            "missing_query_rows": "The query result has no rows.",
            "zero_row_count": "The query returned zero rows.",
            "unexpected_reason": "The backend exporter marked this run as unavailable.",
        }

        for reason, expected in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(app.format_presentation_unavailable_reason(reason), expected)

    def test_initialize_state_adds_presentation_exports_without_disturbing_existing_state(self) -> None:
        app = _load_streamlit_app()
        session_state = app.st.session_state
        existing_chats = {"chat-a": {"name": "Chat A", "history": []}}
        existing_golden_results = [{"question_id": "q1", "status": "passed"}]
        session_state.update({
            "chats": existing_chats,
            "active_chat_id": "chat-a",
            "editing_chat_id": "chat-a",
            "confirm_delete_chat_id": None,
            "last_golden_run_id": "golden-run",
            "last_selected_question_ids": ["q1"],
            "last_failed_question_ids": [],
            "last_errored_question_ids": [],
            "last_golden_result_summary": {"passed": 1},
            "last_golden_results": existing_golden_results,
        })

        app.initialize_state()

        self.assertEqual(session_state["presentation_exports"], {})
        self.assertIs(session_state["chats"], existing_chats)
        self.assertEqual(session_state["active_chat_id"], "chat-a")
        self.assertEqual(session_state["last_golden_results"], existing_golden_results)

    def test_streamlit_source_does_not_import_renderer_internals(self) -> None:
        source = STREAMLIT_APP_PATH.read_text(encoding="utf-8")
        imported = _imported_symbols(source)
        forbidden = {
            "pptx",
            "Presentation",
            "SlideDeckSpec",
            "SlideSpec",
            "validate_template",
            "validate_slide_deck_spec",
            "build_slide_deck_spec",
            "_render_presentation",
            "src.agent.visualization_spec",
        }

        self.assertFalse(forbidden & imported, forbidden & imported)


class StreamlitPresentationExportWiringTests(unittest.TestCase):
    def test_streamlit_imports_only_allowed_backend_export_symbols(self) -> None:
        source = STREAMLIT_APP_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        presentation_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "src.agent.presentation_export"
        ]

        self.assertEqual(len(presentation_imports), 1, "expected one presentation_export import block")
        imported = {alias.name for alias in presentation_imports[0].names}
        self.assertEqual(
            imported,
            {"PPTX_MIME_TYPE", "build_presentation_export", "can_export_presentation"},
        )

    def test_result_export_row_uses_csv_excel_and_ppt_columns(self) -> None:
        source = STREAMLIT_APP_PATH.read_text(encoding="utf-8")

        self.assertIn("col_csv, col_xlsx, col_ppt = st.columns(3)", source)
        self.assertNotIn("col_csv, col_xlsx = st.columns(2)", source)

    def test_create_download_and_status_copy_matches_ui_spec(self) -> None:
        source = STREAMLIT_APP_PATH.read_text(encoding="utf-8")
        approved_copy = [
            "Create PPT",
            "Download PPT",
            "Creating PPT...",
            "PPT ready.",
            "PPT created with warnings.",
            "PPT unavailable",
            "Run a successful validated analysis with result rows, then create the deck.",
            "PPT unavailable: {reason}",
            "PPT export failed: {reason}. Fix the template or rerun a valid analysis, then create the deck again.",
            "PPT warnings",
        ]

        for text in approved_copy:
            with self.subTest(text=text):
                self.assertIn(text, source)

    def test_create_action_calls_backend_export_without_template_path(self) -> None:
        source = STREAMLIT_APP_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_presentation_export"
        ]

        self.assertEqual(len(calls), 1, "expected one Streamlit backend export call")
        keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
        self.assertIn("record", keywords)
        self.assertIn("include_closing", keywords)
        self.assertIsInstance(keywords["include_closing"], ast.Constant)
        self.assertIs(keywords["include_closing"].value, False)
        self.assertNotIn("template_path", keywords)
        self.assertNotIn("template_path=", source)

    def test_download_button_uses_backend_export_fields_and_mime_type(self) -> None:
        source = STREAMLIT_APP_PATH.read_text(encoding="utf-8")
        required_fragments = [
            "data=export.content",
            "file_name=export.filename",
            "mime=export.mime_type or PPTX_MIME_TYPE",
            'key=f"download_{export_key}"',
        ]

        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)
        self.assertNotIn("wuerth_logistics_", source)

    def test_streamlit_does_not_expose_slide_or_renderer_controls(self) -> None:
        source = STREAMLIT_APP_PATH.read_text(encoding="utf-8")
        forbidden_fragments = {
            "from pptx import",
            "Presentation(",
            "SlideDeckSpec",
            "SlideSpec",
            "PresentationExport",
            "validate_template",
            "validate_slide_deck_spec",
            "build_slide_deck_spec",
            "_render_presentation",
            "deck_spec",
            "include_closing=True",
            "slide_order",
            "slide preview",
            "chart type",
        }

        matches = {fragment for fragment in forbidden_fragments if fragment in source}
        self.assertFalse(matches, matches)


if __name__ == "__main__":
    unittest.main()
