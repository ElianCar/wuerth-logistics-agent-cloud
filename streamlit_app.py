import pandas as pd
import streamlit as st
import yaml

from src.agent.db import get_active_backend_metadata
from src.agent.golden_test_runner import load_golden_questions, run_golden_tests
from src.agent.langgraph_sql_agent import SQLAgentConfig
from src.agent.orchestrator import run_orchestrator
from src.agent.logging_utils import log_feedback
from src.agent.memory_store import (
    MemoryStoreError,
    approve_candidate,
    audit_candidate_validation,
    create_candidate_from_run,
    disable_template,
    initialize_memory_files,
    load_candidates,
    load_templates,
    mark_candidate_needs_changes,
    parse_source_tables,
    reactivate_template,
    reject_candidate,
    update_candidate_proposed_template,
)
from src.agent.memory_validation import validate_proposed_template
from src.config.scenarios import (
    SCENARIOS,
    get_active_scenario,
    get_active_scenario_id,
    get_scenario_options,
    set_active_scenario_id,
)
from src.llm.model_adapter import (
    DEFAULT_GEMINI_BACKUP_MODEL,
    DEFAULT_GEMINI_PRIMARY_MODEL,
    DEFAULT_OLLAMA_BACKUP_MODEL,
    DEFAULT_OLLAMA_MODEL,
    gemini_api_key_is_placeholder,
)


PAGE_CHAT = "Chat"
PAGE_GOLDEN = "Golden-Testmodus"
PAGE_MEMORY = "Memory-Prüfung"
PAGE_TEMPLATES = "Freigegebene Templates"


def result_to_dataframe(record: dict) -> pd.DataFrame:
    query_result = record.get("query_result", {})
    return pd.DataFrame(
        query_result.get("rows", []),
        columns=query_result.get("columns", []),
    )


def initialize_state() -> None:
    if "data_scenario" in st.session_state:
        set_active_scenario_id(st.session_state.data_scenario)
    if "history" not in st.session_state:
        st.session_state.history = []
    st.session_state.setdefault("last_golden_run_id", "")
    st.session_state.setdefault("last_selected_question_ids", [])
    st.session_state.setdefault("last_failed_question_ids", [])
    st.session_state.setdefault("last_errored_question_ids", [])
    st.session_state.setdefault("last_golden_result_summary", {})
    st.session_state.setdefault("last_golden_results", [])
    initialize_memory_files()


def set_flash(level: str, message: str) -> None:
    st.session_state.memory_flash = (level, message)


def render_flash() -> None:
    flash = st.session_state.pop("memory_flash", None)
    if not flash:
        return
    level, message = flash
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    else:
        st.info(message)


def build_streamlit_llm_config() -> SQLAgentConfig:
    env_config = SQLAgentConfig.from_env()
    gemini_config = SQLAgentConfig.from_provider("gemini")
    ollama_config = SQLAgentConfig.from_provider("ollama")

    st.session_state.setdefault(
        "use_local_ollama",
        env_config.llm_provider == "ollama",
    )

    use_local_ollama = st.toggle(
        "Lokales Ollama verwenden",
        key="use_local_ollama",
        help="Wenn aktiv, nutzt der Workflow lokale Ollama-Modelle für Primary und Fallback. Sonst wird die Gemini API genutzt.",
    )

    if use_local_ollama:
        return SQLAgentConfig(
            primary_model=DEFAULT_OLLAMA_MODEL,
            fallback_model=DEFAULT_OLLAMA_BACKUP_MODEL,
            max_primary_attempts=ollama_config.max_primary_attempts,
            llm_provider="ollama",
            ollama_host=ollama_config.ollama_host,
        )

    return SQLAgentConfig(
        primary_model=gemini_config.primary_model or DEFAULT_GEMINI_PRIMARY_MODEL,
        fallback_model=gemini_config.fallback_model or DEFAULT_GEMINI_BACKUP_MODEL,
        max_primary_attempts=gemini_config.max_primary_attempts,
        llm_provider="gemini",
        ollama_host=ollama_config.ollama_host,
    )


