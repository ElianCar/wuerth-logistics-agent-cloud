from __future__ import annotations

import os
import re
from functools import lru_cache
from time import perf_counter
from typing import Any, Literal

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src.agent.data_overview import build_data_overview
from src.agent.db import execute_read_only_sql
from src.agent.id_utils import generate_run_id
from src.agent.langgraph_sql_agent import SQLAgentConfig, StepCallback, run_sql_agent
from src.agent.logging_utils import append_csv_row, current_timestamp, get_log_dir
from src.agent.reporting_agent import build_reporting_result
from src.agent.visualization_spec import build_visualization_spec
from src.agent.router import RouterState, build_router_graph
from src.config.scenarios import (
    get_active_scenario,
    get_active_scenario_id,
    load_semantic_column_metadata,
)
from src.llm.model_adapter import get_provider, get_token_usage, reset_token_usage

load_dotenv()


ANTHROPIC_TIER_MODELS = {
    "easy": os.getenv("ANTHROPIC_EASY_MODEL", "claude-haiku-4-5-20251001"),
    "medium": os.getenv("ANTHROPIC_MEDIUM_MODEL", "claude-sonnet-4-6"),
    "hard": os.getenv("ANTHROPIC_HARD_MODEL", "claude-opus-4-8"),
}
ANTHROPIC_FALLBACK_MODELS = {
    "easy": os.getenv("ANTHROPIC_MEDIUM_MODEL", "claude-sonnet-4-6"),
    "medium": os.getenv("ANTHROPIC_HARD_MODEL", "claude-opus-4-8"),
    "hard": os.getenv("ANTHROPIC_HARD_MODEL", "claude-opus-4-8"),
}
ANTHROPIC_SECONDARY_FALLBACK_MODELS = {
    "easy": os.getenv("ANTHROPIC_HARD_MODEL", "claude-opus-4-8"),
    "medium": os.getenv("ANTHROPIC_HARD_MODEL", "claude-opus-4-8"),
    "hard": os.getenv("ANTHROPIC_HARD_MODEL", "claude-opus-4-8"),
}
ANTHROPIC_MAX_PRIMARY_ATTEMPTS = {
    "easy": int(os.getenv("ANTHROPIC_EASY_MAX_PRIMARY_ATTEMPTS", "1")),
    "medium": int(os.getenv("ANTHROPIC_MEDIUM_MAX_PRIMARY_ATTEMPTS", "1")),
    "hard": int(os.getenv("ANTHROPIC_HARD_MAX_PRIMARY_ATTEMPTS", "2")),
}

GEMINI_TIER_MODELS = {
    "easy": os.getenv("GEMINI_EASY_MODEL", "gemini-3.1-flash-lite"),
    "medium": os.getenv(
        "GEMINI_MEDIUM_MODEL",
        os.getenv("GEMINI_PRIMARY_MODEL", "gemini-3.1-flash-lite"),
    ),
    "hard": os.getenv("GEMINI_HARD_MODEL", ""),
}
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")

OLLAMA_TIER_MODELS = {
    "easy": os.getenv("OLLAMA_EASY_MODEL", "llama3.2:3b"),
    "medium": os.getenv(
        "OLLAMA_MEDIUM_MODEL",
        os.getenv("PRIMARY_MODEL") or os.getenv("OLLAMA_MODEL") or "llama3.2:3b",
    ),
    "hard": os.getenv("OLLAMA_HARD_MODEL", ""),
}
OLLAMA_FALLBACK_MODEL = os.getenv("OLLAMA_FALLBACK_MODEL", "llama3.1:8b")


class OrchestratorState(TypedDict, total=False):
    run_id: str
    user_question: str
    chat_context: str
    retry_context: dict[str, Any]
    llm_provider: str
    ollama_host: str

    intent: str
    needs_sql: bool
    needs_clarification: bool
    blocked_or_unsafe: bool
    output_mode: str
    language: str
    memory_intent_key: str
    complexity_tier: str
    complexity_reason: str
    constraints: dict[str, Any]
    execution_plan: list[str]
    clarification_question: str
    template_candidates: list[dict[str, Any]]
    memory_retrieval: dict[str, Any]

    selected_model: str
    model_used: str
    primary_model: str
    fallback_model: str
    secondary_fallback_model: str
    max_primary_attempts: int

    schema_context: str
    generated_sql: str
    final_sql: str
    sql_valid: bool
    sql_error: str
    query_result: dict[str, Any]
    execution_success: bool
    validation_success: bool
    fallback_used: bool
    source_tables: list[str]
    row_count: int
    total_attempts: int
    result_status: str
    error_type: str
    error_message: str
    latency_seconds: float
    trace_steps: list[str]
    final_answer: str
    answer: str
    schema_load_failed: bool
    chart_spec: dict[str, Any]
    reporting_result: dict[str, Any]

    previous_failed_sql: str
    previous_sql_error: str
    previous_final_answer: str
    user_correction: str
    run_context: str
    use_approved_memory: bool
    enable_memory_candidate_generation: bool
    log_to_query_log: bool
    force_fallback: bool

    config_primary_model: str
    config_fallback_model: str
    config_secondary_fallback_model: str
    config_max_primary_attempts: int


_compiled_router = None


def _get_compiled_router():
    global _compiled_router
    if _compiled_router is None:
        _compiled_router = build_router_graph()
    return _compiled_router


