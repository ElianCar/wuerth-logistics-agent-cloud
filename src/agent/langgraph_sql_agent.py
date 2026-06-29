from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from time import perf_counter
from typing import Any, Callable, Literal, Optional, TypedDict

import yaml

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from src.agent.db import execute_read_only_sql, load_schema_context
from src.agent.id_utils import generate_run_id
from src.agent.logging_utils import infer_error_type, log_query_attempt, log_query_run
from src.agent.memory_retriever import load_approved_solution_templates
from src.agent.memory_template_schema import is_retrievable_template, load_and_validate_template
from src.agent.sql_validator import validate_generated_sql
from src.config.scenarios import PROJECT_ROOT, SCENARIOS, get_active_scenario, normalize_scenario_id
from src.llm.model_adapter import (
    DEFAULT_ANTHROPIC_FALLBACK_MODEL,
    DEFAULT_ANTHROPIC_HARD_MODEL,
    DEFAULT_ANTHROPIC_MEDIUM_MODEL,
    DEFAULT_GEMINI_BACKUP_MODEL,
    DEFAULT_GEMINI_PRIMARY_MODEL,
    DEFAULT_OLLAMA_BACKUP_MODEL,
    DEFAULT_OLLAMA_MODEL,
    get_provider,
    invoke_model,
)


load_dotenv()


class SQLAgentState(TypedDict, total=False):
    run_id: str
    user_question: str
    question: str
    selected_model: str
    model_used: str
    attempt_number: int
    max_primary_attempts: int
    fallback_used: bool
    fallback_model: str
    secondary_fallback_model: str
    schema_context: str
    generated_sql: str
    sql_valid: bool
    sql_error: str
    query_result: dict[str, Any]
    final_answer: str
    answer: str
    final_sql: str
    model_primary: str
    validation_success: bool
    error_type: str
    error_message: str
    row_count: int
    latency_seconds: float
    trace_steps: list[str]
    primary_model: str
    llm_provider: str
    ollama_host: str
    previous_failed_sql: str
    previous_final_answer: str
    user_correction: str
    execution_success: bool
    source_tables: list[str]
    total_attempts: int
    result_status: str
    schema_load_failed: bool
    run_context: str
    use_approved_memory: bool
    use_legacy_memory: bool
    enable_memory_candidate_generation: bool
    log_to_query_log: bool
    language: str
    router_context: dict[str, Any]
    memory_retrieval: dict[str, Any]
    chat_context: str


