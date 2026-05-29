from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src.agent.router_template_retriever import find_similar_templates_for_router
from src.llm.model_adapter import invoke_model, get_provider


load_dotenv()

ROUTER_EXCERPT_PATH = Path(
    os.getenv("ROUTER_EXCERPT_PATH", "semantic_layer/router_excerpt.yaml")
)

DETERMINISTIC_BLOCK_PATTERNS = (
    (re.compile(r"\bdrop\s+table\b", re.IGNORECASE), "drop table"),
    (re.compile(r"\bdelete\s+from\b", re.IGNORECASE), "delete from"),
    (re.compile(r"\bupdate\s+[a-zA-Z_][a-zA-Z0-9_]*\b", re.IGNORECASE), "update"),
    (re.compile(r"\binsert\s+into\b", re.IGNORECASE), "insert"),
    (re.compile(r"\balter\s+table\b", re.IGNORECASE), "alter table"),
    (re.compile(r"\btruncate\b", re.IGNORECASE), "truncate"),
    (re.compile(r"\bshow\s+credentials\b", re.IGNORECASE), "show credentials"),
    (re.compile(r"\breveal\s+(?:the\s+)?api\s+key\b", re.IGNORECASE), "reveal api key"),
    (re.compile(r"\bignore\s+previous\s+instructions\b", re.IGNORECASE), "ignore previous instructions"),
)


# ─────────────────────────────────────────────────────────────────────────────
# RouterState
#
# complexity_tier:
#   "easy" → gemini-3.1-flash-lite  (eine Tabelle, einfache Aggregation)
#   "medium" → gemini-3.1-flash-lite (Ranking, einfache Gruppierung, einfacher JOIN)
#   "hard" → konfiguriertes Primary-Modell (Zeitreihen, Subqueries, mehrere KPIs)
#
# Fallback ist immer gemini-2.5-flash.
# ─────────────────────────────────────────────────────────────────────────────
class RouterState(TypedDict, total=False):
    user_question: str
    llm_provider: str
    ollama_host: str

    intent: str                # aggregation | ranking | time_series | cross_table | explanation
    needs_sql: bool
    needs_clarification: bool
    blocked_or_unsafe: bool
    output_mode: str           # table | chart_plus_table | management_summary | technical_detail
    language: str              # de | en
    memory_intent_key: str     # = intent, für Template-Retrieval
    complexity_tier: str       # "easy" | "medium" | "hard"
    complexity_reason: str
    constraints: dict          # time_window, grouping_level
    execution_plan: list
    clarification_question: str
    template_candidates: list[dict[str, Any]]
    _router_raw_response: str


def load_router_excerpt() -> dict[str, Any]:
    if not ROUTER_EXCERPT_PATH.exists():
        raise FileNotFoundError(f"Router excerpt nicht gefunden: {ROUTER_EXCERPT_PATH}")
    with ROUTER_EXCERPT_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _format_excerpt_for_prompt(excerpt: dict[str, Any]) -> str:
    domain       = excerpt.get("data_domain", "business data")
    data_types   = excerpt.get("available_data", [])
    qtypes       = excerpt.get("question_types", {})
    hard_signals = excerpt.get("complexity_signals", {}).get("hard", [])
    medium_signals = excerpt.get("complexity_signals", {}).get("medium", [])
    easy_signals = excerpt.get("complexity_signals", {}).get("easy", [])
    no_sql       = excerpt.get("no_sql_signals", [])
    blocked      = excerpt.get("blocked", [])

    qtype_lines = "\n".join(
        f"  {name}: needs_sql={v.get('needs_sql')}, complexity={v.get('complexity')}"
        for name, v in qtypes.items()
    )
    return (
        f"DOMAIN: {domain}\n"
        f"DATA CATEGORIES: {', '.join(data_types)}\n"
        f"QUESTION TYPES:\n{qtype_lines}\n"
        f"HARD COMPLEXITY SIGNALS: {', '.join(hard_signals)}\n"
        f"MEDIUM COMPLEXITY SIGNALS: {', '.join(medium_signals)}\n"
        f"EASY COMPLEXITY SIGNALS: {', '.join(easy_signals)}\n"
        f"NO SQL WHEN QUESTION CONTAINS: {', '.join(no_sql)}\n"
        f"BLOCKED PATTERNS: {', '.join(blocked)}"
    )