def _coerce_sql_config(config: Any | None) -> SQLAgentConfig:
    if isinstance(config, SQLAgentConfig):
        return config
    if config is None:
        return SQLAgentConfig.from_env()

    return SQLAgentConfig(
        primary_model=str(getattr(config, "primary_model")),
        fallback_model=str(getattr(config, "fallback_model")),
        max_primary_attempts=int(getattr(config, "max_primary_attempts")),
        llm_provider=str(getattr(config, "llm_provider")),
        ollama_host=str(getattr(config, "ollama_host")),
        secondary_fallback_model=str(getattr(config, "secondary_fallback_model", "")),
    )


def _tier_primary_model(config: SQLAgentConfig, tier: str) -> str:
    provider = get_provider(config.llm_provider)
    tier = tier if tier in {"easy", "medium", "hard"} else "hard"
    if provider == "anthropic":
        return ANTHROPIC_TIER_MODELS.get(tier) or config.primary_model
    if provider == "gemini":
        return GEMINI_TIER_MODELS.get(tier) or config.primary_model
    return OLLAMA_TIER_MODELS.get(tier) or config.primary_model


def _tier_fallback_model(config: SQLAgentConfig, tier: str) -> str:
    provider = get_provider(config.llm_provider)
    tier = tier if tier in {"easy", "medium", "hard"} else "hard"
    if provider == "anthropic":
        return ANTHROPIC_FALLBACK_MODELS.get(tier) or config.fallback_model
    return config.fallback_model


def _tier_secondary_fallback_model(config: SQLAgentConfig, tier: str) -> str:
    provider = get_provider(config.llm_provider)
    tier = tier if tier in {"easy", "medium", "hard"} else "hard"
    if provider == "anthropic":
        return ANTHROPIC_SECONDARY_FALLBACK_MODELS.get(tier) or config.secondary_fallback_model
    return config.secondary_fallback_model


def _tier_max_primary_attempts(config: SQLAgentConfig, tier: str) -> int:
    provider = get_provider(config.llm_provider)
    tier = tier if tier in {"easy", "medium", "hard"} else "hard"
    if provider == "anthropic":
        return ANTHROPIC_MAX_PRIMARY_ATTEMPTS.get(tier, config.max_primary_attempts)
    return config.max_primary_attempts


def _router_template_candidate_ids(candidates: list[dict[str, Any]]) -> str:
    ids = []
    for candidate in candidates:
        candidate_id = (
            candidate.get("template_id")
            or candidate.get("candidate_id")
            or candidate.get("id")
        )
        if candidate_id:
            ids.append(str(candidate_id))
    return "|".join(ids)


def _router_template_candidate_scores(candidates: list[dict[str, Any]]) -> str:
    scores = []
    for candidate in candidates:
        score = candidate.get("score")
        if score is not None:
            scores.append(str(score))
    return "|".join(scores)


def _memory_candidate_ids(memory_retrieval: dict[str, Any]) -> str:
    candidates = memory_retrieval.get("candidates", [])
    if not isinstance(candidates, list):
        return ""
    return "|".join(
        str(candidate.get("template_id", ""))
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("template_id")
    )


def _memory_candidate_scores(memory_retrieval: dict[str, Any]) -> str:
    candidates = memory_retrieval.get("candidates", [])
    if not isinstance(candidates, list):
        return ""
    return "|".join(
        str(candidate.get("score", ""))
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("score") is not None
    )


def _format_memory_candidate_trace(memory_retrieval: dict[str, Any]) -> str:
    candidates = memory_retrieval.get("candidates", [])
    if not isinstance(candidates, list) or not candidates:
        return "Memory candidates: none"

    parts = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        terms = candidate.get("matched_terms", [])
        if isinstance(terms, list):
            terms_text = ",".join(str(term) for term in terms)
        else:
            terms_text = ""
        parts.append(
            f"{candidate.get('template_id', '-')}"
            f"(score={candidate.get('score', '-')}, matched_terms={terms_text})"
        )
    return "Memory candidates: " + "; ".join(parts)


def _memory_trace_steps(memory_retrieval: dict[str, Any]) -> list[str]:
    if not memory_retrieval:
        return ["Memory retrieval: not present"]
    scenario = memory_retrieval.get("scenario", "-")
    return [
        (
            "Memory retrieval: "
            f"enabled={memory_retrieval.get('enabled', False)} "
            f"method={memory_retrieval.get('method', '-')} "
            f"scenario={scenario} "
            f"no_match_reason={memory_retrieval.get('no_match_reason', '') or '-'} "
            f"ambiguous={memory_retrieval.get('ambiguous', False)}"
        ),
        f"Memory scenario isolation: active scenario index only ({scenario}).",
        _format_memory_candidate_trace(memory_retrieval),
    ]


def _build_router_context(state: OrchestratorState) -> dict[str, Any]:
    return {
        "intent": state.get("intent", ""),
        "needs_sql": state.get("needs_sql", True),
        "needs_clarification": state.get("needs_clarification", False),
        "blocked_or_unsafe": state.get("blocked_or_unsafe", False),
        "output_mode": state.get("output_mode", ""),
        "language": state.get("language", ""),
        "memory_intent_key": state.get("memory_intent_key", ""),
        "complexity_tier": state.get("complexity_tier", ""),
        "complexity_reason": state.get("complexity_reason", ""),
        "constraints": state.get("constraints", {}),
        "execution_plan": state.get("execution_plan", []),
        "template_candidates": state.get("template_candidates", []),
        "memory_retrieval": state.get("memory_retrieval", {}),
    }


