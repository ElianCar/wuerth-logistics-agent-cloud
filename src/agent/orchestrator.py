from __future__ import annotations

import os
from time import perf_counter
from typing import Any, Literal

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src.agent.id_utils import generate_run_id
from src.agent.langgraph_sql_agent import SQLAgentConfig, run_sql_agent
from src.agent.logging_utils import append_csv_row, current_timestamp, get_log_dir
from src.agent.router import RouterState, build_router_graph
from src.llm.model_adapter import get_provider

load_dotenv()


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

    selected_model: str
    model_used: str
    primary_model: str
    fallback_model: str
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
    )


def _tier_primary_model(config: SQLAgentConfig, tier: str) -> str:
    provider = get_provider(config.llm_provider)
    tier = tier if tier in {"easy", "medium", "hard"} else "hard"
    if provider == "gemini":
        return GEMINI_TIER_MODELS.get(tier) or config.primary_model
    return OLLAMA_TIER_MODELS.get(tier) or config.primary_model


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
    }


def run_router_node(state: OrchestratorState) -> dict[str, Any]:
    router_input: RouterState = {
        "user_question": state.get("user_question", ""),
        "llm_provider": state.get("llm_provider", get_provider()),
        "ollama_host": state.get("ollama_host", "http://localhost:11434"),
    }
    result: RouterState = _get_compiled_router().invoke(router_input, {"recursion_limit": 10})

    raw_tier = str(result.get("complexity_tier", "hard")).strip().lower()
    tier = raw_tier if raw_tier in {"easy", "medium", "hard"} else "hard"
    template_candidates = result.get("template_candidates", [])

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
    )
    primary = _tier_primary_model(config, tier)
    fallback = config.fallback_model
    max_attempts = config.max_primary_attempts
    trace = state.get("trace_steps", [])

    return {
        "selected_model": primary,
        "primary_model": primary,
        "fallback_model": fallback,
        "max_primary_attempts": max_attempts,
        "trace_steps": [
            *trace,
            f"Model selection: primary={primary} tier={tier} fallback={fallback} max_attempts={max_attempts}",
        ],
    }


def run_sql_agent_node(state: OrchestratorState) -> dict[str, Any]:
    config = SQLAgentConfig(
        primary_model=state.get("primary_model", state.get("config_primary_model", "")),
        fallback_model=state.get("fallback_model", state.get("config_fallback_model", "")),
        max_primary_attempts=int(
            state.get("max_primary_attempts", state.get("config_max_primary_attempts", 2))
        ),
        llm_provider=state.get("llm_provider", get_provider()),
        ollama_host=state.get("ollama_host", os.getenv("OLLAMA_HOST", "http://localhost:11434")),
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
        enable_memory_candidate_generation=bool(
            state.get("enable_memory_candidate_generation", True)
        ),
        log_to_query_log=bool(state.get("log_to_query_log", True)),
        language=state.get("language", ""),
        router_context=router_context,
    )

    return {
        **result,
        "answer": result.get("final_answer", ""),
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

    return {
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


def route_after_router(
    state: OrchestratorState,
) -> Literal["terminal_response", "select_model"]:
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


def build_orchestrator_graph():
    graph = StateGraph(OrchestratorState)
    graph.add_node("run_router", run_router_node)
    graph.add_node("select_model", select_model)
    graph.add_node("run_sql_agent", run_sql_agent_node)
    graph.add_node("terminal_response", terminal_response)
    graph.add_edge(START, "run_router")
    graph.add_conditional_edges("run_router", route_after_router)
    graph.add_conditional_edges("select_model", route_after_select_model)
    graph.add_edge("run_sql_agent", END)
    graph.add_edge("terminal_response", END)
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
    "execution_success",
    "row_count",
    "error_type",
]


def _log_router(run_id: str, state: OrchestratorState) -> None:
    candidates = state.get("template_candidates", [])
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
) -> OrchestratorState:
    return {
        "run_id": run_id,
        "user_question": user_question,
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
        "config_max_primary_attempts": config.max_primary_attempts,
    }


def _run_forced_fallback(
    user_question: str,
    *,
    run_id: str,
    config: SQLAgentConfig,
    initial: OrchestratorState,
) -> OrchestratorState:
    fallback_config = SQLAgentConfig(
        primary_model=config.fallback_model,
        fallback_model=config.fallback_model,
        max_primary_attempts=config.max_primary_attempts,
        llm_provider=config.llm_provider,
        ollama_host=config.ollama_host,
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
    }
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
        enable_memory_candidate_generation=bool(
            initial.get("enable_memory_candidate_generation", True)
        ),
        log_to_query_log=bool(initial.get("log_to_query_log", True)),
        router_context=forced_router_context,
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
) -> OrchestratorState:
    sql_config = _coerce_sql_config(config)
    run_id = generate_run_id()
    started = perf_counter()
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
    )

    if force_fallback:
        final = _run_forced_fallback(
            user_question,
            run_id=run_id,
            config=sql_config,
            initial=initial,
        )
    else:
        final = build_orchestrator_graph().invoke(initial, {"recursion_limit": 50})

    final["latency_seconds"] = perf_counter() - started
    final["run_id"] = run_id
    final["user_question"] = user_question
    final["force_fallback"] = force_fallback
    final.setdefault("template_candidates", [])

    if log_to_query_log:
        _log_router(run_id, final)

    return final