@dataclass(frozen=True)
class SQLAgentConfig:
    primary_model: str
    fallback_model: str
    max_primary_attempts: int
    llm_provider: str
    ollama_host: str
    secondary_fallback_model: str = ""

    @classmethod
    def from_env(cls) -> "SQLAgentConfig":
        return cls.from_provider(get_provider())

    @classmethod
    def from_provider(cls, llm_provider: str) -> "SQLAgentConfig":
        llm_provider = get_provider(llm_provider)
        if llm_provider == "anthropic":
            primary_model = os.getenv("ANTHROPIC_PRIMARY_MODEL", DEFAULT_ANTHROPIC_MEDIUM_MODEL)
            fallback_model = os.getenv("ANTHROPIC_FALLBACK_MODEL", DEFAULT_ANTHROPIC_FALLBACK_MODEL)
            secondary_fallback_model = os.getenv(
                "ANTHROPIC_SECONDARY_FALLBACK_MODEL",
                os.getenv("ANTHROPIC_HARD_MODEL", DEFAULT_ANTHROPIC_HARD_MODEL),
            )
            max_primary_attempts = int(os.getenv("MAX_PRIMARY_ATTEMPTS", "1"))
        elif llm_provider == "gemini":
            primary_model = os.getenv("GEMINI_PRIMARY_MODEL", DEFAULT_GEMINI_PRIMARY_MODEL)
            fallback_model = os.getenv("GEMINI_BACKUP_MODEL", DEFAULT_GEMINI_BACKUP_MODEL)
            secondary_fallback_model = ""
            max_primary_attempts = int(os.getenv("MAX_PRIMARY_ATTEMPTS", "2"))
        elif llm_provider == "ollama":
            primary_model = os.getenv("PRIMARY_MODEL") or os.getenv("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
            fallback_model = os.getenv("FALLBACK_MODEL", DEFAULT_OLLAMA_BACKUP_MODEL)
            secondary_fallback_model = ""
            max_primary_attempts = int(os.getenv("MAX_PRIMARY_ATTEMPTS", "2"))
        else:
            raise ValueError(f"Unsupported LLM provider '{llm_provider}'. Use 'anthropic', 'gemini', or 'ollama'.")

        return cls(
            primary_model=primary_model,
            fallback_model=fallback_model,
            max_primary_attempts=max_primary_attempts,
            llm_provider=llm_provider,
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            secondary_fallback_model=secondary_fallback_model,
        )


SchemaLoader = Callable[[], str]
SQLGenerator = Callable[[str, str, str, str], str]
SQLExecutor = Callable[[str, str], dict[str, Any]]
AttemptLogger = Callable[..., None]
StepCallback = Callable[[str, float, "dict[str, Any]"], None]


def noop_attempt_logger(**_kwargs: Any) -> None:
    return None


def append_trace(state: SQLAgentState, message: str) -> list[str]:
    return [*state.get("trace_steps", []), message]


def _path_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _resolve_memory_template_path(
    candidate_path: str,
    *,
    scenario_id: str,
    memory_dir: Path | None = None,
) -> Path | None:
    if not candidate_path:
        return None

    scenario_memory_dir = memory_dir or SCENARIOS[scenario_id].memory_dir
    approved_dir = scenario_memory_dir / "approved"
    raw_path = Path(candidate_path)
    candidates = [raw_path] if raw_path.is_absolute() else [
        PROJECT_ROOT / raw_path,
        scenario_memory_dir.parent / raw_path,
        scenario_memory_dir / raw_path,
    ]
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_file() and _path_inside(resolved, approved_dir):
            return resolved
    return None


def _safe_source_sql(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    sql = value.strip().rstrip(";").strip()
    if not sql or len(sql) > 2000:
        return ""
    if "```" in sql or "--" in sql or "/*" in sql or "*/" in sql:
        return ""
    if not re.match(r"^\s*(select|with)\b", sql, re.IGNORECASE):
        return ""
    forbidden = r"\b(drop|delete|update|insert|alter|truncate|copy|create|merge|grant|revoke)\b"
    if re.search(forbidden, sql, re.IGNORECASE):
        return ""
    if re.search(r";\s*\S+", sql):
        return ""
    return sql


def _format_prompt_list(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return "- none"
    return "\n".join(f"- {str(value)}" for value in values if str(value).strip()) or "- none"


def _load_guidance_template(
    candidate: dict[str, Any],
    *,
    scenario_id: str,
    memory_dir: Path | None = None,
) -> dict[str, Any] | None:
    path = _resolve_memory_template_path(
        str(candidate.get("path", "")),
        scenario_id=scenario_id,
        memory_dir=memory_dir,
    )
    if path is None:
        return None

    validation = load_and_validate_template(path, expected_scenario=scenario_id)
    if not validation.is_valid:
        return None
    template = validation.template
    if not is_retrievable_template(template, expected_scenario=scenario_id):
        return None
    candidate_id = str(candidate.get("template_id", "")).strip()
    if candidate_id and candidate_id != template.get("id"):
        return None
    return template


def format_memory_guidance_from_retrieval(
    memory_retrieval: dict[str, Any] | None,
    *,
    memory_dir: Path | None = None,
    max_templates: int = 3,
) -> str:
    """Format router-provided approved memory retrieval as SQL prompt guidance."""

    if not isinstance(memory_retrieval, dict):
        return ""
    candidates = memory_retrieval.get("candidates", [])
    if not isinstance(candidates, list) or not candidates:
        return ""

    try:
        scenario_id = normalize_scenario_id(str(memory_retrieval.get("scenario", "")))
    except Exception:
        return ""
    if scenario_id != get_active_scenario().scenario_id:
        return ""

    formatted_templates = []
    for candidate in candidates:
        if len(formatted_templates) >= max_templates:
            break
        if not isinstance(candidate, dict):
            continue
        template = _load_guidance_template(
            candidate,
            scenario_id=scenario_id,
            memory_dir=memory_dir,
        )
        if template is None:
            continue

        source_sql = _safe_source_sql(template.get("source_sql", ""))
        source_sql_block = f"\nsource_sql:\n{source_sql}" if source_sql else ""
        matched_terms = candidate.get("matched_terms", [])
        matched_terms_text = ", ".join(str(term) for term in matched_terms) if isinstance(matched_terms, list) else ""
        formatted_templates.append(
            f"""Template {len(formatted_templates) + 1}
template_id: {template.get("id", "")}
title: {template.get("title", "")}
intent: {template.get("intent", "")}
matched_terms: {matched_terms_text}
business_rules:
{_format_prompt_list(template.get("business_rules", []))}
sql_pattern:
{template.get("sql_pattern", "")}
do_not_use_when:
{_format_prompt_list(template.get("do_not_use_when", []))}
validation_checks:
{_format_prompt_list(template.get("validation_checks", []))}
source_question: {template.get("source_question", "")}{source_sql_block}
"""
        )

    if not formatted_templates:
        return ""

    ambiguity_warning = ""
    if bool(memory_retrieval.get("ambiguous", False)):
        ambiguity_warning = (
            "\nAmbiguity warning: multiple approved templates are close matches. "
            "Do not overfit to one template.\n"
        )

    return (
        "\nApproved memory template guidance (context only):\n"
        "- Approved memory templates are guidance only.\n"
        "- Final SQL must answer the current user question.\n"
        "- Explicit user constraints override templates.\n"
        "- Respect do_not_use_when conditions.\n"
        "- Final SQL must use only known schema tables and columns.\n"
        "- Final SQL must still pass SQL validation.\n"
        "- Do not copy source_sql blindly if it does not match the current question.\n"
        f"{ambiguity_warning}\n"
        + "\n".join(formatted_templates)
    )


def format_approved_template_context(question: str) -> str:
    try:
        templates = load_approved_solution_templates(question, max_templates=3)
    except Exception:
        templates = []

    if not templates:
        return ""

    formatted_templates = []
    for index, template in enumerate(templates, start=1):
        metric_definitions = yaml.safe_dump(
            template.get("metric_definitions", {}),
            sort_keys=False,
        ).strip()
        join_logic = yaml.safe_dump(template.get("join_logic", []), sort_keys=False).strip()
        required_tables = ", ".join(str(table) for table in template.get("required_tables", []))
        formatted_templates.append(
            f"""Template {index}
Intent: {template.get("intent", "")}
Required tables: {required_tables}
Metric definitions:
{metric_definitions or "{}"}
Join logic:
{join_logic or "[]"}
SQL skeleton:
{template.get("sql_skeleton", "")}
"""
        )

    return """
Approved reusable solution templates:
The following templates are approved and active. Use them only as guidance.
They are not mandatory. The final SQL must match the current user question,
must use only relevant templates, and must still pass validation.

""" + "\n".join(formatted_templates)


def extract_context_value(schema_context: str, key: str, default: str) -> str:
    prefix = f"{key}:"
    for raw_line in schema_context.splitlines():
        line = raw_line.strip()
        if line.lower().startswith(prefix.lower()):
            value = line[len(prefix):].strip()
            return value or default
    return default


def build_scenario_sql_rules() -> str:
    scenario = get_active_scenario()
    if scenario.scenario_id == "wuerth_local":
        allowed_tables = "\n".join(f"- {table}" for table in scenario.allowed_tables)
        return f"""Würth local PostgreSQL scenario rules:
- Generate PostgreSQL SQL only.
- Use only these local Würth PostgreSQL tables:
{allowed_tables}
- Use explicit joins with aliases i for invoices and s for shipments.
- Do not use TPC-H demo tables, Databricks catalog names, or TRY_CAST; numeric columns are already typed in PostgreSQL.
- Revenue / Umsatz = SUM(i.turnover_inv) from wuerth.invoices (EUR). No cast needed.
- Freight cost = SUM(s.freight_costs); packing cost = SUM(s.packing_costs). Both are NUMERIC — sum directly. Invoice-side freight_cost_inv is unpopulated; never use it.
- Use calendar_day for invoice-side date filtering (end date inclusive: calendar_day <= 'YYYY-MM-DD') and calendar_yearmonth (YYYYMM) for monthly grouping.
- Use shipment_date for shipment-side date filtering (end date inclusive: shipment_date <= 'YYYY-MM-DD').
- Produkt / Artikel / Produktnummer / Material = invoices.product and shipments.customer_material. material_price is a second product number field (Produktnummer/Artikelnummer) — different column from product; do not aggregate it.
- Vertriebszentrum / Lager (distribution center) = shipments.plant. Versandstelle = shipments.shipping_point (one organizational level BELOW plant); use shipping_point only when the user explicitly asks for Versandstelle.
- sales_area (invoices) is NOT the Vertriebszentrum; do not use it for Vertriebszentrum grouping.
- All delivery/shipment information comes exclusively from shipments — do not use invoices for delivery-related filtering.
- Lieferpositionen = COUNT(*) on shipments rows (each row = one Lieferposition). Anzahl Lieferungen (distinct deliveries) = COUNT(DISTINCT s.delivery_number).
- Do not use price_key_quantity, sorting_system, market_segment, or order_item (uninterpreted/irrelevant columns).
- CROSS-TABLE LINKAGE — the method depends on what is measured:
  - Pure shipment measures (Lieferpositionen, Lieferungen, freight/packing cost, delivered quantity) by plant/shipping_point/delivery_type: query shipments directly with GROUP BY that dimension. Do NOT join invoices.
  - Pure invoice measures with no shipment dimension (revenue by product, revenue by month): query invoices directly. Do NOT join shipments.
  - Invoice measure (revenue/Umsatz, ordered quantity) filtered or grouped by a SHIPMENT dimension (plant, shipping_point, delivery_type): link via order_number only. Do NOT join on product = customer_material — the two columns have different string formats and the equality matches almost nothing (revenue would collapse to 0).
- For revenue filtered by a single plant value: SELECT SUM(i.turnover_inv) FROM wuerth.invoices i WHERE <date filter> AND i.order_number IN (SELECT order_number FROM wuerth.shipments WHERE plant = '<value>').
- For revenue grouped by plant: SELECT s.plant, SUM(i.turnover_inv) AS revenue FROM wuerth.invoices i JOIN (SELECT DISTINCT order_number, plant FROM wuerth.shipments) s ON i.order_number = s.order_number GROUP BY s.plant.
- Multi-plant caveat: an order can ship from several plants, so its full invoice revenue is attributed to each involved plant; the sum across plants can exceed total revenue. This is acceptable; do not attempt to split it.
- The full 3-key join (order_number, customer = shiptoparty, product = customer_material) is only for row-level matching questions and under-matches badly; do not use it to link invoice measures to a shipment dimension.
- Use LEFT JOIN or anti join patterns when the user asks for unmatched invoice or shipment records.
"""

    if scenario.scenario_id == "databricks":
        allowed_tables = "\n".join(f"- {table}" for table in scenario.allowed_tables)
        return f"""Databricks scenario rules:
- Generate Databricks SQL only.
- Use fully qualified table names.
- Use only these Würth tables:
{allowed_tables}
- Use explicit joins with aliases i for invoices and s for shipments.
- freight_costs and packing_costs (shipments) are text columns: use SUM(TRY_CAST(freight_costs AS DOUBLE)) and SUM(TRY_CAST(packing_costs AS DOUBLE)).
- Revenue / Umsatz = SUM(i.turnover_inv) from invoices (EUR). Invoice-side freight_cost_inv is unpopulated; never use it.
- Use calendar_day for invoice-side date filtering (end date inclusive: calendar_day <= 'YYYY-MM-DD') and calendar_yearmonth (YYYYMM) for monthly grouping.
- Use shipment_date for shipment-side date filtering (end date inclusive: shipment_date <= 'YYYY-MM-DD').
- Produkt / Artikel / Produktnummer / Material = invoices.product and shipments.customer_material. material_price is a second product number field (Produktnummer/Artikelnummer) — different column from product; do not aggregate it.
- Vertriebszentrum / Lager (distribution center) = shipments.plant. Versandstelle = shipments.shipping_point (one organizational level BELOW plant); use shipping_point only when the user explicitly asks for Versandstelle.
- sales_area (invoices) is NOT the Vertriebszentrum; do not use it for Vertriebszentrum grouping.
- All delivery/shipment information comes exclusively from shipments — do not use invoices for delivery-related filtering.
- Lieferpositionen = COUNT(*) on shipments rows (each row = one Lieferposition). Anzahl Lieferungen (distinct deliveries) = COUNT(DISTINCT s.delivery_number).
- Do not use price_key_quantity, sorting_system, market_segment, or order_item (uninterpreted/irrelevant columns).
- Do not use TPC-H tables or PostgreSQL-specific syntax.
- Do not use information_schema for business questions.
- CROSS-TABLE LINKAGE — the method depends on what is measured:
  - Pure shipment measures (Lieferpositionen, Lieferungen, freight/packing cost, delivered quantity) by plant/shipping_point/delivery_type: query shipments directly with GROUP BY that dimension. Do NOT join invoices.
  - Pure invoice measures with no shipment dimension (revenue by product, revenue by month): query invoices directly. Do NOT join shipments.
  - Invoice measure (revenue/Umsatz, ordered quantity) filtered or grouped by a SHIPMENT dimension (plant, shipping_point, delivery_type): link via order_number only. Do NOT join on product = customer_material — the two columns have different string formats and the equality matches almost nothing (revenue would collapse to 0).
- For revenue filtered by a single plant value: SELECT SUM(i.turnover_inv) FROM <invoices> i WHERE <date filter> AND i.order_number IN (SELECT order_number FROM <shipments> WHERE plant = '<value>').
- For revenue grouped by plant: SELECT s.plant, SUM(i.turnover_inv) AS revenue FROM <invoices> i JOIN (SELECT DISTINCT order_number, plant FROM <shipments>) s ON i.order_number = s.order_number GROUP BY s.plant.
- Multi-plant caveat: an order can ship from several plants, so its full invoice revenue is attributed to each involved plant; the sum across plants can exceed total revenue. This is acceptable; do not attempt to split it.
- The full 3-key join (order_number, customer = shiptoparty, product = customer_material) is only for row-level matching questions and under-matches badly; do not use it to link invoice measures to a shipment dimension.
- For direct delivery count: COUNT(DISTINCT CASE WHEN flag_direct_delivery = 'X' THEN delivery_number END).
- For direct delivery share: COUNT(DISTINCT CASE WHEN flag_direct_delivery = 'X' THEN delivery_number END) * 1.0 / COUNT(DISTINCT delivery_number).
- Use LEFT JOIN or anti join patterns when the user asks for unmatched invoice or shipment records.
- Do not invent business-table SQL for S24 compliance, on-time delivery rate, delivery delay, or gross profit/Rohertrag. For these unsupported KPIs, return: SELECT 'The requested KPI is unsupported because the required columns or business rules are not available.' AS limitation
"""

    return """Demo data scenario rules:
- Preserve the existing PostgreSQL demo SQL behavior.
- Use only the demo TPC-H tables exposed in the schema context.
- For revenue, use SUM(l_extendedprice * (1 - l_discount)) unless otherwise stated.
- Do not use Würth Databricks table names in demo mode.
"""


def build_sql_prompt(state: SQLAgentState) -> str:
    repair_context = ""
    correction_context = ""
    previous_failed_sql = state.get("previous_failed_sql") or state.get("generated_sql", "")
    previous_final_answer = state.get("previous_final_answer", "")
    user_correction = state.get("user_correction", "")
    sql_error = state.get("sql_error", "")

    if previous_failed_sql or sql_error:
        repair_context = f"""
Previous failed SQL:
{previous_failed_sql or "(none)"}

Previous SQL error:
{sql_error or "(none)"}

Produce corrected SQL only.
"""

    if user_correction or previous_final_answer:
        correction_context = f"""
The user said the previous answer did not match their intent.
Use the correction below to reinterpret the original question.

Previous answer:
{previous_final_answer or "(none)"}

User correction:
{user_correction or "(none)"}
"""

    approved_template_context = ""
    if bool(state.get("use_approved_memory", True)):
        router_context = state.get("router_context", {})
        has_router_memory = "memory_retrieval" in state or (
            isinstance(router_context, dict) and "memory_retrieval" in router_context
        )
        if has_router_memory:
            memory_retrieval = state.get("memory_retrieval")
            if memory_retrieval is None and isinstance(router_context, dict):
                memory_retrieval = router_context.get("memory_retrieval", {})
            approved_template_context = format_memory_guidance_from_retrieval(memory_retrieval)
        elif bool(state.get("use_legacy_memory", False)):
            approved_template_context = format_approved_template_context(state["user_question"])

    raw_chat_context = state.get("chat_context", "")
    chat_context_block = f"{raw_chat_context}\n\n" if raw_chat_context else ""

    schema_context = state.get("schema_context", "")
    sql_dialect = extract_context_value(schema_context, "SQL dialect", "PostgreSQL")
    backend_name = extract_context_value(schema_context, "Backend", "postgres")
    scenario_rules = build_scenario_sql_rules()

    return f"""You are a {sql_dialect} SQL generator.

Return SQL only.
Do not include markdown code fences.
Do not include explanations, comments, or prose.
Generate exactly one read-only SELECT query. A WITH common table expression is allowed only if the final statement is a SELECT.
Do not use DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, COPY, CREATE, MERGE, GRANT, or REVOKE.
Use only the provided tables and columns.
Prefer explicit JOIN syntax.
Add LIMIT 50 for broad row-level queries that are not aggregations.
Active backend: {backend_name}
SQL dialect: {sql_dialect}

{scenario_rules}

Database and semantic context:
{schema_context}
{approved_template_context}
{repair_context}
{correction_context}
{chat_context_block}User question:
{state["user_question"]}
"""


def default_sql_generator(
    prompt: str,
    model: str,
    ollama_host: str,
    _node_name: str,
    *,
    llm_provider: str | None = None,
) -> str:
    return invoke_model(
        prompt,
        model_name=model,
        provider=llm_provider,
        ollama_host=ollama_host,
    ).response_text


def log_attempt_state(
    state: SQLAgentState,
    *,
    execution_success: bool,
    row_count: int,
    attempt_logger: AttemptLogger,
) -> None:
    attempt_logger(
        run_id=state.get("run_id", ""),
        user_question=state.get("user_question", ""),
        primary_model=state.get("primary_model", ""),
        backup_model=state.get("fallback_model", ""),
        model_used=state.get("selected_model", ""),
        selected_model=state.get("selected_model", ""),
        attempt_number=int(state.get("attempt_number", 0)),
        fallback_used=bool(state.get("fallback_used", False)),
        sql_candidate=state.get("generated_sql", ""),
        generated_sql=state.get("generated_sql", ""),
        sql_valid=bool(state.get("sql_valid", False)),
        error_message=state.get("sql_error", ""),
        sql_error=state.get("sql_error", ""),
        success=execution_success,
        execution_success=execution_success,
        row_count=row_count,
        source_tables=state.get("source_tables", []),
    )


def derive_error_type(state: SQLAgentState) -> str:
    error_message = state.get("sql_error", "")
    if not error_message:
        return ""
    if state.get("schema_load_failed"):
        return "schema_load_error"
    if not state.get("generated_sql"):
        return "generation_error"
    return infer_error_type(
        validation_success=bool(state.get("sql_valid", False)),
        execution_success=bool(state.get("execution_success", False)),
        error_message=error_message,
    )


def build_sql_agent_graph(
    *,
    schema_loader: SchemaLoader = load_schema_context,
    sql_generator: SQLGenerator = default_sql_generator,
    sql_executor: SQLExecutor = execute_read_only_sql,
    attempt_logger: AttemptLogger = log_query_attempt,
    step_callback: StepCallback | None = None,
):
    def _notify_end(node_name: str, start_time: float, metadata: dict[str, Any] | None = None) -> None:
        if step_callback is not None:
            try:
                step_callback(node_name, perf_counter() - start_time, metadata or {})
            except Exception:
                pass

    def load_schema(state: SQLAgentState) -> dict[str, Any]:
        _start = perf_counter()
        try:
            schema_context = schema_loader()
        except Exception as error:
            _notify_end("load_schema", _start)
            return {
                "schema_load_failed": True,
                "sql_error": str(error),
                "final_answer": f"Das Datenbankschema konnte nicht geladen werden: {error}",
                "trace_steps": append_trace(state, "Schema laden fehlgeschlagen"),
            }

        _notify_end("load_schema", _start)
        return {
            "schema_context": schema_context,
            "schema_load_failed": False,
            "trace_steps": append_trace(state, "Schema und Semantic Layer geladen"),
        }

    def generate_sql(state: SQLAgentState) -> dict[str, Any]:
        _start = perf_counter()
        attempt_number = int(state.get("attempt_number", 0)) + 1
        total_attempts = int(state.get("total_attempts", 0)) + 1
        working_state: SQLAgentState = {
            **state,
            "attempt_number": attempt_number,
            "total_attempts": total_attempts,
        }
        prompt = build_sql_prompt(working_state)
        selected_model = working_state["selected_model"]

        try:
            ollama_host = working_state.get("ollama_host", "http://localhost:11434")
            if sql_generator is default_sql_generator:
                generated_sql = default_sql_generator(
                    prompt,
                    selected_model,
                    ollama_host,
                    "generate_sql",
                    llm_provider=working_state.get("llm_provider", ""),
                )
            else:
                generated_sql = sql_generator(
                    prompt,
                    selected_model,
                    ollama_host,
                    "generate_sql",
                )
            sql_error = ""
            trace_message = f"SQL-Generierung Versuch {attempt_number} mit {selected_model}"
        except Exception as error:
            generated_sql = ""
            sql_error = str(error)
            trace_message = f"SQL-Generierung in Versuch {attempt_number} mit {selected_model} fehlgeschlagen"

        _notify_end("generate_sql", _start)
        return {
            "attempt_number": attempt_number,
            "total_attempts": total_attempts,
            "generated_sql": generated_sql,
            "sql_valid": False,
            "sql_error": sql_error,
            "execution_success": False,
            "query_result": {},
            "trace_steps": append_trace(state, trace_message),
        }

    def validate_sql(state: SQLAgentState) -> dict[str, Any]:
        _start = perf_counter()
        if state.get("sql_error") and not state.get("generated_sql"):
            update: dict[str, Any] = {
                "sql_valid": False,
                "source_tables": [],
                "trace_steps": append_trace(
                    state,
                    f"SQL-Validierung übersprungen, weil die Generierung fehlgeschlagen ist: {state.get('sql_error', '')}",
                ),
            }
            state_for_log: SQLAgentState = {**state, **update}
            log_attempt_state(
                state_for_log,
                execution_success=False,
                row_count=0,
                attempt_logger=attempt_logger,
            )
            _notify_end("validate_sql", _start)
            return update

        validation = validate_generated_sql(
            state.get("generated_sql", ""),
            state.get("schema_context", ""),
        )
        update: dict[str, Any] = {
            "generated_sql": validation.sql,
            "sql_valid": validation.is_valid,
            "sql_error": validation.error,
            "source_tables": validation.used_tables,
            "trace_steps": append_trace(
                state,
                "SQL-Validierung erfolgreich" if validation.is_valid else f"SQL-Validierung fehlgeschlagen: {validation.error}",
            ),
        }

        state_for_log: SQLAgentState = {**state, **update}
        if not validation.is_valid:
            log_attempt_state(
                state_for_log,
                execution_success=False,
                row_count=0,
                attempt_logger=attempt_logger,
            )

        _notify_end("validate_sql", _start)
        return update

    def execute_sql(state: SQLAgentState) -> dict[str, Any]:
        _start = perf_counter()
        try:
            query_result = sql_executor(
                state.get("generated_sql", ""),
                state.get("user_question", ""),
            )
            row_count = int(query_result.get("row_count", 0))
            update = {
                "query_result": query_result,
                "execution_success": True,
                "sql_error": "",
                "trace_steps": append_trace(state, f"SQL-Ausführung erfolgreich mit {row_count} Zeilen"),
            }
            state_for_log: SQLAgentState = {**state, **update}
            log_attempt_state(
                state_for_log,
                execution_success=True,
                row_count=row_count,
                attempt_logger=attempt_logger,
            )
            _notify_end("execute_sql", _start)
            return update
        except Exception as error:
            update = {
                "query_result": {},
                "execution_success": False,
                "sql_error": str(error),
                "trace_steps": append_trace(state, f"SQL-Ausführung fehlgeschlagen: {error}"),
            }
            state_for_log: SQLAgentState = {**state, **update}
            log_attempt_state(
                state_for_log,
                execution_success=False,
                row_count=0,
                attempt_logger=attempt_logger,
            )
            _notify_end("execute_sql", _start)
            return update

    def repair_sql(state: SQLAgentState) -> dict[str, Any]:
        _start = perf_counter()
        result = {
            "previous_failed_sql": state.get("generated_sql", ""),
            "trace_steps": append_trace(state, "SQL-Reparatur hat fehlgeschlagenes SQL und Fehler für einen weiteren Versuch vorbereitet"),
        }
        _notify_end("repair_sql", _start)
        return result

    def switch_model(state: SQLAgentState) -> dict[str, Any]:
        _start = perf_counter()
        fallback_model = next_fallback_model(state)
        result = {
            "selected_model": fallback_model,
            "attempt_number": 0,
            "fallback_used": True,
            "previous_failed_sql": state.get("generated_sql", ""),
            "trace_steps": append_trace(state, f"Modellwechsel auf {fallback_model}"),
        }
        _notify_end("switch_model", _start)
        return result

    def generate_final_answer(state: SQLAgentState) -> dict[str, Any]:
        _start = perf_counter()
        language = str(state.get("language", "de")).lower()

        if state.get("schema_load_failed"):
            result = {
                "final_answer": state.get(
                    "final_answer",
                    "The database schema could not be loaded."
                    if language == "en"
                    else "Das Datenbankschema konnte nicht geladen werden.",
                ),
                "result_status": "fehlgeschlagen",
                "trace_steps": append_trace(state, "Finale Antwort meldet Fehler beim Laden des Schemas"),
            }
            _notify_end("generate_final_answer", _start)
            return result

        if not state.get("execution_success"):
            if language == "en":
                final_answer = (
                    "I could not create a valid executable SQL query. "
                    f"Last error: {state.get('sql_error', 'unknown error')}"
                )
            else:
                final_answer = (
                    "Ich konnte keine gültige ausführbare SQL-Abfrage erzeugen. "
                    f"Letzter Fehler: {state.get('sql_error', 'unbekannter Fehler')}"
                )
            result = {
                "final_answer": final_answer,
                "result_status": "fehlgeschlagen",
                "trace_steps": append_trace(state, "Finale Antwort meldet SQL-Fehler"),
            }
            _notify_end("generate_final_answer", _start)
            return result

        query_result = state.get("query_result", {})
        columns = query_result.get("columns", [])
        rows = query_result.get("rows", [])
        row_count = int(query_result.get("row_count", 0))

        if language == "en" and row_count == 0:
            final_answer = "The query returned no rows."
        elif language == "en" and row_count == 1 and len(columns) == 1:
            final_answer = f"The answer is {rows[0][0]}."
        elif language == "en":
            final_answer = f"The query returned {row_count} rows."
        elif row_count == 0:
            final_answer = "Die Abfrage lieferte keine Zeilen."
        elif row_count == 1 and len(columns) == 1:
            final_answer = f"Die Antwort ist {rows[0][0]}."
        else:
            final_answer = f"Die Abfrage lieferte {row_count} Zeilen."

        if state.get("fallback_used"):
            result_status = "mit Fallback erfolgreich"
        elif int(state.get("total_attempts", 0)) == 1:
            result_status = "im ersten Versuch erfolgreich"
        else:
            result_status = "nach Reparatur erfolgreich"

        result = {
            "final_answer": final_answer,
            "result_status": result_status,
            "trace_steps": append_trace(state, f"Finale Antwort erzeugt: {result_status}"),
        }
        _notify_end("generate_final_answer", _start)
        return result

    def route_after_load_schema(state: SQLAgentState) -> Literal["generate_sql", "generate_final_answer"]:
        if state.get("schema_load_failed"):
            return "generate_final_answer"
        return "generate_sql"

    def can_retry_primary(state: SQLAgentState) -> bool:
        return (
            state.get("selected_model") == state.get("primary_model")
            and int(state.get("attempt_number", 0)) < int(state.get("max_primary_attempts", 2))
        )

    def next_fallback_model(state: SQLAgentState) -> str:
        selected_model = str(state.get("selected_model", ""))
        primary_model = str(state.get("primary_model", ""))
        fallback_chain = [
            str(state.get("fallback_model", "") or ""),
            str(state.get("secondary_fallback_model", "") or ""),
        ]
        if selected_model == primary_model:
            for fallback_model in fallback_chain:
                if fallback_model and fallback_model != selected_model:
                    return fallback_model
            return ""

        for index, fallback_model in enumerate(fallback_chain):
            if selected_model != fallback_model:
                continue
            for next_model in fallback_chain[index + 1 :]:
                if next_model and next_model != selected_model:
                    return next_model
            return ""
        return ""

    def can_switch_to_fallback(state: SQLAgentState) -> bool:
        return bool(next_fallback_model(state))

    def route_after_validate_sql(
        state: SQLAgentState,
    ) -> Literal["execute_sql", "repair_sql", "switch_model", "generate_final_answer"]:
        if state.get("sql_valid"):
            return "execute_sql"
        if can_retry_primary(state):
            return "repair_sql"
        if can_switch_to_fallback(state):
            return "switch_model"
        return "generate_final_answer"

    def route_after_execute_sql(
        state: SQLAgentState,
    ) -> Literal["generate_final_answer", "repair_sql", "switch_model"]:
        if state.get("execution_success"):
            return "generate_final_answer"
        if can_retry_primary(state):
            return "repair_sql"
        if can_switch_to_fallback(state):
            return "switch_model"
        return "generate_final_answer"

    graph = StateGraph(SQLAgentState)
    graph.add_node("load_schema", load_schema)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("repair_sql", repair_sql)
    graph.add_node("switch_model", switch_model)
    graph.add_node("generate_final_answer", generate_final_answer)

    graph.add_edge(START, "load_schema")
    graph.add_conditional_edges("load_schema", route_after_load_schema)
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_conditional_edges("validate_sql", route_after_validate_sql)
    graph.add_edge("repair_sql", "generate_sql")
    graph.add_edge("switch_model", "generate_sql")
    graph.add_conditional_edges("execute_sql", route_after_execute_sql)
    graph.add_edge("generate_final_answer", END)

    return graph.compile()


def run_sql_agent(
    user_question: str,
    *,
    run_id: str | None = None,
    config: SQLAgentConfig | None = None,
    force_fallback: bool = False,
    previous_failed_sql: str = "",
    previous_sql_error: str = "",
    previous_final_answer: str = "",
    user_correction: str = "",
    run_context: str = "chat",
    use_approved_memory: bool = True,
    use_legacy_memory: bool = False,
    enable_memory_candidate_generation: bool = True,
    log_to_query_log: bool = True,
    language: str = "",
    router_context: dict[str, Any] | None = None,
    memory_retrieval: dict[str, Any] | None = None,
    chat_context: str = "",
    schema_loader: SchemaLoader = load_schema_context,
    sql_generator: SQLGenerator = default_sql_generator,
    sql_executor: SQLExecutor = execute_read_only_sql,
    attempt_logger: AttemptLogger = log_query_attempt,
    step_callback: StepCallback | None = None,
) -> SQLAgentState:
    agent_config = config or SQLAgentConfig.from_env()
    selected_model = agent_config.fallback_model if force_fallback else agent_config.primary_model
    run_id = run_id or generate_run_id()
    started_at = perf_counter()
    effective_attempt_logger = attempt_logger if log_to_query_log else noop_attempt_logger
    graph = build_sql_agent_graph(
        schema_loader=schema_loader,
        sql_generator=sql_generator,
        sql_executor=sql_executor,
        attempt_logger=effective_attempt_logger,
        step_callback=step_callback,
    )
    initial_state: SQLAgentState = {
        "run_id": run_id,
        "user_question": user_question,
        "question": user_question,
        "selected_model": selected_model,
        "model_used": selected_model,
        "attempt_number": 0,
        "max_primary_attempts": agent_config.max_primary_attempts,
        "fallback_used": force_fallback,
        "schema_context": "",
        "generated_sql": "",
        "sql_valid": False,
        "sql_error": previous_sql_error,
        "query_result": {},
        "final_answer": "",
        "answer": "",
        "final_sql": "",
        "model_primary": agent_config.primary_model,
        "validation_success": False,
        "error_type": "",
        "error_message": previous_sql_error,
        "row_count": 0,
        "latency_seconds": 0.0,
        "trace_steps": [],
        "primary_model": agent_config.primary_model,
        "fallback_model": agent_config.fallback_model,
        "secondary_fallback_model": agent_config.secondary_fallback_model,
        "llm_provider": agent_config.llm_provider,
        "ollama_host": agent_config.ollama_host,
        "previous_failed_sql": previous_failed_sql,
        "previous_final_answer": previous_final_answer,
        "user_correction": user_correction,
        "execution_success": False,
        "source_tables": [],
        "total_attempts": 0,
        "result_status": "",
        "schema_load_failed": False,
        "run_context": run_context,
        "use_approved_memory": use_approved_memory,
        "use_legacy_memory": use_legacy_memory,
        "enable_memory_candidate_generation": enable_memory_candidate_generation,
        "log_to_query_log": log_to_query_log,
        "language": language,
        "router_context": router_context or {},
        "chat_context": chat_context,
    }
    if memory_retrieval is not None:
        initial_state["memory_retrieval"] = memory_retrieval

    final_state: SQLAgentState = graph.invoke(initial_state, {"recursion_limit": 30})
    latency_seconds = perf_counter() - started_at
    query_result = final_state.get("query_result", {})
    generated_sql = final_state.get("generated_sql", "")
    execution_success = bool(final_state.get("execution_success", False))
    validation_success = bool(final_state.get("sql_valid", False))
    final_sql = str(query_result.get("executed_sql") or (generated_sql if execution_success else ""))
    row_count = int(query_result.get("row_count", 0) or 0)
    error_message = final_state.get("sql_error", "")
    error_type = derive_error_type(final_state)

    final_state.update(
        {
            "run_id": run_id,
            "question": user_question,
            "answer": final_state.get("final_answer", ""),
            "final_sql": final_sql,
            "model_primary": agent_config.primary_model,
            "model_used": final_state.get("selected_model", ""),
            "validation_success": validation_success,
            "execution_success": execution_success,
            "error_type": error_type,
            "error_message": error_message,
            "row_count": row_count,
            "latency_seconds": latency_seconds,
            "run_context": run_context,
            "use_approved_memory": use_approved_memory,
            "use_legacy_memory": use_legacy_memory,
            "enable_memory_candidate_generation": enable_memory_candidate_generation,
            "log_to_query_log": log_to_query_log,
            "language": language,
            "router_context": router_context or final_state.get("router_context", {}),
            "secondary_fallback_model": agent_config.secondary_fallback_model,
        }
    )
    if memory_retrieval is not None:
        final_state["memory_retrieval"] = memory_retrieval

    if log_to_query_log:
        log_query_run(
            run_id=run_id,
            question=user_question,
            generated_sql=generated_sql,
            final_sql=final_sql,
            model_primary=agent_config.primary_model,
            model_used=final_state.get("selected_model", ""),
            fallback_used=bool(final_state.get("fallback_used", False)),
            validation_success=validation_success,
            execution_success=execution_success,
            error_type=error_type,
            error_message=error_message,
            source_tables=final_state.get("source_tables", []),
            row_count=row_count,
            latency_seconds=latency_seconds,
            answer=final_state.get("final_answer", ""),
        )
    return final_state
