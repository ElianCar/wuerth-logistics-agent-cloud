from __future__ import annotations

import os
from time import perf_counter
from typing import Any, Literal

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src.agent.id_utils import generate_run_id
from src.agent.langgraph_sql_agent import (
    SQLAgentConfig,
    SQLAgentState,
    build_sql_agent_graph,
    load_schema_context,
    default_sql_generator,
    execute_read_only_sql,
    log_query_attempt,
    noop_attempt_logger,
)
from src.agent.logging_utils import append_csv_row, get_log_dir, current_timestamp
from src.agent.router import RouterState, build_router_graph
from src.llm.model_adapter import get_provider

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Modell-Konfiguration — zwei Tiers
#
#   "easy" → gemini-2.0-flash-lite  (eine Tabelle, einfache Aggregation)
#   "hard" → gemini-2.5-flash       (Joins, Zeitreihen, mehrere KPIs)
#
# Fallback ist immer das hard-Modell, unabhängig vom Tier.
# Werte per .env überschreibbar.
# ─────────────────────────────────────────────────────────────────────────────
GEMINI_TIER_MODELS = {
    "easy": os.getenv("GEMINI_EASY_MODEL",  "gemini-2.0-flash-lite"),
    "hard": os.getenv("GEMINI_HARD_MODEL",  "gemini-2.5-flash"),
}
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")

OLLAMA_TIER_MODELS = {
    "easy": os.getenv("OLLAMA_EASY_MODEL", "llama3.2:3b"),
    "hard": os.getenv("OLLAMA_HARD_MODEL", "llama3.1:8b"),
}
OLLAMA_FALLBACK_MODEL = os.getenv("OLLAMA_FALLBACK_MODEL", "llama3.1:8b")


# ─────────────────────────────────────────────────────────────────────────────
# OrchestratorState
# Vereint alle Felder aus RouterState + SQLAgentState
# ─────────────────────────────────────────────────────────────────────────────
class OrchestratorState(TypedDict, total=False):
    # Basis
    run_id: str
    user_question: str
    llm_provider: str
    ollama_host: str

    # Vom Router befüllt
    intent: str
    needs_sql: bool
    needs_clarification: bool
    blocked_or_unsafe: bool
    output_mode: str
    language: str
    memory_intent_key: str
    complexity_tier: str
    complexity_reason: str
    constraints: dict
    execution_plan: list
    clarification_question: str

    # Von select_model befüllt
    selected_model: str
    primary_model: str
    fallback_model: str
    max_primary_attempts: int

    # Vom SQL-Agent befüllt
    schema_context: str
    generated_sql: str
    final_sql: str
    sql_valid: bool
    sql_error: str
    query_result: dict
    execution_success: bool
    validation_success: bool
    fallback_used: bool
    source_tables: list
    row_count: int
    total_attempts: int
    result_status: str
    error_type: str
    error_message: str
    latency_seconds: float
    trace_steps: list
    final_answer: str
    answer: str
    schema_load_failed: bool


# ─────────────────────────────────────────────────────────────────────────────
# Node: run_router
# ─────────────────────────────────────────────────────────────────────────────
_compiled_router = None


def _get_compiled_router():
    global _compiled_router
    if _compiled_router is None:
        _compiled_router = build_router_graph()
    return _compiled_router