def build_router_prompt(question: str, excerpt_text: str) -> str:
    return f"""Classify this user question for a data analytics system.
Reply ONLY with a JSON object. No markdown, no explanation, no code fences.

CONTEXT:
{excerpt_text}

CLASSIFICATION RULES:
- intent: one of the question_types above (aggregation/ranking/time_series/cross_table/explanation)
- needs_sql: false only when question matches no_sql_signals, true otherwise
- needs_clarification: true only when too vague to act on (e.g. "how is it going?"). Default false.
- blocked_or_unsafe: true when blocked patterns appear
- complexity_tier:
    "easy" → single table, simple aggregation (COUNT/SUM/AVG), no JOIN, no time comparison
    "medium" → simple ranking, simple grouping, or one straightforward JOIN without subqueries
    "hard" → requires multiple JOINs, time series/trends, period comparisons, subqueries, or multiple metrics
  When in doubt: "hard".
- complexity_reason: one short sentence
- output_mode: "table" | "chart_plus_table" | "management_summary" | "technical_detail"
- language: "de" or "en" based on question language
- memory_intent_key: same as intent
- constraints.time_window: extracted time period or null
- constraints.grouping_level: extracted grouping dimension(s) or []
- execution_plan: ["retrieve_templates","run_sql_agent","run_reporting_agent"] if needs_sql, else ["run_reporting_agent"]
- clarification_question: only when needs_clarification=true, in question language

QUESTION: {question}

JSON:
{{
  "intent": "...",
  "needs_sql": true,
  "needs_clarification": false,
  "blocked_or_unsafe": false,
  "output_mode": "...",
  "language": "...",
  "memory_intent_key": "...",
  "complexity_tier": "easy|medium|hard",
  "complexity_reason": "...",
  "constraints": {{
    "time_window": null,
    "grouping_level": []
  }},
  "execution_plan": [],
  "clarification_question": ""
}}"""


def _get_router_model(llm_provider: str) -> str:
    if llm_provider == "gemini":
        return os.getenv("GEMINI_ROUTER_MODEL", "gemini-3.1-flash-lite")
    return os.getenv("OLLAMA_ROUTER_MODEL", os.getenv("PRIMARY_MODEL", "llama3.2:3b"))


def _safe_parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "ja"}:
            return True
        if normalized in {"false", "0", "no", "nein"}:
            return False
    return bool(value)


def _normalize_complexity_tier(value: Any) -> str:
    tier = str(value or "hard").strip().lower()
    if tier in {"easy", "medium", "hard"}:
        return tier
    return "hard"


def deterministic_block_reason(question: str) -> str:
    for pattern, label in DETERMINISTIC_BLOCK_PATTERNS:
        if pattern.search(question):
            return label
    return ""


def _template_candidates(
    *,
    question: str,
    memory_intent_key: str | None,
    intent: str | None,
) -> list[dict[str, Any]]:
    return find_similar_templates_for_router(
        question,
        memory_intent_key,
        intent,
        limit=3,
    )


def _fallback_state(reason: str, *, question: str = "") -> dict[str, Any]:
    return {
        "intent": "aggregation",
        "needs_sql": True,
        "needs_clarification": False,
        "blocked_or_unsafe": False,
        "output_mode": "table",
        "language": "de",
        "memory_intent_key": "aggregation",
        "complexity_tier": "hard",
        "complexity_reason": f"Fallback: {reason}",
        "constraints": {"time_window": None, "grouping_level": []},
        "execution_plan": ["retrieve_templates", "run_sql_agent", "run_reporting_agent"],
        "clarification_question": "",
        "template_candidates": _template_candidates(
            question=question,
            memory_intent_key="aggregation",
            intent="aggregation",
        ),
        "_router_raw_response": "",
    }


