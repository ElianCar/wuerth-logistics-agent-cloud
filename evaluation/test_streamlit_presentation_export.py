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


if __name__ == "__main__":
    unittest.main()