def run_router_node(state: OrchestratorState) -> dict[str, Any]:
    router_input: RouterState = {
        "user_question": state.get("user_question", ""),
        "llm_provider":  state.get("llm_provider", get_provider()),
        "ollama_host":   state.get("ollama_host", "http://localhost:11434"),
    }
    result: RouterState = _get_compiled_router().invoke(router_input, {"recursion_limit": 10})

    tier = "easy" if result.get("complexity_tier") == "easy" else "hard"

    return {
        "intent":                 result.get("intent", "aggregation"),
        "needs_sql":              result.get("needs_sql", True),
        "needs_clarification":    result.get("needs_clarification", False),
        "blocked_or_unsafe":      result.get("blocked_or_unsafe", False),
        "output_mode":            result.get("output_mode", "table"),
        "language":               result.get("language", "de"),
        "memory_intent_key":      result.get("memory_intent_key", "aggregation"),
        "complexity_tier":        tier,
        "complexity_reason":      result.get("complexity_reason", ""),
        "constraints":            result.get("constraints", {}),
        "execution_plan":         result.get("execution_plan", []),
        "clarification_question": result.get("clarification_question", ""),
        "trace_steps": [
            f"── Router Entscheidung ──────────────────────",
            f"Intent:              {result.get('intent', '—')}",
            f"needs_sql:           {result.get('needs_sql')}",
            f"needs_clarification: {result.get('needs_clarification')}",
            f"blocked_or_unsafe:   {result.get('blocked_or_unsafe')}",
            f"Complexity Tier:     {tier}",
            f"Complexity Reason:   {result.get('complexity_reason', '—')}",
            f"Output Mode:         {result.get('output_mode', '—')}",
            f"Language:            {result.get('language', '—')}",
            f"Execution Plan:      {' → '.join(result.get('execution_plan', []))}",
            f"Constraints:         {result.get('constraints', {})}",
            f"────────────────────────────────────────────",
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node: select_model
# Wählt Primary- und Fallback-Modell anhand des complexity_tier
# ─────────────────────────────────────────────────────────────────────────────
def select_model(state: OrchestratorState) -> dict[str, Any]:
    tier     = "easy" if state.get("complexity_tier") == "easy" else "hard"
    provider = state.get("llm_provider", get_provider())

    if provider == "gemini":
        primary  = GEMINI_TIER_MODELS[tier]
        fallback = GEMINI_FALLBACK_MODEL
    else:
        primary  = OLLAMA_TIER_MODELS[tier]
        fallback = OLLAMA_FALLBACK_MODEL

    max_attempts = int(os.getenv("MAX_PRIMARY_ATTEMPTS", "2"))
    trace = state.get("trace_steps", [])

    return {
        "selected_model":      primary,
        "primary_model":       primary,
        "fallback_model":      fallback,
        "max_primary_attempts": max_attempts,
       "trace_steps": [*trace, f"── Modell Auswahl ── Primary: {primary} | Tier: {tier} | Fallback: {fallback} | Max Versuche: {max_attempts}"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node: run_sql_agent
# Ruft den bestehenden SQL-Agent mit den vom Orchestrator gewählten Modellen
# ─────────────────────────────────────────────────────────────────────────────
def run_sql_agent_node(state: OrchestratorState) -> dict[str, Any]:
    provider = state.get("llm_provider", get_provider())
    config = SQLAgentConfig(
        primary_model=state.get("primary_model", GEMINI_TIER_MODELS["hard"]),
        fallback_model=state.get("fallback_model", GEMINI_FALLBACK_MODEL),
        max_primary_attempts=state.get("max_primary_attempts", 2),
        llm_provider=provider,
        ollama_host=state.get("ollama_host", os.getenv("OLLAMA_HOST", "http://localhost:11434")),
    )

    graph = build_sql_agent_graph(
        schema_loader=load_schema_context,
        sql_generator=default_sql_generator,
        sql_executor=execute_read_only_sql,
        attempt_logger=noop_attempt_logger,  # Logging übernimmt run_orchestrator
    )

    initial: SQLAgentState = {
        "run_id":            state.get("run_id", ""),
        "user_question":     state.get("user_question", ""),
        "question":          state.get("user_question", ""),
        "selected_model":    config.primary_model,
        "model_used":        config.primary_model,
        "attempt_number":    0,
        "max_primary_attempts": config.max_primary_attempts,
        "fallback_used":     False,
        "schema_context":    "",
        "generated_sql":     "",
        "sql_valid":         False,
        "sql_error":         "",
        "query_result":      {},
        "final_answer":      "",
        "answer":            "",
        "final_sql":         "",
        "validation_success": False,
        "error_type":        "",
        "error_message":     "",
        "row_count":         0,
        "latency_seconds":   0.0,
        "trace_steps":       state.get("trace_steps", []),
        "source_tables":     [],
        "execution_success": False,
        "result_status":     "",
        "schema_load_failed": False,
        "run_context":       "orchestrator",
        "use_approved_memory": True,
        "enable_memory_candidate_generation": True,
        "log_to_query_log":  False,
        "primary_model":     config.primary_model,
        "fallback_model":    config.fallback_model,
        "total_attempts":    0,
    }

    result: SQLAgentState = graph.invoke(initial, {"recursion_limit": 30})

    return {
        "schema_context":    result.get("schema_context", ""),
        "generated_sql":     result.get("generated_sql", ""),
        "final_sql":         result.get("final_sql", ""),
        "sql_valid":         result.get("sql_valid", False),
        "sql_error":         result.get("sql_error", ""),
        "query_result":      result.get("query_result", {}),
        "execution_success": result.get("execution_success", False),
        "validation_success": result.get("validation_success", False),
        "fallback_used":     result.get("fallback_used", False),
        "source_tables":     result.get("source_tables", []),
        "row_count":         result.get("row_count", 0),
        "total_attempts":    result.get("total_attempts", 0),
        "result_status":     result.get("result_status", ""),
        "error_type":        result.get("error_type", ""),
        "error_message":     result.get("error_message", ""),
        "final_answer":      result.get("final_answer", ""),
        "answer":            result.get("final_answer", ""),
        "schema_load_failed": result.get("schema_load_failed", False),
        "trace_steps":       result.get("trace_steps", []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node: clarification_response
# Gibt Rückfrage oder Sicherheitsstopp als finale Antwort zurück
# ─────────────────────────────────────────────────────────────────────────────
def clarification_response(state: OrchestratorState) -> dict[str, Any]:
    if state.get("blocked_or_unsafe"):
        answer = "Diese Anfrage kann aus Sicherheitsgründen nicht verarbeitet werden."
        status = "blocked"
    else:
        answer = state.get("clarification_question", "Könnten Sie Ihre Frage präzisieren?")
        status = "clarification_needed"
    return {
        "final_answer":      answer,
        "answer":            answer,
        "execution_success": False,
        "result_status":     status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Conditional Edges
# ─────────────────────────────────────────────────────────────────────────────
def route_after_router(
    state: OrchestratorState,
) -> Literal["clarification_response", "select_model"]:
    if state.get("needs_clarification") or state.get("blocked_or_unsafe"):
        return "clarification_response"
    return "select_model"


def route_after_select_model(
    state: OrchestratorState,
) -> Literal["run_sql_agent", "clarification_response"]:
    if state.get("needs_sql", True):
        return "run_sql_agent"
    # needs_sql=false: kein SQL-Agent, direkte Antwort
    return "clarification_response"


# ─────────────────────────────────────────────────────────────────────────────
# OrchestratorGraph
# ─────────────────────────────────────────────────────────────────────────────
def build_orchestrator_graph():
    graph = StateGraph(OrchestratorState)
    graph.add_node("run_router",             run_router_node)
    graph.add_node("select_model",           select_model)
    graph.add_node("run_sql_agent",          run_sql_agent_node)
    graph.add_node("clarification_response", clarification_response)
    graph.add_edge(START, "run_router")
    graph.add_conditional_edges("run_router",      route_after_router)
    graph.add_conditional_edges("select_model",    route_after_select_model)
    graph.add_edge("run_sql_agent",          END)
    graph.add_edge("clarification_response", END)
    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Router-Log
# ─────────────────────────────────────────────────────────────────────────────
_ROUTER_LOG_FIELDS = [
    "run_id", "timestamp", "question",
    "intent", "needs_sql", "complexity_tier", "complexity_reason",
    "output_mode", "language", "selected_model", "fallback_model",
]


def _log_router(run_id: str, state: OrchestratorState) -> None:
    try:
        append_csv_row(
            get_log_dir() / "router_log.csv",
            _ROUTER_LOG_FIELDS,
            {
                "run_id":            run_id,
                "timestamp":         current_timestamp(),
                "question":          state.get("user_question", ""),
                "intent":            state.get("intent", ""),
                "needs_sql":         state.get("needs_sql", ""),
                "complexity_tier":   state.get("complexity_tier", ""),
                "complexity_reason": state.get("complexity_reason", ""),
                "output_mode":       state.get("output_mode", ""),
                "language":          state.get("language", ""),
                "selected_model":    state.get("selected_model", ""),
                "fallback_model":    state.get("fallback_model", ""),
            },
        )
    except Exception:
        pass  # Logging darf den Agent nie blockieren


# ─────────────────────────────────────────────────────────────────────────────
# run_orchestrator — Haupteinstieg, ersetzt run_sql_agent in streamlit_app.py
# ─────────────────────────────────────────────────────────────────────────────
def run_orchestrator(
    user_question: str,
    *,
    config: Any = None,              # SQLAgentConfig — wird ignoriert, Modell kommt vom Router
    force_fallback: bool = False,
    previous_failed_sql: str = "",
    previous_sql_error: str = "",
    previous_final_answer: str = "",
    user_correction: str = "",
    run_context: str = "chat",
    use_approved_memory: bool = True,
    enable_memory_candidate_generation: bool = True,
    log_to_query_log: bool = True,
) -> OrchestratorState:
    run_id   = generate_run_id()
    provider = get_provider()
    started  = perf_counter()

    initial: OrchestratorState = {
        "run_id":        run_id,
        "user_question": user_question,
        "llm_provider":  provider,
        "ollama_host":   os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        "trace_steps":   [],
        "query_result":  {},
        "source_tables": [],
        "execution_success": False,
    }

    # force_fallback: Router überspringen, direkt stärkstes Modell
    if force_fallback:
        fallback = GEMINI_FALLBACK_MODEL if provider == "gemini" else OLLAMA_FALLBACK_MODEL
        initial.update({
            "complexity_tier":   "hard",
            "complexity_reason": "force_fallback",
            "selected_model":    fallback,
            "primary_model":     fallback,
            "fallback_model":    fallback,
            "needs_sql":         True,
            "needs_clarification": False,
            "blocked_or_unsafe": False,
        })

    final: OrchestratorState = build_orchestrator_graph().invoke(
        initial, {"recursion_limit": 50}
    )
    final["latency_seconds"] = perf_counter() - started

    if log_to_query_log:
        _log_router(run_id, final)

    return final