def apply_app_styles() -> None:
    st.markdown(
        """
        <style>
        p code,
        li code {
            white-space: nowrap;
            word-break: keep-all;
            overflow-wrap: normal;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> tuple[str, SQLAgentConfig]:
    with st.sidebar:
        st.header("Navigation")
        page = st.radio(
            "Ansicht",
            [PAGE_CHAT, PAGE_GOLDEN, PAGE_MEMORY, PAGE_TEMPLATES],
            label_visibility="collapsed",
        )

        st.header("Konfiguration")
        scenario_ids = [scenario.scenario_id for scenario in get_scenario_options()]
        default_scenario_id = st.session_state.get("data_scenario", get_active_scenario_id())
        default_index = scenario_ids.index(default_scenario_id) if default_scenario_id in scenario_ids else 0
        selected_scenario_id = st.selectbox(
            "Data scenario",
            scenario_ids,
            index=default_index,
            key="data_scenario_selector",
            format_func=lambda scenario_id: SCENARIOS[scenario_id].label,
        )
        previous_scenario_id = st.session_state.get("data_scenario")
        st.session_state.data_scenario = selected_scenario_id
        if previous_scenario_id and previous_scenario_id != selected_scenario_id:
            st.session_state.history = []
            st.session_state.last_golden_run_id = ""
            st.session_state.last_selected_question_ids = []
            st.session_state.last_failed_question_ids = []
            st.session_state.last_errored_question_ids = []
            st.session_state.last_golden_result_summary = {}
            st.session_state.last_golden_results = []
        set_active_scenario_id(selected_scenario_id)
        initialize_memory_files()
        scenario = get_active_scenario()

        config = build_streamlit_llm_config()
        try:
            backend_metadata = get_active_backend_metadata()
        except Exception as error:
            backend_metadata = {
                **scenario.safe_metadata,
                "auth_type": "",
            }
            st.error(f"Datenbank-Backend ist nicht korrekt konfiguriert: {error}")

        st.write(f"Active data scenario: `{backend_metadata.get('scenario_label', scenario.label)}`")
        st.write(f"Backend: `{backend_metadata.get('backend_display_name', backend_metadata.get('backend_name', ''))}`")
        st.write(f"SQL-Dialekt: `{backend_metadata.get('sql_dialect', '')}`")
        st.write(f"Semantic layer: `{backend_metadata.get('semantic_layer', scenario.semantic_layer_filename)}`")
        if backend_metadata.get("auth_type"):
            st.write(f"Databricks-Auth-Modus: `{backend_metadata.get('auth_type', '')}`")
        st.write(f"LLM-Anbieter: `{config.llm_provider}`")
        st.write(f"Primäres Modell: `{config.primary_model}`")
        st.write(f"Fallback-Modell: `{config.fallback_model}`")
        st.write(f"Max. primäre Versuche: `{config.max_primary_attempts}`")
        if config.llm_provider == "gemini":
            if gemini_api_key_is_placeholder():
                st.warning(
                    "GEMINI_API_KEY ist noch auf `key` gesetzt. Ersetze den Wert in `.env` "
                    "durch einen echten Gemini API Key, bevor Fragen gestellt werden."
                )
        else:
            st.write(f"Ollama-Host: `{config.ollama_host}`")

        st.header("Erlaubte Tabellen")
        allowed_tables = backend_metadata.get("allowed_tables") or list(scenario.allowed_tables)
        for table in allowed_tables:
            st.write(f"- `{table}`")

    return page, config


def write_feedback(record: dict, rating: str, comment: str) -> str:
    return log_feedback(
        run_id=record.get("run_id", ""),
        rating=rating,
        comment=comment,
        user_question=record.get("user_question", ""),
        final_answer=record.get("final_answer", ""),
        generated_sql=record.get("generated_sql", ""),
        selected_model=record.get("selected_model", ""),
        fallback_used=bool(record.get("fallback_used", False)),
        user_rating=rating,
        user_comment=comment,
    )


def retry_with_comment(record: dict, index: int, comment: str, config: SQLAgentConfig) -> None:
    if not comment.strip():
        st.warning("Bitte zuerst eine kurze Korrektur eingeben.")
        return

    write_feedback(record, "neutral", f"retry_with_comment: {comment}")
    with st.spinner("Wiederhole den Lauf mit deiner Korrektur..."):
        corrected_record = run_orchestrator(
            record.get("user_question", ""),
            config=config,
            previous_failed_sql=record.get("generated_sql", ""),
            previous_sql_error=record.get("sql_error", ""),
            previous_final_answer=record.get("final_answer", ""),
            user_correction=comment.strip(),
        )
    st.session_state.history[index] = corrected_record
    st.rerun()


def rerun_with_fallback(
    record: dict,
    index: int,
    config: SQLAgentConfig,
    comment: str = "",
) -> None:
    write_feedback(record, "neutral", f"fallback_requested: {comment}")
    with st.spinner("Wiederhole den Lauf mit dem Fallback-Modell..."):
        fallback_record = run_orchestrator(
            record.get("user_question", ""),
            config=config,
            force_fallback=True,
            previous_failed_sql=record.get("generated_sql", ""),
            previous_sql_error=record.get("sql_error", ""),
            previous_final_answer=record.get("final_answer", ""),
            user_correction=comment.strip(),
        )
    st.session_state.history[index] = fallback_record
    st.rerun()


def render_metadata(record: dict) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Modell", record.get("model_used") or record.get("selected_model", ""))
    col2.metric("Versuche", int(record.get("total_attempts", 0)))
    col3.metric("Fallback", "ja" if record.get("fallback_used") else "nein")
    col4.metric("Status", format_status(record.get("result_status", "")))


def can_create_template_candidate(record: dict) -> bool:
    return (
        record.get("run_context", "chat") == "chat"
        and bool(record.get("enable_memory_candidate_generation", True))
        and bool(record.get("validation_success", record.get("sql_valid")))
        and bool(record.get("execution_success"))
        and bool(record.get("final_sql") or record.get("generated_sql"))
        and bool(record.get("question") or record.get("user_question"))
    )


def render_candidate_creation(record: dict, index: int) -> None:
    if not can_create_template_candidate(record):
        return

    st.subheader("Memory")
    if st.button("YAML Template Vorschlag erstellen", key=f"create_candidate_{index}"):
        try:
            _candidate, created, message = create_candidate_from_run(record)
        except MemoryStoreError as error:
            st.error(str(error))
            return

        if created:
            st.success("YAML Template Vorschlag wurde erstellt.")
        else:
            st.info(message)


def format_filter_value(value: object) -> str:
    mapping = {
        "all": "alle",
        "pending_review": "wartet auf Prüfung",
        "needs_changes": "Überarbeitung nötig",
        "rejected": "verworfen",
        "approved": "freigegeben",
        "disabled": "deaktiviert",
        "solution_template": "Lösungstemplate",
    }
    return mapping.get(str(value), str(value))


def dump_yaml(data: object) -> str:
    return yaml.safe_dump(data or {}, sort_keys=False)


def parse_yaml_editor(text: str) -> dict | None:
    try:
        parsed = yaml.safe_load(text) or {}
    except yaml.YAMLError as error:
        st.error(f"YAML ist ungültig: {error}")
        return None
    if not isinstance(parsed, dict):
        st.error("YAML muss ein Mapping sein.")
        return None
    return parsed


def candidate_editor_is_stale(candidate_id: str, candidate: dict) -> bool:
    loaded_key = f"candidate_loaded_updated_at_{candidate_id}"
    loaded_updated_at = st.session_state.get(loaded_key)
    current_updated_at = candidate.get("updated_at", "")
    return bool(loaded_updated_at and loaded_updated_at != current_updated_at)


def show_validation_result(errors: list[str]) -> None:
    if not errors:
        st.success("YAML ist gültig.")
        return
    st.error("YAML ist ungültig.")
    for error in errors:
        st.write(f"- {error}")


def candidate_matches_filters(
    candidate: dict,
    *,
    status_filter: str,
    type_filter: str,
    table_filter: str,
    search_text: str,
) -> bool:
    if status_filter != "all" and candidate.get("status") != status_filter:
        return False
    if type_filter != "all" and candidate.get("candidate_type") != type_filter:
        return False
    if table_filter != "all" and table_filter not in parse_source_tables(candidate.get("source_tables")):
        return False

    if search_text:
        proposed_template = candidate.get("proposed_template", {})
        searchable = " ".join(
            [
                str(candidate.get("candidate_id", "")),
                str(candidate.get("run_id", "")),
                str(candidate.get("original_question", "")),
                str(proposed_template.get("intent", "")) if isinstance(proposed_template, dict) else "",
            ]
        ).lower()
        if search_text.lower() not in searchable:
            return False

    return True


def render_candidate_details(candidate: dict) -> None:
    st.subheader("Vorschlag")
    col1, col2, col3, col4 = st.columns(4)
    col1.write(f"candidate_id: `{candidate.get('candidate_id', '')}`")
    col2.write(f"run_id: `{candidate.get('run_id', '')}`")
    col3.write(f"Status: `{format_filter_value(candidate.get('status', ''))}`")
    col4.write(f"Typ: `{format_filter_value(candidate.get('candidate_type', ''))}`")
    st.write(f"Erstellt am: `{candidate.get('created_at', '')}`")
    st.write(f"Aktualisiert am: `{candidate.get('updated_at', '')}`")

    st.subheader("Originalfrage")
    st.write(candidate.get("original_question", ""))

    st.subheader("Antwort")
    st.write(candidate.get("generated_answer", ""))

    sql_col1, sql_col2 = st.columns(2)
    with sql_col1:
        st.subheader("Generiertes SQL")
        st.code(candidate.get("generated_sql", "") or "(leer)", language="sql")
    with sql_col2:
        st.subheader("Finales SQL")
        st.code(candidate.get("final_sql", "") or "(leer)", language="sql")

    st.subheader("Metadaten")
    metadata = {
        "Quelltabellen": candidate.get("source_tables", []),
        "Primäres Modell": candidate.get("model_primary"),
        "Verwendetes Modell": candidate.get("model_used"),
        "Fallback verwendet": candidate.get("fallback_used"),
        "Validierung erfolgreich": candidate.get("validation_success"),
        "Ausführung erfolgreich": candidate.get("execution_success"),
        "Fehlertyp": candidate.get("error_type"),
        "Fehlermeldung": candidate.get("error_message"),
        "Zeilenanzahl": candidate.get("row_count"),
    }
    st.json(metadata, expanded=False)

    feedback = candidate.get("feedback", {})
    st.subheader("Rückmeldung")
    st.write(f"Bewertung: `{feedback.get('rating') if isinstance(feedback, dict) else ''}`")
    st.write(feedback.get("comment") if isinstance(feedback, dict) else "")


def render_memory_review_view() -> None:
    st.title("Memory-Prüfung")
    render_flash()

    try:
        candidates = load_candidates()
    except MemoryStoreError as error:
        st.error(str(error))
        return

    if not candidates:
        st.info("Keine Memory-Vorschläge vorhanden.")
        return

    statuses = ["all", "pending_review", "needs_changes", "rejected", "approved"]
    candidate_types = ["all", *sorted({str(candidate.get("candidate_type", "")) for candidate in candidates if candidate.get("candidate_type")})]
    source_tables = sorted({table for candidate in candidates for table in parse_source_tables(candidate.get("source_tables"))})

    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        status_filter = st.selectbox(
            "Status",
            statuses,
            key="candidate_status_filter",
            format_func=format_filter_value,
        )
    with filter_col2:
        type_filter = st.selectbox(
            "Typ",
            candidate_types,
            key="candidate_type_filter",
            format_func=format_filter_value,
        )
    with filter_col3:
        table_filter = st.selectbox(
            "Quelltabelle",
            ["all", *source_tables],
            key="candidate_table_filter",
            format_func=format_filter_value,
        )
    with filter_col4:
        search_text = st.text_input("Suche", key="candidate_search")

    filtered_candidates = [
        candidate
        for candidate in candidates
        if candidate_matches_filters(
            candidate,
            status_filter=status_filter,
            type_filter=type_filter,
            table_filter=table_filter,
            search_text=search_text,
        )
    ]

    if not filtered_candidates:
        st.info("Keine Vorschläge für diese Filter.")
        return

    table_rows = []
    for candidate in filtered_candidates:
        proposed_template = candidate.get("proposed_template", {})
        table_rows.append(
            {
                "candidate_id": candidate.get("candidate_id", ""),
                "run_id": candidate.get("run_id", ""),
                "Status": format_filter_value(candidate.get("status", "")),
                "Typ": format_filter_value(candidate.get("candidate_type", "")),
                "Intent": proposed_template.get("intent", "") if isinstance(proposed_template, dict) else "",
                "Quelltabellen": ", ".join(parse_source_tables(candidate.get("source_tables"))),
                "Erstellt am": candidate.get("created_at", ""),
                "Aktualisiert am": candidate.get("updated_at", ""),
            }
        )
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    candidate_by_id = {candidate.get("candidate_id"): candidate for candidate in filtered_candidates}
    if st.session_state.get("selected_candidate_id") not in candidate_by_id:
        st.session_state.pop("selected_candidate_id", None)
    selected_candidate_id = st.selectbox(
        "Vorschlag auswählen",
        list(candidate_by_id.keys()),
        key="selected_candidate_id",
    )
    candidate = candidate_by_id[selected_candidate_id]
    candidate_id = str(candidate.get("candidate_id", ""))
    status = str(candidate.get("status", ""))
    editing_disabled = status in {"approved", "rejected"}

    render_candidate_details(candidate)

    st.subheader("Vorgeschlagenes Template-YAML")
    yaml_key = f"candidate_yaml_{candidate_id}"
    loaded_key = f"candidate_loaded_updated_at_{candidate_id}"
    if yaml_key not in st.session_state:
        st.session_state[yaml_key] = dump_yaml(candidate.get("proposed_template", {}))
        st.session_state[loaded_key] = candidate.get("updated_at", "")

    if st.button("Neu laden", key=f"reload_{candidate_id}"):
        st.session_state[yaml_key] = dump_yaml(candidate.get("proposed_template", {}))
        st.session_state[loaded_key] = candidate.get("updated_at", "")
        st.rerun()

    edited_yaml = st.text_area(
        "proposed_template",
        key=yaml_key,
        height=360,
        disabled=editing_disabled,
        label_visibility="collapsed",
    )

    review_comment = st.text_area("Review-Kommentar", key=f"review_comment_{candidate_id}")
    rejection_reason = st.text_area("Ablehnungsgrund", key=f"rejection_reason_{candidate_id}")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        if st.button(
            "Änderungen speichern",
            key=f"save_{candidate_id}",
            disabled=editing_disabled,
        ):
            if candidate_editor_is_stale(candidate_id, candidate):
                st.warning("Dieser Vorschlag wurde seit dem Laden geändert. Bitte zuerst neu laden.")
                parsed = None
            else:
                parsed = parse_yaml_editor(edited_yaml)
            if parsed is not None:
                try:
                    update_candidate_proposed_template(candidate_id, parsed)
                except MemoryStoreError as error:
                    st.error(str(error))
                else:
                    st.session_state[loaded_key] = ""
                    set_flash("success", "Änderungen wurden gespeichert.")
                    st.rerun()

    with col2:
        if st.button("YAML prüfen", key=f"validate_{candidate_id}"):
            parsed = parse_yaml_editor(edited_yaml)
            if parsed is not None:
                errors = validate_proposed_template(parsed)
                audit_candidate_validation(candidate_id, valid=not errors, error_count=len(errors))
                show_validation_result(errors)

    with col3:
        can_approve = status in {"pending_review", "needs_changes"}
        if st.button("Template freigeben", key=f"approve_{candidate_id}", disabled=not can_approve):
            if candidate_editor_is_stale(candidate_id, candidate):
                st.warning("Dieser Vorschlag wurde seit dem Laden geändert. Bitte zuerst neu laden.")
                parsed = None
            else:
                parsed = parse_yaml_editor(edited_yaml)
            if parsed is not None:
                errors = validate_proposed_template(parsed)
                if errors:
                    show_validation_result(errors)
                else:
                    try:
                        _candidate, template = approve_candidate(candidate_id, parsed)
                    except MemoryStoreError as error:
                        st.warning(str(error))
                    else:
                        set_flash("success", f"Template `{template.get('template_id')}` wurde freigegeben.")
                        st.rerun()

    with col4:
        can_reject = status in {"pending_review", "needs_changes"}
        if st.button("Vorschlag verwerfen", key=f"reject_{candidate_id}", disabled=not can_reject):
            if not rejection_reason.strip():
                st.warning("Bitte Ablehnungsgrund angeben.")
            else:
                try:
                    reject_candidate(candidate_id, rejection_reason)
                except MemoryStoreError as error:
                    st.error(str(error))
                else:
                    set_flash("success", "Vorschlag wurde verworfen.")
                    st.rerun()

    with col5:
        can_mark_needs_changes = status == "pending_review"
        if st.button(
            "Überarbeitung nötig",
            key=f"needs_changes_{candidate_id}",
            disabled=not can_mark_needs_changes,
        ):
            try:
                mark_candidate_needs_changes(candidate_id, review_comment)
            except MemoryStoreError as error:
                st.error(str(error))
            else:
                set_flash("success", "Vorschlag wurde als Überarbeitung nötig markiert.")
                st.rerun()


def render_approved_templates_view() -> None:
    st.title("Freigegebene Templates")
    render_flash()

    try:
        templates = load_templates()
    except MemoryStoreError as error:
        st.error(str(error))
        return

    if not templates:
        st.info("Keine freigegebenen Templates vorhanden.")
        return

    table_rows = [
        {
            "template_id": template.get("template_id", ""),
            "Version": template.get("version", ""),
            "Status": format_filter_value(template.get("status", "")),
            "Aktiv": format_yes_no(template.get("is_active", False)),
            "Intent": template.get("intent", ""),
            "Benötigte Tabellen": ", ".join(parse_source_tables(template.get("required_tables"))),
            "Erstellt aus Candidate": template.get("created_from_candidate_id", ""),
            "Quell-Run": template.get("source_run_id", ""),
            "Freigegeben am": template.get("approved_at", ""),
            "Freigegeben von": template.get("approved_by", ""),
        }
        for template in templates
    ]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    template_by_id = {template.get("template_id"): template for template in templates}
    if st.session_state.get("selected_template_id") not in template_by_id:
        st.session_state.pop("selected_template_id", None)
    selected_template_id = st.selectbox(
        "Template auswählen",
        list(template_by_id.keys()),
        key="selected_template_id",
    )
    template = template_by_id[selected_template_id]

    st.subheader("Details")
    st.write(f"template_id: `{template.get('template_id', '')}`")
    st.write(f"Status: `{format_filter_value(template.get('status', ''))}`")
    st.write(f"Aktiv: `{format_yes_no(template.get('is_active', False))}`")
    st.write(f"Intent: {template.get('intent', '')}")
    st.write("Auslösephrasen")
    st.json(template.get("trigger_phrases", []), expanded=False)
    st.write("Metrikdefinitionen")
    st.json(template.get("metric_definitions", {}), expanded=False)
    st.write("Join-Logik")
    st.json(template.get("join_logic", []), expanded=False)
    st.write("Qualität")
    st.json(template.get("quality", {}), expanded=False)
    st.subheader("SQL-Gerüst")
    st.code(template.get("sql_skeleton", "") or "(leer)", language="sql")

    disabled_reason = st.text_area(
        "Deaktivierungsgrund",
        key=f"disabled_reason_{selected_template_id}",
    )

    if template.get("status") == "approved" and template.get("is_active") is True:
        if st.button("Template deaktivieren", key=f"disable_{selected_template_id}"):
            if not disabled_reason.strip():
                st.warning("Bitte Deaktivierungsgrund angeben.")
            else:
                try:
                    disable_template(str(selected_template_id), disabled_reason)
                except MemoryStoreError as error:
                    st.error(str(error))
                else:
                    set_flash("success", "Template wurde deaktiviert.")
                    st.rerun()

    if template.get("status") == "disabled":
        if st.button("Template reaktivieren", key=f"reactivate_{selected_template_id}"):
            try:
                reactivate_template(str(selected_template_id))
            except MemoryStoreError as error:
                st.error(str(error))
            else:
                set_flash("success", "Template wurde reaktiviert.")
                st.rerun()


def golden_checkbox_key(question_id: str) -> str:
    return f"golden_select_{question_id}"


def initialize_golden_question_state(questions: list[dict]) -> None:
    for question in questions:
        st.session_state.setdefault(golden_checkbox_key(question["question_id"]), False)


def selected_golden_question_ids(questions: list[dict]) -> list[str]:
    return [
        question["question_id"]
        for question in questions
        if st.session_state.get(golden_checkbox_key(question["question_id"]), False)
    ]


def ordered_subset(question_ids: list[str], questions: list[dict]) -> list[str]:
    requested = set(question_ids)
    return [question["question_id"] for question in questions if question["question_id"] in requested]


def run_golden_question_ids(
    question_ids: list[str],
    *,
    use_approved_memory: bool,
    config: SQLAgentConfig,
) -> None:
    if not question_ids:
        st.warning("Bitte zuerst mindestens eine Golden-Testfrage auswählen.")
        return

    with st.spinner(f"Golden Tests werden gegen {get_active_scenario().label} ausgeführt..."):
        batch_run_id, results, summary = run_golden_tests(
            question_ids,
            use_approved_memory=use_approved_memory,
            config=config,
        )

    st.session_state.last_golden_run_id = batch_run_id
    st.session_state.last_selected_question_ids = question_ids
    st.session_state.last_failed_question_ids = [
        result["question_id"] for result in results if result.get("status") == "failed"
    ]
    st.session_state.last_errored_question_ids = [
        result["question_id"] for result in results if result.get("status") == "error"
    ]
    st.session_state.last_golden_result_summary = summary
    st.session_state.last_golden_results = results


def preview_to_dataframe(preview: dict) -> pd.DataFrame:
    return pd.DataFrame(preview.get("rows", []), columns=preview.get("columns", []))


def format_status(value: object) -> str:
    mapping = {
        "passed": "bestanden",
        "failed": "fehlgeschlagen",
        "error": "Fehler",
        "first attempt success": "im ersten Versuch erfolgreich",
        "repaired success": "nach Reparatur erfolgreich",
        "fallback success": "mit Fallback erfolgreich",
    }
    return mapping.get(str(value), str(value))


def format_yes_no(value: object) -> str:
    return "ja" if bool(value) else "nein"


def format_failure_reason(value: object) -> str:
    mapping = {
        "output_mismatch": "Ausgabe weicht ab",
        "sql_validation": "SQL-Validierung fehlgeschlagen",
        "execution_error": "Ausführungsfehler",
        "reference_sql_validation_error": "Referenz-SQL ist ungültig",
        "reference_sql_execution_error": "Referenz-SQL konnte nicht ausgeführt werden",
        "agent_error": "Agentenfehler",
        "unexpected_error": "Unerwarteter Fehler",
        "shape mismatch": "Form der Ausgabe weicht ab",
        "column count mismatch": "Spaltenanzahl weicht ab",
        "row count mismatch": "Zeilenanzahl weicht ab",
        "column name mismatch": "Spaltennamen weichen ab",
        "row values differ ignoring order": "Zeilenwerte weichen ab",
        "row values differ with order enforced": "Zeilenwerte oder Sortierung weichen ab",
        "duplicate row count mismatch": "Anzahl doppelter Zeilen weicht ab",
        "numeric value outside tolerance": "Numerischer Wert außerhalb der Toleranz",
        "null mismatch": "NULL-Wert weicht ab",
        "missing rows": "fehlende Zeilen",
        "unexpected rows": "unerwartete Zeilen",
        "value mismatch": "Wertabweichung",
        "column mismatch": "Spaltenabweichung",
        "order mismatch": "Sortierung weicht ab",
    }
    text = str(value or "")
    for english, german in mapping.items():
        text = text.replace(english, german)
    return text


def localize_diff_summary(diff_summary: dict) -> dict:
    if not isinstance(diff_summary, dict):
        return {}
    localized = {
        "bestanden": diff_summary.get("passed", False),
        "Probleme": [
            format_failure_reason(issue)
            for issue in diff_summary.get("issues", [])
        ],
    }
    for source_key, target_key in [
        ("shape_mismatch", "Formabweichung"),
        ("column_count_mismatch", "Spaltenanzahlabweichung"),
        ("row_count_mismatch", "Zeilenanzahlabweichung"),
        ("column_name_mismatch", "Spaltennamenabweichung"),
        ("column_mismatch", "Spaltenabweichung"),
        ("value_mismatch", "Wertabweichung"),
        ("missing_rows", "fehlende Zeilen"),
        ("unexpected_rows", "unerwartete Zeilen"),
    ]:
        if source_key in diff_summary:
            localized[target_key] = diff_summary[source_key]
    localized["reihenfolge_sensitiv"] = diff_summary.get("order_sensitive", False)
    localized["spaltennamen_vergleichen"] = diff_summary.get("compare_column_names", True)
    return localized


def render_golden_summary(summary: dict) -> None:
    if not summary:
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tests insgesamt", int(summary.get("total_tests_run", 0)))
    col2.metric("Bestanden", int(summary.get("passed", 0)))
    col3.metric("Bestehensquote", f"{float(summary.get('pass_rate', 0.0)) * 100:.1f}%")
    col4.metric("Ø Laufzeit", f"{float(summary.get('average_runtime', 0.0)):.2f}s")

    col5, col6, col7 = st.columns(3)
    col5.metric("Ausgabeabweichung", int(summary.get("failed_output_mismatch", 0)))
    col6.metric("SQL-Validierung", int(summary.get("failed_sql_validation", 0)))
    col7.metric("Ausführungsfehler", int(summary.get("failed_execution_error", 0)))


def render_golden_results(results: list[dict]) -> None:
    if not results:
        return

    st.subheader("Ergebnisse")
    table_rows = [
        {
            "Frage": result.get("question_id", ""),
            "Titel": result.get("title", ""),
            "Status": format_status(result.get("status", "")),
            "Bestanden": format_yes_no(result.get("passed", False)),
            "Laufzeit": f"{float(result.get('runtime_seconds', 0.0)):.2f}s",
            "Erwartete Zeilen": result.get("expected_row_count", 0),
            "Tatsächliche Zeilen": result.get("actual_row_count", 0),
            "Fehlergrund": format_failure_reason(result.get("failure_reason", "")),
        }
        for result in results
    ]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    for result in results:
        label = (
            f"{result.get('question_id', '')} - {result.get('title', '')} "
            f"({format_status(result.get('status', ''))})"
        )
        with st.expander(label, expanded=not result.get("passed", False)):
            meta1, meta2, meta3, meta4 = st.columns(4)
            meta1.write(f"Zeitpunkt: `{result.get('timestamp', '')}`")
            meta2.write(f"Modell: `{result.get('model_used', '')}`")
            meta3.write(f"Backend: `{result.get('backend', '')}`")
            meta4.write(f"Memory/Templates: `{format_yes_no(result.get('memory_templates_enabled', False))}`")

            st.subheader("Frage")
            st.write(result.get("question", ""))

            sql_col1, sql_col2 = st.columns(2)
            with sql_col1:
                st.subheader("Generiertes Agenten-SQL")
                st.code(result.get("generated_agent_sql", "") or "(leer)", language="sql")
            with sql_col2:
                st.subheader("Referenz-SQL")
                st.code(result.get("reference_sql", "") or "(leer)", language="sql")

            out_col1, out_col2 = st.columns(2)
            with out_col1:
                st.subheader("Tatsächliche Ausgabevorschau")
                st.dataframe(
                    preview_to_dataframe(result.get("actual_output_preview", {})),
                    use_container_width=True,
                )
            with out_col2:
                st.subheader("Erwartete Ausgabevorschau")
                st.dataframe(
                    preview_to_dataframe(result.get("expected_output_preview", {})),
                    use_container_width=True,
                )

            st.subheader("Abweichungsübersicht")
            st.json(localize_diff_summary(result.get("diff_summary", {})), expanded=False)

            if result.get("validation_errors"):
                st.subheader("Validierungsfehler")
                st.json(result.get("validation_errors", []), expanded=False)

            if result.get("execution_errors"):
                st.subheader("Ausführungsfehler")
                execution_errors = result.get("execution_errors", {})
                if isinstance(execution_errors, dict):
                    execution_errors = {
                        format_failure_reason(key): value
                        for key, value in execution_errors.items()
                    }
                st.json(execution_errors, expanded=False)

            if result.get("agent_trace_steps"):
                st.subheader("Ablaufschritte")
                for step in result.get("agent_trace_steps", []):
                    st.markdown(f"- {step}")


def render_golden_test_mode_view(config: SQLAgentConfig) -> None:
    st.title("Golden-Testmodus")
    scenario = get_active_scenario()
    st.caption(
        f"Reiner Evaluationsmodus für {scenario.label}. Ergebnisse werden unter "
        f"{scenario.evaluation_dir.name}/golden_results.jsonl geschrieben."
    )
    render_flash()

    try:
        questions = load_golden_questions()
    except Exception as error:
        st.error(f"Golden-Testfragen konnten nicht geladen werden: {error}")
        return

    initialize_golden_question_state(questions)
    all_question_ids = [question["question_id"] for question in questions]
    use_approved_memory = st.toggle(
        "Freigegebene Memory/Templates verwenden",
        value=True,
        key="golden_use_approved_memory",
    )

    if not st.session_state.last_golden_run_id:
        st.info("Es gibt noch keinen vorherigen Golden-Testlauf. Wiederholen-Buttons sind deaktiviert, bis ein Lauf abgeschlossen wurde.")

    control_cols = st.columns(6)
    with control_cols[0]:
        if st.button("Alle auswählen"):
            for question_id in all_question_ids:
                st.session_state[golden_checkbox_key(question_id)] = True
            st.rerun()
    with control_cols[1]:
        if st.button("Alle abwählen"):
            for question_id in all_question_ids:
                st.session_state[golden_checkbox_key(question_id)] = False
            st.rerun()
    with control_cols[2]:
        if st.button("Ausgewählte Golden Tests ausführen"):
            run_golden_question_ids(
                selected_golden_question_ids(questions),
                use_approved_memory=use_approved_memory,
                config=config,
            )
    with control_cols[3]:
        if st.button("Alle Golden Tests ausführen"):
            run_golden_question_ids(
                all_question_ids,
                use_approved_memory=use_approved_memory,
                config=config,
            )
    with control_cols[4]:
        if st.button(
            "Letzten Lauf wiederholen",
            disabled=not bool(st.session_state.last_selected_question_ids),
        ):
            run_golden_question_ids(
                ordered_subset(st.session_state.last_selected_question_ids, questions),
                use_approved_memory=use_approved_memory,
                config=config,
            )
    with control_cols[5]:
        failed_or_errored = ordered_subset(
            [
                *st.session_state.last_failed_question_ids,
                *st.session_state.last_errored_question_ids,
            ],
            questions,
        )
        if st.button("Nur fehlgeschlagene Tests wiederholen", disabled=not bool(failed_or_errored)):
            run_golden_question_ids(
                failed_or_errored,
                use_approved_memory=use_approved_memory,
                config=config,
            )

    selected_ids = selected_golden_question_ids(questions)
    st.write(f"Ausgewählte Fragen: `{len(selected_ids)}` von `{len(questions)}`")

    st.subheader("Fragen")
    for question in questions:
        st.checkbox(
            f"{question['question_id']} - {question.get('title', '')}",
            key=golden_checkbox_key(question["question_id"]),
        )
        st.caption(question.get("question", ""))

    render_golden_summary(st.session_state.last_golden_result_summary)
    render_golden_results(st.session_state.last_golden_results)


def render_record(record: dict, index: int, config: SQLAgentConfig) -> None:
    with st.chat_message("user"):
        st.caption("Frage")
        st.markdown(record.get("user_question", ""))

    with st.chat_message("assistant"):
        render_metadata(record)

        st.subheader("Antwort")
        st.write(record.get("final_answer") or "Es wurde keine Antwort erzeugt.")

        query_result = record.get("query_result", {})
        rows = query_result.get("rows", [])
        columns = query_result.get("columns", [])
        if rows and columns:
            st.subheader("Ergebnisvorschau")
            df = result_to_dataframe(record)
            st.dataframe(df, use_container_width=True)

        st.subheader("SQL-Anweisung")
        st.code(record.get("final_sql") or record.get("generated_sql", "") or "(kein SQL erzeugt)", language="sql")

        source_tables = record.get("source_tables", [])
        st.subheader("Quelltabellen")
        if source_tables:
            for table in source_tables:
                st.markdown(f"- `{table}`")
        else:
            st.write("Es wurden keine Quelltabellen erkannt.")

        if record.get("sql_error"):
            st.subheader("SQL-Fehler")
            st.error(record["sql_error"])

        with st.expander("Ablaufschritte", expanded=False):
            for step in record.get("trace_steps", []):
                st.markdown(f"- {step}")

        if record.get("user_correction"):
            st.subheader("Nutzerkorrektur")
            st.write(record["user_correction"])

        st.subheader("Rückmeldung")
        comment = st.text_area("Optionaler Kommentar", key=f"feedback_comment_{index}")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("Gute Antwort", key=f"feedback_good_{index}"):
                write_feedback(record, "thumbs_up", comment)
                st.success("Rückmeldung gespeichert.")
        with col2:
            if st.button("Schlechte Antwort", key=f"feedback_bad_{index}"):
                write_feedback(record, "thumbs_down", comment)
                st.warning("Rückmeldung gespeichert.")
        with col3:
            if st.button("Mit Kommentar wiederholen", key=f"feedback_retry_{index}"):
                retry_with_comment(record, index, comment, config)
        with col4:
            if st.button("Fallback-Modell verwenden", key=f"feedback_fallback_{index}"):
                rerun_with_fallback(record, index, config, comment)

        render_candidate_creation(record, index)


def main() -> None:
    st.set_page_config(page_title="Agentic AI Datenassistent", layout="wide")
    apply_app_styles()
    initialize_state()
    page, config = render_sidebar()

    if page == PAGE_MEMORY:
        render_memory_review_view()
        return

    if page == PAGE_GOLDEN:
        render_golden_test_mode_view(config)
        return

    if page == PAGE_TEMPLATES:
        render_approved_templates_view()
        return

    st.title("Agentic AI Datenassistent")
    scenario = get_active_scenario()
    st.caption(
        f"LangGraph-SQL-Workflow für {scenario.label} mit konfigurierbaren Primary- und Fallback-Modellen."
    )
    render_flash()

    for index, record in enumerate(st.session_state.history):
        render_record(record, index, config)

    question = st.chat_input(f"Stelle eine Frage zu {scenario.label}")
    if question:
        with st.spinner("LangGraph-SQL-Workflow wird ausgeführt..."):
            record = run_orchestrator(question, config=config)
        st.session_state.history.append(record)
        st.rerun()


if __name__ == "__main__":
    main()