@lru_cache(maxsize=8)
def _semantic_column_metadata_cached(semantic_layer_path: str) -> dict[str, Any]:
    """Load and cache the per-column semantic metadata for the active scenario.

    Cached by the semantic layer file path so the YAML is parsed at most once per
    scenario. Failures degrade to an empty mapping (chart profiler falls back to
    name/value heuristics).
    """
    try:
        return load_semantic_column_metadata(get_active_scenario())
    except Exception:
        return {"columns": {}}


_MONTH_PERIOD_NAME_RE = re.compile(r"yearmonth|year_month|monat|month", re.IGNORECASE)


def _semantic_date_columns(semantic_metadata: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (month-period columns, day-level columns) from the semantic layer."""
    columns = semantic_metadata.get("columns", {}) if isinstance(semantic_metadata, dict) else {}
    month_cols: list[str] = []
    day_cols: list[str] = []
    for name, meta in columns.items():
        semantic_type = str((meta or {}).get("semantic_type", "")).strip().lower()
        if semantic_type == "date_period":
            month_cols.append(str(name))
        elif semantic_type == "date":
            day_cols.append(str(name))
    return month_cols, day_cols


def _maybe_upgrade_chart_to_daily(
    reporting_result: dict[str, Any],
    *,
    result: dict[str, Any],
    semantic_metadata: dict[str, Any],
    user_question: str,
    router_context: dict[str, Any],
) -> dict[str, Any]:
    """Chart-only refinement: when a monthly time series collapsed to a single point,
    re-run the SQL at day granularity for the visualization only.

    Never touches the main answer, table, SQL or query_result. Falls back silently to
    the monthly chart on any failure (rewrite, execution, or empty result).
    """
    chart_plan = reporting_result.get("chart_plan") if isinstance(reporting_result, dict) else None
    if not isinstance(chart_plan, dict) or not chart_plan.get("render_allowed"):
        return reporting_result
    if str(chart_plan.get("chart_type")) not in {"area", "line"}:
        return reporting_result
    # Only act when the time series degenerated to a single time point.
    if int(result.get("row_count", 0) or 0) > 1:
        return reporting_result

    final_sql = str(result.get("final_sql") or result.get("generated_sql") or "")
    if not final_sql.strip():
        return reporting_result

    month_cols, day_cols = _semantic_date_columns(semantic_metadata)
    day_col = next((c for c in day_cols if "day" in c.lower()), day_cols[0] if day_cols else "")
    if not day_col:
        return reporting_result

    x_axis = str(chart_plan.get("x_axis") or "")
    candidates = [c for c in month_cols if re.search(rf"\b{re.escape(c)}\b", final_sql)]
    if not candidates and _MONTH_PERIOD_NAME_RE.search(x_axis) and re.search(rf"\b{re.escape(x_axis)}\b", final_sql):
        candidates = [x_axis]
    if not candidates:
        return reporting_result
    month_col = candidates[0]
    if month_col == day_col:
        return reporting_result

    daily_sql = re.sub(rf"\b{re.escape(month_col)}\b", day_col, final_sql)
    if daily_sql == final_sql:
        return reporting_result

    try:
        daily = execute_read_only_sql(daily_sql, user_question)
    except Exception:
        return reporting_result
    if not isinstance(daily, dict):
        return reporting_result
    rows = list(daily.get("rows") or [])
    if len(rows) <= 1:
        # Nothing finer to show — keep the monthly chart.
        return reporting_result

    daily_qr = {
        "columns": list(daily.get("columns", []) or []),
        "rows": rows,
        "row_count": len(rows),
        "executed_sql": daily_sql,
    }
    daily_plan = build_visualization_spec(
        user_question=user_question,
        router_context=router_context,
        output_mode=str(router_context.get("output_mode", "")),
        query_result=daily_qr,
        execution_success=True,
        validation_success=True,
        row_count=len(rows),
        final_sql=daily_sql,
        source_tables=list(result.get("source_tables", [])),
        semantic_metadata=semantic_metadata,
    )
    if not daily_plan.get("render_allowed"):
        return reporting_result

    note = "Da nur ein Monat Daten enthält, zeigt das Diagramm den Tagesverlauf."
    existing_note = str(daily_plan.get("note") or "").strip()
    daily_plan = {**daily_plan, "note": (f"{existing_note} {note}".strip())}
    reporting_result["chart_plan"] = daily_plan
    reporting_result["chart_query_result"] = daily_qr
    return reporting_result


def _build_reporting_result(
    *,
    user_question: str,
    router_context: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    try:
        semantic_metadata = _semantic_column_metadata_cached(str(get_active_scenario().semantic_layer_path))
        reporting_result = build_reporting_result(
            user_question=user_question,
            router_state=router_context,
            sql=str(result.get("final_sql") or result.get("generated_sql") or ""),
            query_result=result.get("query_result", {}),
            row_count=int(result.get("row_count", 0) or 0),
            source_tables=list(result.get("source_tables", [])),
            execution_success=bool(result.get("execution_success", False)),
            validation_success=bool(result.get("validation_success", result.get("sql_valid", False))),
            language=str(router_context.get("language") or "de"),
            semantic_metadata=semantic_metadata,
        )
        try:  # chart-only daily refinement; must never break the reporting result
            reporting_result = _maybe_upgrade_chart_to_daily(
                reporting_result,
                result=result,
                semantic_metadata=semantic_metadata,
                user_question=user_question,
                router_context=router_context,
            )
        except Exception:
            pass
        return reporting_result
    except Exception as error:
        return _reporting_failure_result(result=result, error=error)


def _reporting_failure_result(*, result: dict[str, Any], error: Exception) -> dict[str, Any]:
    query_result = result.get("query_result", {}) if isinstance(result.get("query_result", {}), dict) else {}
    columns = [str(column) for column in query_result.get("columns", []) or []]
    row_count = int(result.get("row_count", query_result.get("row_count", 0)) or 0)
    chart_plan = {
        "chart_type": "none",
        "x_axis": None,
        "y_axis": None,
        "series": None,
        "title": "",
        "x_label": "",
        "y_label": "",
        "unit": "",
        "reason": "Reporting construction failed.",
        "confidence": 0.0,
        "render_allowed": False,
        "warnings": ["Reporting construction failed."],
        "orientation": "vertical",
        "category_order": [],
        "x_type": "",
        "y_type": "",
        "value_axis_starts_at_zero": False,
        "display_row_limit": 50,
        "truncated": False,
        "note": "",
        "sort": {"mode": "none", "explicit": False},
    }
    return {
        "summary": "",
        "interpretation": "",
        "caveats": [],
        "chart_plan": chart_plan,
        "table_plan": {
            "render_allowed": bool(columns and row_count),
            "row_count": row_count,
            "columns": columns,
            "preserve_sql_order": True,
        },
        "kpi_cards": [],
        "display_notes": [],
        "audit": {
            "reporting_failed": True,
            "reporting_error_type": type(error).__name__,
            "reporting_error_message": str(error),
            "sql_success": bool(
                result.get("execution_success", False)
                and result.get("validation_success", result.get("sql_valid", False))
            ),
            "row_count": row_count,
            "chart_type": "none",
            "rows_visualized": 0,
            "warnings": ["Reporting construction failed."],
            "table_order_preserved": True,
        },
    }


def _format_retry_context_for_router(retry_context: dict[str, Any] | None) -> str:
    if not isinstance(retry_context, dict) or not retry_context:
        return ""

    original_question = str(retry_context.get("original_question", "")).strip()
    previous_answer = str(retry_context.get("previous_assistant_answer", "")).strip()
    user_comment = str(retry_context.get("user_comment", "")).strip()
    previous_router_decision = retry_context.get("previous_router_decision", {})
    if isinstance(previous_router_decision, dict):
        router_decision_text = ", ".join(
            f"{key}={value}"
            for key, value in previous_router_decision.items()
            if value not in (None, "")
        )
    else:
        router_decision_text = str(previous_router_decision or "")

    lines = [
        "RÜCKFRAGE-KONTEXT FÜR ERNEUTE AUSFÜHRUNG:",
        "URSPRÜNGLICHE NUTZERFRAGE:",
        original_question,
        "",
        "RÜCKFRAGE DES SYSTEMS:",
        previous_answer,
        "",
        "ANTWORT DES NUTZERS AUF DIE RÜCKFRAGE:",
        user_comment,
        "",
        "ANWEISUNG:",
        (
            "Die Antwort des Nutzers gehört zur ursprünglichen Nutzerfrage. "
            "Verwende sie zur Disambiguierung der ursprünglichen Frage. "
            "Behandle die Antwort nicht als neue eigenständige Frage. "
            "Stelle dieselbe Rückfrage nicht erneut, wenn die Antwort die "
            "Ambiguität auflöst."
        ),
    ]
    optional_lines = []
    previous_status = str(retry_context.get("previous_status", "")).strip()
    previous_error = str(retry_context.get("previous_error", "")).strip()
    if previous_status:
        optional_lines.append(f"Vorheriger Status: {previous_status}")
    if router_decision_text:
        optional_lines.append(f"Vorherige Router-Entscheidung: {router_decision_text}")
    if previous_error:
        optional_lines.append(f"Vorheriger Fehler: {previous_error}")
    if optional_lines:
        lines.extend(["", "ZUSÄTZLICHER KONTEXT:", *optional_lines])
    return "\n".join(lines).strip()


def _format_retry_context_for_agent(retry_context: dict[str, Any] | None) -> str:
    if not isinstance(retry_context, dict) or not retry_context:
        return ""

    previous_router_decision = retry_context.get("previous_router_decision", {})
    if isinstance(previous_router_decision, dict):
        router_decision_text = ", ".join(
            f"{key}={value}"
            for key, value in previous_router_decision.items()
            if value not in (None, "")
        )
    else:
        router_decision_text = str(previous_router_decision or "")

    lines = [
        "RETRY CONTEXT:",
        f"Original user question: {retry_context.get('original_question', '')}",
        (
            "Previous assistant response / clarification: "
            f"{retry_context.get('previous_assistant_answer', '')}"
        ),
        f"Previous status: {retry_context.get('previous_status', '')}",
        f"Previous router decision: {router_decision_text}",
        f"Previous error: {retry_context.get('previous_error', '')}",
        f"User correction/comment: {retry_context.get('user_comment', '')}",
        f"Active scenario: {retry_context.get('scenario', '')}",
        f"Active profile: {retry_context.get('role_profile', '')}",
        f"Permission role: {retry_context.get('permission_role', '')}",
        (
            "Instruction: The user correction/comment belongs to the original "
            "question. Resolve the original question using this clarification. "
            "Do not treat the correction/comment as a standalone new question."
        ),
    ]
    return "\n".join(line for line in lines if line.strip())


def _merge_retry_context_into_chat_context(
    chat_context: str,
    retry_context: dict[str, Any] | None,
) -> str:
    retry_context_text = _format_retry_context_for_router(retry_context)
    if not retry_context_text:
        return chat_context
    if chat_context.strip():
        return f"{chat_context.rstrip()}\n\n{retry_context_text}"
    return retry_context_text


def _merge_retry_context_into_agent_chat_context(
    chat_context: str,
    retry_context: dict[str, Any] | None,
) -> str:
    retry_context_text = _format_retry_context_for_agent(retry_context)
    if not retry_context_text:
        return chat_context
    if chat_context.strip():
        return f"{chat_context.rstrip()}\n\n{retry_context_text}"
    return retry_context_text


def run_router_node(state: OrchestratorState) -> dict[str, Any]:
    router_chat_context = _merge_retry_context_into_chat_context(
        state.get("chat_context", ""),
        state.get("retry_context", {}),
    )
    router_input: RouterState = {
        "user_question": state.get("user_question", ""),
        "active_scenario": get_active_scenario_id(),
        "llm_provider": state.get("llm_provider", get_provider()),
        "ollama_host": state.get("ollama_host", "http://localhost:11434"),
        "chat_context": router_chat_context,
    }
    result: RouterState = _get_compiled_router().invoke(router_input, {"recursion_limit": 10})

    raw_tier = str(result.get("complexity_tier", "hard")).strip().lower()
    tier = raw_tier if raw_tier in {"easy", "medium", "hard"} else "hard"
    template_candidates = result.get("template_candidates", [])
    memory_retrieval = result.get("memory_retrieval", {})

    return {
        "intent": result.get("intent", "aggregation"),
        "needs_sql": result.get("needs_sql", True),
        "needs_clarification": result.get("needs_clarification", False),
        "blocked_or_unsafe": result.get("blocked_or_unsafe", False),
        "output_mode": result.get("output_mode", "table"),
        "language": result.get("language", "de"),
        "memory_intent_key": result.get("memory_intent_key", "aggregation"),
        "complexity_tier": tier,
        "complexity_reason": result.get("complexity_reason", ""),
        "constraints": result.get("constraints", {}),
        "execution_plan": result.get("execution_plan", []),
        "clarification_question": result.get("clarification_question", ""),
        "template_candidates": template_candidates,
        "memory_retrieval": memory_retrieval,
        "trace_steps": [
            "Router decision",
            f"Intent: {result.get('intent', '-')}",
            f"needs_sql: {result.get('needs_sql')}",
            f"needs_clarification: {result.get('needs_clarification')}",
            f"blocked_or_unsafe: {result.get('blocked_or_unsafe')}",
            f"Complexity tier: {tier}",
            f"Complexity reason: {result.get('complexity_reason', '-')}",
            f"Output mode: {result.get('output_mode', '-')}",
            f"Language: {result.get('language', '-')}",
            f"Memory intent key: {result.get('memory_intent_key', '-')}",
            f"Template candidates: {len(template_candidates)}",
            *_memory_trace_steps(memory_retrieval),
        ],
    }


def select_model(state: OrchestratorState) -> dict[str, Any]:
    raw_tier = str(state.get("complexity_tier", "hard")).strip().lower()
    tier = raw_tier if raw_tier in {"easy", "medium", "hard"} else "hard"
    config = SQLAgentConfig(
        primary_model=state.get("config_primary_model", ""),
        fallback_model=state.get("config_fallback_model", ""),
        max_primary_attempts=int(state.get("config_max_primary_attempts", 2)),
        llm_provider=state.get("llm_provider", get_provider()),
        ollama_host=state.get("ollama_host", os.getenv("OLLAMA_HOST", "http://localhost:11434")),
        secondary_fallback_model=state.get("config_secondary_fallback_model", ""),
    )
    primary = _tier_primary_model(config, tier)
    fallback = _tier_fallback_model(config, tier)
    secondary_fallback = _tier_secondary_fallback_model(config, tier)
    max_attempts = _tier_max_primary_attempts(config, tier)
    trace = state.get("trace_steps", [])

    return {
        "selected_model": primary,
        "primary_model": primary,
        "fallback_model": fallback,
        "secondary_fallback_model": secondary_fallback,
        "max_primary_attempts": max_attempts,
        "trace_steps": [
            *trace,
            (
                f"Model selection: primary={primary} tier={tier} fallback={fallback} "
                f"secondary_fallback={secondary_fallback or '-'} max_attempts={max_attempts}"
            ),
        ],
    }


def _make_run_sql_agent_node(step_callback: StepCallback | None = None):
    def run_sql_agent_node(state: OrchestratorState) -> dict[str, Any]:
        return _run_sql_agent_node_impl(state, step_callback=step_callback)
    return run_sql_agent_node


def run_sql_agent_node(state: OrchestratorState) -> dict[str, Any]:
    return _run_sql_agent_node_impl(state)


def _run_sql_agent_node_impl(state: OrchestratorState, step_callback: StepCallback | None = None) -> dict[str, Any]:
    config = SQLAgentConfig(
        primary_model=state.get("primary_model", state.get("config_primary_model", "")),
        fallback_model=state.get("fallback_model", state.get("config_fallback_model", "")),
        max_primary_attempts=int(
            state.get("max_primary_attempts", state.get("config_max_primary_attempts", 2))
        ),
        llm_provider=state.get("llm_provider", get_provider()),
        ollama_host=state.get("ollama_host", os.getenv("OLLAMA_HOST", "http://localhost:11434")),
        secondary_fallback_model=state.get(
            "secondary_fallback_model",
            state.get("config_secondary_fallback_model", ""),
        ),
    )
    trace = state.get("trace_steps", [])
    trace_extension = []
    if state.get("constraints") or state.get("execution_plan"):
        # TODO: Extend the SQL prompt contract with explicit router context once
        # reporting/template retrieval is implemented. For now these fields stay
        # observable in the orchestrator result and must not influence SQL.
        trace_extension.append("Router context preserved for downstream reporting/template retrieval.")

    router_context = _build_router_context(state)
    result = run_sql_agent(
        state.get("user_question", ""),
        run_id=state.get("run_id"),
        config=config,
        force_fallback=bool(state.get("force_fallback", False)),
        previous_failed_sql=state.get("previous_failed_sql", ""),
        previous_sql_error=state.get("previous_sql_error", ""),
        previous_final_answer=state.get("previous_final_answer", ""),
        user_correction=state.get("user_correction", ""),
        run_context=state.get("run_context", "chat"),
        use_approved_memory=bool(state.get("use_approved_memory", True)),
        use_legacy_memory=False,
        enable_memory_candidate_generation=bool(
            state.get("enable_memory_candidate_generation", True)
        ),
        log_to_query_log=bool(state.get("log_to_query_log", True)),
        language=state.get("language", ""),
        router_context=router_context,
        memory_retrieval=state.get("memory_retrieval", {}),
        step_callback=step_callback,
        chat_context=_merge_retry_context_into_agent_chat_context(
            state.get("chat_context", ""),
            state.get("retry_context", {}),
        ),
    )
    reporting_result = _build_reporting_result(
        user_question=state.get("user_question", ""),
        router_context=router_context,
        result=result,
    )

    return {
        **result,
        "answer": result.get("final_answer", ""),
        "chart_spec": reporting_result["chart_plan"],
        "reporting_result": reporting_result,
        "trace_steps": [*trace, *trace_extension, *result.get("trace_steps", [])],
    }


def terminal_response(state: OrchestratorState) -> dict[str, Any]:
    if state.get("blocked_or_unsafe"):
        answer = state.get(
            "clarification_question",
            "Diese Anfrage kann aus Sicherheitsgründen nicht verarbeitet werden.",
        )
        status = "blocked"
        error_type = "blocked_request"
    elif state.get("needs_clarification"):
        answer = state.get(
            "clarification_question",
            "Könnten Sie Ihre Frage präzisieren?",
        )
        status = "clarification_needed"
        error_type = "clarification_needed"
    else:
        answer = (
            state.get("clarification_question")
            or "Diese Anfrage benötigt keine SQL-Abfrage. Bitte stelle eine konkrete Datenfrage."
        )
        status = "no_sql_needed"
        error_type = ""

    terminal_result = {
        "final_answer": answer,
        "answer": answer,
        "execution_success": False,
        "validation_success": False,
        "fallback_used": False,
        "generated_sql": "",
        "final_sql": "",
        "sql_valid": False,
        "sql_error": "",
        "query_result": {},
        "source_tables": [],
        "row_count": 0,
        "total_attempts": 0,
        "result_status": status,
        "error_type": error_type,
        "error_message": "",
    }
    router_context = _build_router_context(state)
    reporting_result = _build_reporting_result(
        user_question=state.get("user_question", ""),
        router_context=router_context,
        result=terminal_result,
    )
    return {
        **terminal_result,
        "chart_spec": reporting_result["chart_plan"],
        "reporting_result": reporting_result,
    }


def data_overview_response(state: OrchestratorState) -> dict[str, Any]:
    try:
        answer = build_data_overview(get_active_scenario())
    except Exception as error:  # pragma: no cover - defensive
        answer = (
            "Der Datenüberblick konnte nicht erstellt werden: "
            f"{error}"
        )

    overview_result = {
        "final_answer": answer,
        "answer": answer,
        "execution_success": True,
        "validation_success": True,
        "fallback_used": False,
        "generated_sql": "",
        "final_sql": "",
        "sql_valid": True,
        "sql_error": "",
        "query_result": {},
        "source_tables": [],
        "row_count": 0,
        "total_attempts": 0,
        "result_status": "data_overview",
        "error_type": "",
        "error_message": "",
    }
    router_context = _build_router_context(state)
    reporting_result = _build_reporting_result(
        user_question=state.get("user_question", ""),
        router_context=router_context,
        result=overview_result,
    )
    return {
        **overview_result,
        "chart_spec": reporting_result["chart_plan"],
        "reporting_result": reporting_result,
    }


def route_after_router(
    state: OrchestratorState,
) -> Literal["terminal_response", "select_model", "data_overview"]:
    if state.get("intent") == "data_overview":
        return "data_overview"
    if (
        state.get("needs_clarification")
        or state.get("blocked_or_unsafe")
        or not state.get("needs_sql", True)
    ):
        return "terminal_response"
    return "select_model"


def route_after_select_model(
    state: OrchestratorState,
) -> Literal["run_sql_agent", "terminal_response"]:
    if state.get("needs_sql", True):
        return "run_sql_agent"
    return "terminal_response"


def build_orchestrator_graph(step_callback: StepCallback | None = None):
    def _notify_end(node_name: str, start_time: float, metadata: dict[str, Any] | None = None) -> None:
        if step_callback is not None:
            try:
                step_callback(node_name, perf_counter() - start_time, metadata or {})
            except Exception:
                pass

    def _run_router_node_with_callback(state: OrchestratorState) -> dict[str, Any]:
        _start = perf_counter()
        result = run_router_node(state)
        _notify_end("run_router", _start, {
            "intent": result.get("intent", ""),
            "complexity_tier": result.get("complexity_tier", ""),
            "complexity_reason": result.get("complexity_reason", ""),
        })
        return result

    def _select_model_with_callback(state: OrchestratorState) -> dict[str, Any]:
        _start = perf_counter()
        result = select_model(state)
        _notify_end("select_model", _start, {
            "primary": result.get("primary_model", ""),
            "fallback": result.get("fallback_model", ""),
            "tier": state.get("complexity_tier", ""),
        })
        return result

    def _terminal_response_with_callback(state: OrchestratorState) -> dict[str, Any]:
        _start = perf_counter()
        result = terminal_response(state)
        _notify_end("terminal_response", _start)
        return result

    def _data_overview_with_callback(state: OrchestratorState) -> dict[str, Any]:
        _start = perf_counter()
        result = data_overview_response(state)
        _notify_end("data_overview", _start)
        return result

    graph = StateGraph(OrchestratorState)
    graph.add_node("run_router", _run_router_node_with_callback)
    graph.add_node("select_model", _select_model_with_callback)
    graph.add_node("run_sql_agent", _make_run_sql_agent_node(step_callback))
    graph.add_node("terminal_response", _terminal_response_with_callback)
    graph.add_node("data_overview", _data_overview_with_callback)
    graph.add_edge(START, "run_router")
    graph.add_conditional_edges("run_router", route_after_router)
    graph.add_conditional_edges("select_model", route_after_select_model)
    graph.add_edge("run_sql_agent", END)
    graph.add_edge("terminal_response", END)
    graph.add_edge("data_overview", END)
    return graph.compile()


_ROUTER_LOG_FIELDS = [
    "run_id",
    "timestamp",
    "user_question",
    "intent",
    "needs_sql",
    "needs_clarification",
    "blocked_or_unsafe",
    "complexity_tier",
    "output_mode",
    "language",
    "memory_intent_key",
    "selected_model",
    "fallback_model",
    "force_fallback",
    "template_candidate_ids",
    "template_candidate_scores",
    "memory_retrieval_enabled",
    "memory_retrieval_method",
    "memory_retrieval_scenario",
    "memory_retrieval_no_match_reason",
    "memory_retrieval_ambiguous",
    "memory_candidate_ids",
    "memory_candidate_scores",
    "execution_success",
    "row_count",
    "error_type",
]


def _log_router(run_id: str, state: OrchestratorState) -> None:
    candidates = state.get("template_candidates", [])
    memory_retrieval = state.get("memory_retrieval", {})
    try:
        append_csv_row(
            get_log_dir() / "router_log.csv",
            _ROUTER_LOG_FIELDS,
            {
                "run_id": run_id,
                "timestamp": current_timestamp(),
                "user_question": state.get("user_question", ""),
                "intent": state.get("intent", ""),
                "needs_sql": state.get("needs_sql", ""),
                "needs_clarification": state.get("needs_clarification", ""),
                "blocked_or_unsafe": state.get("blocked_or_unsafe", ""),
                "complexity_tier": state.get("complexity_tier", ""),
                "output_mode": state.get("output_mode", ""),
                "language": state.get("language", ""),
                "memory_intent_key": state.get("memory_intent_key", ""),
                "selected_model": state.get("selected_model", state.get("model_used", "")),
                "fallback_model": state.get("fallback_model", ""),
                "force_fallback": state.get("force_fallback", False),
                "template_candidate_ids": _router_template_candidate_ids(candidates),
                "template_candidate_scores": _router_template_candidate_scores(candidates),
                "memory_retrieval_enabled": memory_retrieval.get("enabled", ""),
                "memory_retrieval_method": memory_retrieval.get("method", ""),
                "memory_retrieval_scenario": memory_retrieval.get("scenario", ""),
                "memory_retrieval_no_match_reason": memory_retrieval.get("no_match_reason", ""),
                "memory_retrieval_ambiguous": memory_retrieval.get("ambiguous", ""),
                "memory_candidate_ids": _memory_candidate_ids(memory_retrieval),
                "memory_candidate_scores": _memory_candidate_scores(memory_retrieval),
                "execution_success": state.get("execution_success", ""),
                "row_count": state.get("row_count", ""),
                "error_type": state.get("error_type", ""),
            },
        )
    except Exception:
        pass


def _initial_state(
    user_question: str,
    *,
    run_id: str,
    config: SQLAgentConfig,
    force_fallback: bool,
    previous_failed_sql: str,
    previous_sql_error: str,
    previous_final_answer: str,
    user_correction: str,
    run_context: str,
    use_approved_memory: bool,
    enable_memory_candidate_generation: bool,
    log_to_query_log: bool,
    chat_context: str = "",
    retry_context: dict[str, Any] | None = None,
) -> OrchestratorState:
    return {
        "run_id": run_id,
        "user_question": user_question,
        "chat_context": chat_context,
        "retry_context": dict(retry_context or {}),
        "llm_provider": config.llm_provider,
        "ollama_host": config.ollama_host,
        "trace_steps": [],
        "query_result": {},
        "source_tables": [],
        "execution_success": False,
        "validation_success": False,
        "row_count": 0,
        "total_attempts": 0,
        "fallback_used": False,
        "template_candidates": [],
        "memory_retrieval": {},
        "previous_failed_sql": previous_failed_sql,
        "previous_sql_error": previous_sql_error,
        "previous_final_answer": previous_final_answer,
        "user_correction": user_correction,
        "run_context": run_context,
        "use_approved_memory": use_approved_memory,
        "enable_memory_candidate_generation": enable_memory_candidate_generation,
        "log_to_query_log": log_to_query_log,
        "force_fallback": force_fallback,
        "config_primary_model": config.primary_model,
        "config_fallback_model": config.fallback_model,
        "config_secondary_fallback_model": config.secondary_fallback_model,
        "config_max_primary_attempts": config.max_primary_attempts,
    }


def _run_forced_fallback(
    user_question: str,
    *,
    run_id: str,
    config: SQLAgentConfig,
    initial: OrchestratorState,
    step_callback: StepCallback | None = None,
) -> OrchestratorState:
    fallback_config = SQLAgentConfig(
        primary_model=config.fallback_model,
        fallback_model=config.fallback_model,
        max_primary_attempts=config.max_primary_attempts,
        llm_provider=config.llm_provider,
        ollama_host=config.ollama_host,
        secondary_fallback_model=config.fallback_model,
    )
    forced_router_context = {
        "intent": "forced_fallback",
        "needs_sql": True,
        "needs_clarification": False,
        "blocked_or_unsafe": False,
        "output_mode": "table",
        "language": "",
        "memory_intent_key": "",
        "complexity_tier": "hard",
        "complexity_reason": "force_fallback",
        "constraints": {},
        "execution_plan": ["run_sql_agent"],
        "template_candidates": [],
        "memory_retrieval": {},
    }
    retry_context = initial.get("retry_context", {})
    if retry_context:
        forced_router_context["retry_context"] = retry_context
    result = run_sql_agent(
        user_question,
        run_id=run_id,
        config=fallback_config,
        force_fallback=True,
        previous_failed_sql=initial.get("previous_failed_sql", ""),
        previous_sql_error=initial.get("previous_sql_error", ""),
        previous_final_answer=initial.get("previous_final_answer", ""),
        user_correction=initial.get("user_correction", ""),
        run_context=initial.get("run_context", "chat"),
        use_approved_memory=bool(initial.get("use_approved_memory", True)),
        use_legacy_memory=False,
        enable_memory_candidate_generation=bool(
            initial.get("enable_memory_candidate_generation", True)
        ),
        log_to_query_log=bool(initial.get("log_to_query_log", True)),
        router_context=forced_router_context,
        memory_retrieval=forced_router_context.get("memory_retrieval", {}),
        step_callback=step_callback,
        chat_context=_merge_retry_context_into_agent_chat_context(
            initial.get("chat_context", ""),
            retry_context,
        ),
    )
    reporting_result = _build_reporting_result(
        user_question=user_question,
        router_context=forced_router_context,
        result=result,
    )
    trace = [
        "Router skipped because force_fallback=True.",
        *result.get("trace_steps", []),
    ]
    return {
        **initial,
        **result,
        "intent": "forced_fallback",
        "needs_sql": True,
        "needs_clarification": False,
        "blocked_or_unsafe": False,
        "output_mode": "table",
        "language": "",
        "memory_intent_key": "",
        "complexity_tier": "hard",
        "complexity_reason": "force_fallback",
        "selected_model": config.fallback_model,
        "primary_model": config.fallback_model,
        "fallback_model": config.fallback_model,
        "max_primary_attempts": config.max_primary_attempts,
        "template_candidates": [],
        "memory_retrieval": {},
        "chart_spec": reporting_result["chart_plan"],
        "reporting_result": reporting_result,
        "answer": result.get("final_answer", ""),
        "trace_steps": trace,
    }


def run_orchestrator(
    user_question: str,
    *,
    config: Any = None,
    force_fallback: bool = False,
    previous_failed_sql: str = "",
    previous_sql_error: str = "",
    previous_final_answer: str = "",
    user_correction: str = "",
    run_context: str = "chat",
    use_approved_memory: bool = True,
    enable_memory_candidate_generation: bool = True,
    log_to_query_log: bool = True,
    step_callback: StepCallback | None = None,
    chat_context: str = "",
    retry_context: dict[str, Any] | None = None,
) -> OrchestratorState:
    sql_config = _coerce_sql_config(config)
    run_id = generate_run_id()
    started = perf_counter()
    reset_token_usage()
    initial = _initial_state(
        user_question,
        run_id=run_id,
        config=sql_config,
        force_fallback=force_fallback,
        previous_failed_sql=previous_failed_sql,
        previous_sql_error=previous_sql_error,
        previous_final_answer=previous_final_answer,
        user_correction=user_correction,
        run_context=run_context,
        use_approved_memory=use_approved_memory,
        enable_memory_candidate_generation=enable_memory_candidate_generation,
        log_to_query_log=log_to_query_log,
        chat_context=chat_context,
        retry_context=retry_context,
    )

    if force_fallback:
        final = _run_forced_fallback(
            user_question,
            run_id=run_id,
            config=sql_config,
            initial=initial,
            step_callback=step_callback,
        )
    else:
        final = build_orchestrator_graph(step_callback=step_callback).invoke(initial, {"recursion_limit": 50})

    final["latency_seconds"] = perf_counter() - started
    final["run_id"] = run_id
    final["user_question"] = user_question
    final["force_fallback"] = force_fallback
    final.setdefault("template_candidates", [])
    final.setdefault("memory_retrieval", {})
    if retry_context:
        final["retry_context"] = dict(retry_context)
    final["token_usage"] = get_token_usage()

    if log_to_query_log:
        _log_router(run_id, final)

    return final