def _blocked_state(question: str, reason: str) -> dict[str, Any]:
    return {
        "intent": "blocked",
        "needs_sql": False,
        "needs_clarification": False,
        "blocked_or_unsafe": True,
        "output_mode": "technical_detail",
        "language": "de",
        "memory_intent_key": "blocked",
        "complexity_tier": "hard",
        "complexity_reason": f"Deterministic safety block: {reason}",
        "constraints": {"time_window": None, "grouping_level": []},
        "execution_plan": [],
        "clarification_question": "Diese Anfrage kann aus Sicherheitsgründen nicht verarbeitet werden.",
        "template_candidates": _template_candidates(
            question=question,
            memory_intent_key="blocked",
            intent="blocked",
        ),
        "_router_raw_response": "",
    }


def classify_intent(state: RouterState) -> dict[str, Any]:
    question     = state.get("user_question", "")
    llm_provider = state.get("llm_provider", get_provider())
    ollama_host  = state.get("ollama_host", "http://localhost:11434")

    block_reason = deterministic_block_reason(question)
    if block_reason:
        return _blocked_state(question, block_reason)

    try:
        excerpt      = load_router_excerpt()
        excerpt_text = _format_excerpt_for_prompt(excerpt)
    except Exception as e:
        return _fallback_state(f"Excerpt konnte nicht geladen werden: {e}", question=question)

    try:
        response = invoke_model(
            build_router_prompt(question, excerpt_text),
            model_name=_get_router_model(llm_provider),
            provider=llm_provider,
            ollama_host=ollama_host,
        )
        raw    = response.response_text
        parsed = _safe_parse_json(raw)

        tier = _normalize_complexity_tier(parsed.get("complexity_tier", "hard"))
        intent = parsed.get("intent", "aggregation")
        memory_intent_key = parsed.get("memory_intent_key", intent)

        return {
            "intent":                 intent,
            "needs_sql":              _as_bool(parsed.get("needs_sql"), True),
            "needs_clarification":    _as_bool(parsed.get("needs_clarification"), False),
            "blocked_or_unsafe":      _as_bool(parsed.get("blocked_or_unsafe"), False),
            "output_mode":            parsed.get("output_mode", "table"),
            "language":               parsed.get("language", "de"),
            "memory_intent_key":      memory_intent_key,
            "complexity_tier":        tier,
            "complexity_reason":      parsed.get("complexity_reason", ""),
            "constraints":            parsed.get("constraints", {"time_window": None, "grouping_level": []}),
            "execution_plan":         parsed.get("execution_plan", []),
            "clarification_question": parsed.get("clarification_question", ""),
            "template_candidates":    _template_candidates(
                question=question,
                memory_intent_key=memory_intent_key,
                intent=intent,
            ),
            "_router_raw_response":   raw,
        }
    except Exception as e:
        return _fallback_state(f"Parse-Fehler: {e}", question=question)


def clarification_gate(state: RouterState) -> dict[str, Any]:
    if state.get("blocked_or_unsafe"):
        return {
            "blocked_or_unsafe": True,
            "needs_sql": False,
            "clarification_question": "Diese Anfrage kann aus Sicherheitsgründen nicht verarbeitet werden.",
        }
    if state.get("needs_clarification"):
        fallback_q = "Könnten Sie Ihre Frage präzisieren? Welche Kennzahl, welcher Zeitraum und welche Gruppierungsebene interessiert Sie?"
        return {
            "needs_clarification": True,
            "needs_sql": False,
            "clarification_question": state.get("clarification_question") or fallback_q,
        }
    return {}


def route_after_gate(state: RouterState) -> Literal["router_end_clarification", "router_end_ok"]:
    if state.get("blocked_or_unsafe") or state.get("needs_clarification"):
        return "router_end_clarification"
    return "router_end_ok"


def router_end_clarification(state: RouterState) -> dict[str, Any]:
    return {}


def router_end_ok(state: RouterState) -> dict[str, Any]:
    return {}


def build_router_graph():
    graph = StateGraph(RouterState)
    graph.add_node("classify_intent",         classify_intent)
    graph.add_node("clarification_gate",       clarification_gate)
    graph.add_node("router_end_clarification", router_end_clarification)
    graph.add_node("router_end_ok",            router_end_ok)
    graph.add_edge(START, "classify_intent")
    graph.add_edge("classify_intent", "clarification_gate")
    graph.add_conditional_edges("clarification_gate", route_after_gate)
    graph.add_edge("router_end_clarification", END)
    graph.add_edge("router_end_ok",            END)
    return graph.compile()
