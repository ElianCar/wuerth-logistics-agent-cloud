from __future__ import annotations

from collections import Counter
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import io
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import yaml

from app.db import get_connection
from src.agent.db import execute_read_only_sql, get_active_backend_metadata, load_schema_context
from src.agent.id_utils import generate_run_id
from src.agent.langgraph_sql_agent import SQLAgentConfig, run_sql_agent
from src.agent.logging_utils import current_timestamp
from src.agent.sql_validator import validate_generated_sql
from src.config.scenarios import get_active_scenario


DEFAULT_COMPARE_CONFIG: dict[str, Any] = {
    "ignore_column_names": True,
    "ignore_row_order": True,
    "numeric_tolerance": 0.000001,
    "require_same_row_count": True,
    "require_same_column_count": True,
}

GoldenRuntimeMode = Literal["orchestrator", "direct_sql_agent"]
DEFAULT_GOLDEN_RUNTIME_MODE: GoldenRuntimeMode = "orchestrator"
GOLDEN_RUNTIME_MODES: tuple[GoldenRuntimeMode, ...] = ("orchestrator", "direct_sql_agent")


def resolve_golden_runtime_mode(
    runtime_mode: GoldenRuntimeMode | str | None = None,
    use_orchestrator: bool | None = None,
) -> GoldenRuntimeMode:
    if runtime_mode is not None:
        normalized = str(runtime_mode).strip().lower()
        if normalized not in GOLDEN_RUNTIME_MODES:
            supported = ", ".join(GOLDEN_RUNTIME_MODES)
            raise ValueError(f"Unsupported Golden runtime_mode '{runtime_mode}'. Use one of: {supported}.")
        return normalized  # type: ignore[return-value]

    if use_orchestrator is not None:
        return "orchestrator" if use_orchestrator else "direct_sql_agent"

    return DEFAULT_GOLDEN_RUNTIME_MODE


def evaluation_dir() -> Path:
    return get_active_scenario().evaluation_dir


def golden_questions_path() -> Path:
    return evaluation_dir() / "golden_questions.yaml"


def solution_sql_dir() -> Path:
    return evaluation_dir() / "solution_sql"


def golden_results_path() -> Path:
    return evaluation_dir() / "golden_results.jsonl"


def active_backend_name() -> str:
    try:
        metadata = get_active_backend_metadata()
    except Exception:
        return get_active_scenario().backend_name
    return str(metadata.get("backend_name") or get_active_scenario().backend_name)


def question_sort_key(question: dict[str, Any]) -> int:
    question_id = str(question.get("question_id", "")).upper()
    try:
        return int(question_id.removeprefix("Q"))
    except ValueError:
        return 999


def load_golden_questions(path: Path | None = None) -> list[dict[str, Any]]:
    resolved_path = path or golden_questions_path()
    with resolved_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if isinstance(data, dict):
        questions = data.get("questions", [])
    elif isinstance(data, list):
        questions = data
    else:
        questions = []

    normalized = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        copied = dict(question)
        copied["question_id"] = str(copied.get("question_id", "")).upper()
        normalized.append(copied)
    return sorted(normalized, key=question_sort_key)


def load_golden_question_map() -> dict[str, dict[str, Any]]:
    return {question["question_id"]: question for question in load_golden_questions()}


def read_solution_sql(question: dict[str, Any]) -> str:
    sql_file = str(question.get("solution_sql_file") or "").strip()
    if not sql_file:
        raise RuntimeError(f"{question.get('question_id', '')} has no solution_sql_file.")
    path = solution_sql_dir() / sql_file
    return path.read_text(encoding="utf-8").strip()


def execute_read_only_sql_full(sql: str, user_question: str = "") -> dict[str, Any]:
    cleaned_sql = sql.strip().rstrip(";").strip()
    if get_active_scenario().backend_name != "postgres":
        return execute_read_only_sql(cleaned_sql, user_question)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(f"EXPLAIN {cleaned_sql}")
            cursor.fetchall()
            cursor.execute(cleaned_sql)
            rows = cursor.fetchall()
            columns = [description.name for description in cursor.description]

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "executed_sql": cleaned_sql,
        "limit_applied": False,
    }


def is_nullish(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def decimal_or_none(value: Any) -> Decimal | None:
    if isinstance(value, bool) or is_nullish(value):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return Decimal(str(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return Decimal(stripped)
        except InvalidOperation:
            return None
    return None


def numeric_values_equal(
    expected: Decimal,
    actual: Decimal,
    *,
    numeric_tolerance: float,
) -> bool:
    difference = abs(expected - actual)
    return difference <= Decimal(str(numeric_tolerance))


def values_equal(
    expected: Any,
    actual: Any,
    *,
    numeric_tolerance: float,
) -> bool:
    if is_nullish(expected) or is_nullish(actual):
        return is_nullish(expected) and is_nullish(actual)

    expected_decimal = decimal_or_none(expected)
    actual_decimal = decimal_or_none(actual)
    if expected_decimal is not None and actual_decimal is not None:
        return numeric_values_equal(
            expected_decimal,
            actual_decimal,
            numeric_tolerance=numeric_tolerance,
        )

    if isinstance(expected, str) or isinstance(actual, str):
        expected_normalized = expected.strip() if isinstance(expected, str) else expected
        actual_normalized = actual.strip() if isinstance(actual, str) else actual
        return expected_normalized == actual_normalized

    if isinstance(expected, (date, datetime)) or isinstance(actual, (date, datetime)):
        return to_jsonable(expected) == to_jsonable(actual)

    return expected == actual


def resolve_compare_config(question: dict[str, Any] | None) -> dict[str, Any]:
    question = question or {}
    config = dict(DEFAULT_COMPARE_CONFIG)
    explicit_config = question.get("compare")
    if isinstance(explicit_config, dict):
        for key in DEFAULT_COMPARE_CONFIG:
            if key in explicit_config:
                config[key] = explicit_config[key]

    config["ignore_column_names"] = bool(config["ignore_column_names"])
    config["ignore_row_order"] = bool(config["ignore_row_order"])
    config["require_same_row_count"] = bool(config["require_same_row_count"])
    config["require_same_column_count"] = bool(config["require_same_column_count"])
    config["numeric_tolerance"] = float(config["numeric_tolerance"] or 0.0)
    return config


def rows_equal(
    expected: tuple[Any, ...] | list[Any],
    actual: tuple[Any, ...] | list[Any],
    *,
    numeric_tolerance: float,
) -> bool:
    if len(expected) != len(actual):
        return False
    return all(
        values_equal(
            expected_value,
            actual_value,
            numeric_tolerance=numeric_tolerance,
        )
        for expected_value, actual_value in zip(expected, actual)
    )


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def preview_result(query_result: dict[str, Any], max_rows: int) -> dict[str, Any]:
    return {
        "columns": to_jsonable(query_result.get("columns", [])),
        "rows": to_jsonable(list(query_result.get("rows", []))[:max_rows]),
    }


def first_mismatch(
    expected_rows: list[tuple[Any, ...]],
    actual_rows: list[tuple[Any, ...]],
    columns: list[str],
    *,
    numeric_tolerance: float,
) -> dict[str, Any] | None:
    for row_index, (expected_row, actual_row) in enumerate(zip(expected_rows, actual_rows)):
        for column_index, (expected_value, actual_value) in enumerate(zip(expected_row, actual_row)):
            if not values_equal(
                expected_value,
                actual_value,
                numeric_tolerance=numeric_tolerance,
            ):
                return {
                    "row_index": row_index,
                    "column": columns[column_index] if column_index < len(columns) else column_index,
                    "expected": to_jsonable(expected_value),
                    "actual": to_jsonable(actual_value),
                }
    return None


def match_unordered_rows(
    expected_rows: list[tuple[Any, ...]],
    actual_rows: list[tuple[Any, ...]],
    *,
    numeric_tolerance: float,
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    unmatched_actual_indexes = set(range(len(actual_rows)))
    missing_rows = []

    for expected_row in expected_rows:
        matched_index = None
        for actual_index in sorted(unmatched_actual_indexes):
            if rows_equal(
                expected_row,
                actual_rows[actual_index],
                numeric_tolerance=numeric_tolerance,
            ):
                matched_index = actual_index
                break
        if matched_index is None:
            missing_rows.append(expected_row)
        else:
            unmatched_actual_indexes.remove(matched_index)

    unexpected_rows = [actual_rows[index] for index in sorted(unmatched_actual_indexes)]
    return missing_rows, unexpected_rows


def row_values_match_as_multiset(
    expected_row: tuple[Any, ...] | list[Any],
    actual_row: tuple[Any, ...] | list[Any],
    *,
    numeric_tolerance: float,
) -> bool:
    """True when both rows contain the same values, regardless of column order.

    Used for the looser "content correct" metric: it catches cases where the agent's
    SQL returns the right data but with columns in a different order than the
    reference (e.g. ``plant, metric, ...`` instead of ``metric, plant, ...``), which
    the strict positional comparison would otherwise flag as a value mismatch.
    """
    if len(expected_row) != len(actual_row):
        return False
    remaining = list(actual_row)
    for expected_value in expected_row:
        matched_index = None
        for index, actual_value in enumerate(remaining):
            if values_equal(expected_value, actual_value, numeric_tolerance=numeric_tolerance):
                matched_index = index
                break
        if matched_index is None:
            return False
        remaining.pop(matched_index)
    return True


def match_rows_as_multisets(
    expected_rows: list[tuple[Any, ...]],
    actual_rows: list[tuple[Any, ...]],
    *,
    numeric_tolerance: float,
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    unmatched_actual_indexes = set(range(len(actual_rows)))
    missing_rows = []

    for expected_row in expected_rows:
        matched_index = None
        for actual_index in sorted(unmatched_actual_indexes):
            if row_values_match_as_multiset(
                expected_row,
                actual_rows[actual_index],
                numeric_tolerance=numeric_tolerance,
            ):
                matched_index = actual_index
                break
        if matched_index is None:
            missing_rows.append(expected_row)
        else:
            unmatched_actual_indexes.remove(matched_index)

    unexpected_rows = [actual_rows[index] for index in sorted(unmatched_actual_indexes)]
    return missing_rows, unexpected_rows


def rows_are_multiset_subset(
    actual_rows: list[tuple[Any, ...]],
    expected_rows: list[tuple[Any, ...]],
    *,
    numeric_tolerance: float,
) -> bool:
    """True when every actual row matches a distinct expected row.

    Rows are compared as unordered value sets, so a differing column order still
    matches. Matched expected rows are consumed, so duplicates must be backed by
    equally many reference rows.
    """
    remaining = list(expected_rows)
    for actual_row in actual_rows:
        matched_index = None
        for index, expected_row in enumerate(remaining):
            if row_values_match_as_multiset(
                expected_row, actual_row, numeric_tolerance=numeric_tolerance
            ):
                matched_index = index
                break
        if matched_index is None:
            return False
        remaining.pop(matched_index)
    return True


def is_content_correct(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    numeric_tolerance: float,
) -> bool:
    """Looser correctness check reported alongside the strict ``passed`` verdict.

    Requires the same column count and that every returned row matches a distinct
    reference row, comparing each row's values without regard to column order. Row
    counts may differ: a truncated result (e.g. the agent appending ``LIMIT 50`` to a
    3952-row reference) still counts as content correct as long as every row it did
    return is genuinely in the reference. An empty result never counts.
    """
    expected_columns = list(expected.get("columns", []))
    actual_columns = list(actual.get("columns", []))
    if len(expected_columns) != len(actual_columns):
        return False

    expected_rows = [tuple(row) for row in expected.get("rows", [])]
    actual_rows = [tuple(row) for row in actual.get("rows", [])]
    if not actual_rows:
        return False

    return rows_are_multiset_subset(
        actual_rows, expected_rows, numeric_tolerance=numeric_tolerance
    )


def normalized_row_key(row: tuple[Any, ...]) -> tuple[Any, ...]:
    normalized = []
    for value in row:
        if is_nullish(value):
            normalized.append(None)
        elif isinstance(value, str):
            normalized.append(value.strip())
        elif isinstance(value, (date, datetime)):
            normalized.append(to_jsonable(value))
        else:
            normalized.append(value)
    return tuple(normalized)


def has_duplicate_count_mismatch(
    expected_rows: list[tuple[Any, ...]],
    actual_rows: list[tuple[Any, ...]],
) -> bool:
    expected_counts: dict[tuple[Any, ...], int] = {}
    actual_counts: dict[tuple[Any, ...], int] = {}

    for row in expected_rows:
        key = normalized_row_key(row)
        expected_counts[key] = expected_counts.get(key, 0) + 1
    for row in actual_rows:
        key = normalized_row_key(row)
        actual_counts[key] = actual_counts.get(key, 0) + 1

    duplicate_keys = {
        key
        for key, count in expected_counts.items()
        if count > 1 or actual_counts.get(key, 0) > 1
    }
    duplicate_keys.update(key for key, count in actual_counts.items() if count > 1)
    return any(expected_counts.get(key, 0) != actual_counts.get(key, 0) for key in duplicate_keys)


def append_issue(issues: list[str], issue: str) -> None:
    if issue not in issues:
        issues.append(issue)


def compare_query_results(
    expected: dict[str, Any],
    actual: dict[str, Any],
    question: dict[str, Any],
) -> dict[str, Any]:
    config = resolve_compare_config(question)
    expected_columns = list(expected.get("columns", []))
    actual_columns = list(actual.get("columns", []))
    expected_rows = [tuple(row) for row in expected.get("rows", [])]
    actual_rows = [tuple(row) for row in actual.get("rows", [])]
    numeric_tolerance = float(config["numeric_tolerance"])

    issues: list[str] = []
    summary: dict[str, Any] = {
        "passed": True,
        "issues": issues,
        "compare": config,
        "ignore_column_names": config["ignore_column_names"],
        "ignore_row_order": config["ignore_row_order"],
        "order_sensitive": not config["ignore_row_order"],
        "compare_column_names": not config["ignore_column_names"],
        # Looser metric: same column count and every returned row matches a distinct
        # reference row ignoring column order; a truncated result still counts.
        # Reported alongside "passed" (strict, positional) — it never changes pass/fail.
        "content_correct": is_content_correct(expected, actual, numeric_tolerance=numeric_tolerance),
    }

    if config["require_same_column_count"] and len(expected_columns) != len(actual_columns):
        append_issue(issues, "column count mismatch")
        summary["column_count_mismatch"] = {
            "expected_columns": len(expected_columns),
            "actual_columns": len(actual_columns),
        }

    if not config["ignore_column_names"] and expected_columns != actual_columns:
        append_issue(issues, "column name mismatch")
        summary["column_name_mismatch"] = {
            "expected_columns": expected_columns,
            "actual_columns": actual_columns,
        }

    if config["require_same_row_count"] and len(expected_rows) != len(actual_rows):
        append_issue(issues, "row count mismatch")
        summary["row_count_mismatch"] = {
            "expected_rows": len(expected_rows),
            "actual_rows": len(actual_rows),
        }

    if len(expected_columns) != len(actual_columns):
        summary["passed"] = False
        return summary

    if config["ignore_row_order"]:
        missing_rows, unexpected_rows = match_unordered_rows(
            expected_rows,
            actual_rows,
            numeric_tolerance=numeric_tolerance,
        )
        if missing_rows or unexpected_rows:
            append_issue(issues, "row values differ ignoring order")
            summary["missing_rows"] = to_jsonable(missing_rows[:5])
            summary["unexpected_rows"] = to_jsonable(unexpected_rows[:5])
            mismatch = first_mismatch(
                expected_rows,
                actual_rows,
                expected_columns,
                numeric_tolerance=numeric_tolerance,
            )
            if mismatch:
                summary["value_mismatch"] = mismatch
                expected_decimal = decimal_or_none(mismatch.get("expected"))
                actual_decimal = decimal_or_none(mismatch.get("actual"))
                if expected_decimal is not None and actual_decimal is not None:
                    append_issue(issues, "numeric value outside tolerance")
                elif is_nullish(mismatch.get("expected")) or is_nullish(mismatch.get("actual")):
                    append_issue(issues, "null mismatch")
                else:
                    append_issue(issues, "value mismatch")
            if has_duplicate_count_mismatch(expected_rows, actual_rows):
                append_issue(issues, "duplicate row count mismatch")
    else:
        ordered_match = (
            len(expected_rows) == len(actual_rows)
            and all(
                rows_equal(
                    expected_row,
                    actual_row,
                    numeric_tolerance=numeric_tolerance,
                )
                for expected_row, actual_row in zip(expected_rows, actual_rows)
            )
        )
        if not ordered_match:
            append_issue(issues, "row values differ with order enforced")
            mismatch = first_mismatch(
                expected_rows,
                actual_rows,
                expected_columns,
                numeric_tolerance=numeric_tolerance,
            )
            if mismatch:
                summary["value_mismatch"] = mismatch

    summary["passed"] = not issues
    return summary


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


def _runtime_route_status(raw_result: dict[str, Any]) -> str:
    if bool(raw_result.get("blocked_or_unsafe", False)):
        return "blocked"
    if bool(raw_result.get("needs_clarification", False)):
        return "needs_clarification"
    if raw_result.get("needs_sql") is False:
        return "no_sql_required"
    if raw_result.get("generated_sql") or raw_result.get("final_sql"):
        return "routed_to_sql"
    return "failed"


def _normalize_golden_runtime_result(
    raw_result: dict[str, Any] | None,
    runtime_mode: GoldenRuntimeMode,
    active_scenario: str | None = None,
) -> dict[str, Any]:
    raw_result = raw_result or {}
    scenario_id = active_scenario or get_active_scenario().scenario_id
    query_result = raw_result.get("query_result", {})
    if not isinstance(query_result, dict):
        query_result = {}
    memory_retrieval = raw_result.get("memory_retrieval", {})
    if not isinstance(memory_retrieval, dict):
        memory_retrieval = {}

    generated_sql = str(raw_result.get("generated_sql") or raw_result.get("final_sql") or "")
    trace_steps = raw_result.get("trace_steps", [])
    if not isinstance(trace_steps, list):
        trace_steps = []

    return {
        "raw_result": raw_result,
        "runtime_mode": runtime_mode,
        "active_scenario": scenario_id,
        "status": _runtime_route_status(raw_result),
        "route_status": _runtime_route_status(raw_result),
        "intent": raw_result.get("intent", ""),
        "route": raw_result.get("intent", ""),
        "needs_sql": raw_result.get("needs_sql", ""),
        "needs_clarification": raw_result.get("needs_clarification", ""),
        "blocked_or_unsafe": raw_result.get("blocked_or_unsafe", ""),
        "complexity": raw_result.get("complexity_tier", ""),
        "complexity_tier": raw_result.get("complexity_tier", ""),
        "complexity_reason": raw_result.get("complexity_reason", ""),
        "selected_model": raw_result.get("selected_model", ""),
        "primary_model": raw_result.get("primary_model") or raw_result.get("model_primary", ""),
        "fallback_model": raw_result.get("fallback_model", ""),
        "secondary_fallback_model": raw_result.get("secondary_fallback_model", ""),
        "model_used": raw_result.get("model_used") or raw_result.get("selected_model", ""),
        "fallback_used": raw_result.get("fallback_used", False),
        "total_attempts": int(raw_result.get("total_attempts", 0) or 0),
        "sql_repaired": any("sql-reparatur" in str(step).lower() for step in trace_steps),
        "final_answer": raw_result.get("final_answer") or raw_result.get("answer", ""),
        "generated_sql": generated_sql,
        "source_tables": raw_result.get("source_tables", []),
        "query_result": query_result,
        "result_rows": query_result.get("rows", []),
        "row_count": int(raw_result.get("row_count") or query_result.get("row_count") or 0),
        "validation_success": raw_result.get("validation_success", raw_result.get("sql_valid", False)),
        "execution_success": raw_result.get("execution_success", False),
        "validation_error": raw_result.get("sql_error", ""),
        "execution_error": raw_result.get("error_message", ""),
        "result_status": raw_result.get("result_status", ""),
        "memory_retrieval": memory_retrieval,
        "memory_enabled": memory_retrieval.get("enabled", ""),
        "memory_method": memory_retrieval.get("method", ""),
        "memory_scenario": memory_retrieval.get("scenario", ""),
        "memory_no_match_reason": memory_retrieval.get("no_match_reason", ""),
        "memory_ambiguous": memory_retrieval.get("ambiguous", ""),
        "memory_candidate_ids": _memory_candidate_ids(memory_retrieval),
        "memory_candidate_scores": _memory_candidate_scores(memory_retrieval),
        "trace": trace_steps,
        "trace_steps": trace_steps,
    }


def _golden_runtime_metadata(normalized_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime_mode": normalized_result.get("runtime_mode", DEFAULT_GOLDEN_RUNTIME_MODE),
        "active_scenario": normalized_result.get("active_scenario", get_active_scenario().scenario_id),
        "route_status": normalized_result.get("route_status", ""),
        "intent": normalized_result.get("intent", ""),
        "needs_sql": normalized_result.get("needs_sql", ""),
        "needs_clarification": normalized_result.get("needs_clarification", ""),
        "blocked_or_unsafe": normalized_result.get("blocked_or_unsafe", ""),
        "complexity_tier": normalized_result.get("complexity_tier", ""),
        "complexity_reason": normalized_result.get("complexity_reason", ""),
        "selected_model": normalized_result.get("selected_model", ""),
        "primary_model": normalized_result.get("primary_model", ""),
        "fallback_model": normalized_result.get("fallback_model", ""),
        "secondary_fallback_model": normalized_result.get("secondary_fallback_model", ""),
        "fallback_used": normalized_result.get("fallback_used", False),
        "total_attempts": normalized_result.get("total_attempts", 0),
        "sql_repaired": normalized_result.get("sql_repaired", False),
        "source_tables": normalized_result.get("source_tables", []),
        "validation_success": normalized_result.get("validation_success", False),
        "execution_success": normalized_result.get("execution_success", False),
        "final_answer": normalized_result.get("final_answer", ""),
        "memory_retrieval_enabled": normalized_result.get("memory_enabled", ""),
        "memory_retrieval_method": normalized_result.get("memory_method", ""),
        "memory_retrieval_scenario": normalized_result.get("memory_scenario", ""),
        "memory_retrieval_no_match_reason": normalized_result.get("memory_no_match_reason", ""),
        "memory_retrieval_ambiguous": normalized_result.get("memory_ambiguous", ""),
        "memory_candidate_ids": normalized_result.get("memory_candidate_ids", ""),
        "memory_candidate_scores": normalized_result.get("memory_candidate_scores", ""),
    }


def _chart_info(agent_state: dict[str, Any] | None) -> tuple[bool, str]:
    """Extract (chart_rendered, chart_type) from an orchestrator agent result.

    Reads the chart spec attached by the orchestrator (``chart_spec`` or
    ``reporting_result.chart_plan``). Returns (False, "none") when unavailable,
    e.g. in direct SQL-agent mode or on failure paths.
    """
    if not isinstance(agent_state, dict):
        return False, "none"
    chart_spec = agent_state.get("chart_spec")
    if not isinstance(chart_spec, dict):
        reporting_result = agent_state.get("reporting_result")
        chart_spec = reporting_result.get("chart_plan") if isinstance(reporting_result, dict) else None
    if not isinstance(chart_spec, dict):
        return False, "none"
    chart_type = str(chart_spec.get("chart_type") or "none")
    chart_rendered = bool(chart_spec.get("render_allowed")) and chart_type != "none"
    return chart_rendered, chart_type


def build_error_result(
    *,
    batch_run_id: str,
    question: dict[str, Any],
    started_at_iso: str,
    runtime_seconds: float,
    failure_type: str,
    failure_reason: str,
    reference_sql: str = "",
    generated_sql: str = "",
    agent_state: dict[str, Any] | None = None,
    expected_result: dict[str, Any] | None = None,
    actual_result: dict[str, Any] | None = None,
    use_approved_memory: bool,
    runtime_mode: GoldenRuntimeMode = DEFAULT_GOLDEN_RUNTIME_MODE,
    active_scenario: str | None = None,
) -> dict[str, Any]:
    max_preview_rows = int(question.get("max_preview_rows", 20) or 20)
    normalized_result = _normalize_golden_runtime_result(
        agent_state,
        runtime_mode,
        active_scenario=active_scenario,
    )
    status = "error" if failure_type.startswith("reference_") or failure_type in {"agent_error", "unexpected_error"} else "failed"
    return {
        "golden_run_id": batch_run_id,
        "agent_run_id": normalized_result.get("raw_result", {}).get("run_id", ""),
        "question_id": question.get("question_id", ""),
        "title": question.get("title", ""),
        "question": question.get("question", ""),
        "status": status,
        "passed": False,
        "content_correct": False,
        "failure_type": failure_type,
        "failure_reason": failure_reason,
        "runtime_seconds": runtime_seconds,
        "expected_row_count": int((expected_result or {}).get("row_count", 0) or 0),
        "actual_row_count": int((actual_result or {}).get("row_count", 0) or 0),
        "generated_agent_sql": generated_sql,
        "reference_sql": reference_sql,
        "expected_output_preview": preview_result(expected_result or {}, max_preview_rows),
        "actual_output_preview": preview_result(actual_result or {}, max_preview_rows),
        "diff_summary": {"passed": False, "content_correct": False, "issues": [failure_type]},
        "validation_errors": [failure_reason] if "validation" in failure_type else [],
        "execution_errors": {failure_type: failure_reason} if "execution" in failure_type else {},
        "model_used": normalized_result.get("model_used", ""),
        "memory_templates_enabled": use_approved_memory,
        "chart_rendered": _chart_info(agent_state)[0],
        "chart_type": _chart_info(agent_state)[1],
        "backend": active_backend_name(),
        "timestamp": started_at_iso,
        "agent_result_status": normalized_result.get("result_status", ""),
        "agent_trace_steps": normalized_result.get("trace_steps", []),
        **_golden_runtime_metadata(normalized_result),
    }


def run_golden_agent(
    question: dict[str, Any],
    *,
    schema_context: str,
    use_approved_memory: bool,
    config: SQLAgentConfig | None,
    runtime_mode: GoldenRuntimeMode | str | None = None,
    use_orchestrator: bool | None = None,
) -> dict[str, Any]:
    resolved_runtime_mode = resolve_golden_runtime_mode(runtime_mode, use_orchestrator)
    if resolved_runtime_mode == "orchestrator":
        return run_orchestrator_for_golden(
            question,
            schema_context=schema_context,
            use_approved_memory=use_approved_memory,
            config=config,
        )

    try:
        return run_sql_agent(
            question.get("question", ""),
            config=config,
            run_context="golden_test",
            use_approved_memory=use_approved_memory,
            use_legacy_memory=False,
            enable_memory_candidate_generation=False,
            log_to_query_log=False,
            schema_loader=lambda: schema_context,
            sql_executor=execute_read_only_sql_full,
        )
    except NameError as error:
        if str(error) != "name 'Any' is not defined":
            raise
        import src.agent.langgraph_sql_agent as langgraph_sql_agent

        langgraph_sql_agent.Any = Any
        return run_sql_agent(
            question.get("question", ""),
            config=config,
            run_context="golden_test",
            use_approved_memory=use_approved_memory,
            use_legacy_memory=False,
            enable_memory_candidate_generation=False,
            log_to_query_log=False,
            schema_loader=lambda: schema_context,
            sql_executor=execute_read_only_sql_full,
        )


def run_orchestrator_for_golden(
    question: dict[str, Any],
    *,
    schema_context: str,
    use_approved_memory: bool,
    config: SQLAgentConfig | None,
) -> dict[str, Any]:
    # Default Golden mode intentionally exercises the same runtime path as
    # Streamlit Chat. The frozen schema_context is retained for direct SQL-agent
    # debug mode and reference-output comparison, not injected here.
    _ = schema_context
    from src.agent.orchestrator import run_orchestrator

    return run_orchestrator(
        question.get("question", ""),
        config=config,
        run_context="golden_test_orchestrator",
        use_approved_memory=use_approved_memory,
        enable_memory_candidate_generation=False,
        log_to_query_log=False,
    )


def evaluate_golden_question(
    question: dict[str, Any],
    *,
    batch_run_id: str,
    schema_context: str,
    use_approved_memory: bool,
    config: SQLAgentConfig | None = None,
    runtime_mode: GoldenRuntimeMode | str | None = None,
    use_orchestrator: bool | None = None,
) -> dict[str, Any]:
    resolved_runtime_mode = resolve_golden_runtime_mode(runtime_mode, use_orchestrator)
    active_scenario = get_active_scenario().scenario_id
    started_at = perf_counter()
    started_at_iso = current_timestamp()
    reference_sql = read_solution_sql(question)
    max_preview_rows = int(question.get("max_preview_rows", 20) or 20)
    expected_result: dict[str, Any] = {}
    actual_result: dict[str, Any] = {}
    agent_state: dict[str, Any] = {}

    reference_validation = validate_generated_sql(reference_sql, schema_context)
    if not reference_validation.is_valid:
        return build_error_result(
            batch_run_id=batch_run_id,
            question=question,
            started_at_iso=started_at_iso,
            runtime_seconds=perf_counter() - started_at,
            failure_type="reference_sql_validation_error",
            failure_reason=reference_validation.error,
            reference_sql=reference_sql,
            use_approved_memory=use_approved_memory,
            runtime_mode=resolved_runtime_mode,
            active_scenario=active_scenario,
        )

    try:
        expected_result = execute_read_only_sql_full(reference_validation.sql, question.get("question", ""))
    except Exception as error:
        return build_error_result(
            batch_run_id=batch_run_id,
            question=question,
            started_at_iso=started_at_iso,
            runtime_seconds=perf_counter() - started_at,
            failure_type="reference_sql_execution_error",
            failure_reason=str(error),
            reference_sql=reference_validation.sql,
            expected_result=expected_result,
            use_approved_memory=use_approved_memory,
            runtime_mode=resolved_runtime_mode,
            active_scenario=active_scenario,
        )

    try:
        agent_state = run_golden_agent(
            question,
            schema_context=schema_context,
            use_approved_memory=use_approved_memory,
            config=config,
            runtime_mode=resolved_runtime_mode,
        )
    except Exception as error:
        return build_error_result(
            batch_run_id=batch_run_id,
            question=question,
            started_at_iso=started_at_iso,
            runtime_seconds=perf_counter() - started_at,
            failure_type="agent_error",
            failure_reason=str(error),
            reference_sql=reference_validation.sql,
            expected_result=expected_result,
            use_approved_memory=use_approved_memory,
            runtime_mode=resolved_runtime_mode,
            active_scenario=active_scenario,
        )

    normalized_agent_result = _normalize_golden_runtime_result(
        agent_state,
        resolved_runtime_mode,
        active_scenario=active_scenario,
    )
    if normalized_agent_result.get("route_status") != "routed_to_sql":
        return build_error_result(
            batch_run_id=batch_run_id,
            question=question,
            started_at_iso=started_at_iso,
            runtime_seconds=perf_counter() - started_at,
            failure_type="router_not_routed_to_sql",
            failure_reason=str(normalized_agent_result.get("route_status", "failed")),
            reference_sql=reference_validation.sql,
            agent_state=normalized_agent_result,
            expected_result=expected_result,
            use_approved_memory=use_approved_memory,
            runtime_mode=resolved_runtime_mode,
            active_scenario=active_scenario,
        )

    generated_sql = str(normalized_agent_result.get("generated_sql", ""))
    agent_validation = validate_generated_sql(generated_sql, schema_context)
    if not agent_validation.is_valid:
        return build_error_result(
            batch_run_id=batch_run_id,
            question=question,
            started_at_iso=started_at_iso,
            runtime_seconds=perf_counter() - started_at,
            failure_type="sql_validation",
            failure_reason=agent_validation.error,
            reference_sql=reference_validation.sql,
            generated_sql=agent_validation.sql or generated_sql,
            agent_state=normalized_agent_result,
            expected_result=expected_result,
            use_approved_memory=use_approved_memory,
            runtime_mode=resolved_runtime_mode,
            active_scenario=active_scenario,
        )

    try:
        actual_result = execute_read_only_sql_full(agent_validation.sql, question.get("question", ""))
    except Exception as error:
        return build_error_result(
            batch_run_id=batch_run_id,
            question=question,
            started_at_iso=started_at_iso,
            runtime_seconds=perf_counter() - started_at,
            failure_type="execution_error",
            failure_reason=str(error),
            reference_sql=reference_validation.sql,
            generated_sql=agent_validation.sql,
            agent_state=normalized_agent_result,
            expected_result=expected_result,
            actual_result=actual_result,
            use_approved_memory=use_approved_memory,
            runtime_mode=resolved_runtime_mode,
            active_scenario=active_scenario,
        )

    diff_summary = compare_query_results(expected_result, actual_result, question)
    passed = bool(diff_summary.get("passed"))
    failure_reason = ""
    if not passed:
        failure_reason = ", ".join(diff_summary.get("issues", [])) or "output mismatch"

    return {
        "golden_run_id": batch_run_id,
        "agent_run_id": agent_state.get("run_id", ""),
        "question_id": question.get("question_id", ""),
        "title": question.get("title", ""),
        "question": question.get("question", ""),
        "status": "passed" if passed else "failed",
        "passed": passed,
        "content_correct": bool(diff_summary.get("content_correct", False)),
        "failure_type": "" if passed else "output_mismatch",
        "failure_reason": failure_reason,
        "runtime_seconds": perf_counter() - started_at,
        "expected_row_count": int(expected_result.get("row_count", 0) or 0),
        "actual_row_count": int(actual_result.get("row_count", 0) or 0),
        "generated_agent_sql": agent_validation.sql,
        "reference_sql": reference_validation.sql,
        "expected_output_preview": preview_result(expected_result, max_preview_rows),
        "actual_output_preview": preview_result(actual_result, max_preview_rows),
        "diff_summary": diff_summary,
        "validation_errors": [],
        "execution_errors": {},
        "model_used": normalized_agent_result.get("model_used", ""),
        "memory_templates_enabled": use_approved_memory,
        "chart_rendered": _chart_info(agent_state)[0],
        "chart_type": _chart_info(agent_state)[1],
        "backend": active_backend_name(),
        "timestamp": started_at_iso,
        "agent_result_status": normalized_agent_result.get("result_status", ""),
        "agent_trace_steps": normalized_agent_result.get("trace_steps", []),
        **_golden_runtime_metadata(normalized_agent_result),
    }


def append_golden_result(result: dict[str, Any]) -> None:
    path = golden_results_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(to_jsonable(result), sort_keys=True) + "\n")


def build_result_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.get("passed"))
    output_mismatch = sum(1 for result in results if result.get("failure_type") == "output_mismatch")
    sql_validation = sum(1 for result in results if result.get("failure_type") == "sql_validation")
    execution_error = sum(
        1
        for result in results
        if result.get("failure_type") in {"execution_error", "reference_sql_execution_error"}
    )
    errored = sum(1 for result in results if result.get("status") == "error")
    total_runtime = sum(float(result.get("runtime_seconds", 0.0) or 0.0) for result in results)

    return {
        "total_tests_run": total,
        "passed": passed,
        "failed_output_mismatch": output_mismatch,
        "failed_sql_validation": sql_validation,
        "failed_execution_error": execution_error,
        "errored": errored,
        "pass_rate": passed / total if total else 0.0,
        "average_runtime": total_runtime / total if total else 0.0,
    }


def run_golden_tests(
    question_ids: list[str],
    *,
    use_approved_memory: bool = True,
    config: SQLAgentConfig | None = None,
    runtime_mode: GoldenRuntimeMode | str | None = None,
    use_orchestrator: bool | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    resolved_runtime_mode = resolve_golden_runtime_mode(runtime_mode, use_orchestrator)
    active_scenario = get_active_scenario().scenario_id
    question_map = load_golden_question_map()
    selected_ids = [question_id.upper() for question_id in question_ids if question_id.upper() in question_map]
    batch_run_id = f"golden_{generate_run_id()}"
    schema_context = load_schema_context()
    results = []

    for question_id in selected_ids:
        try:
            result = evaluate_golden_question(
                question_map[question_id],
                batch_run_id=batch_run_id,
                schema_context=schema_context,
                use_approved_memory=use_approved_memory,
                config=config,
                runtime_mode=resolved_runtime_mode,
            )
        except Exception as error:
            question = question_map[question_id]
            result = build_error_result(
                batch_run_id=batch_run_id,
                question=question,
                started_at_iso=current_timestamp(),
                runtime_seconds=0.0,
                failure_type="unexpected_error",
                failure_reason=str(error),
                use_approved_memory=use_approved_memory,
                runtime_mode=resolved_runtime_mode,
                active_scenario=active_scenario,
            )
        append_golden_result(result)
        results.append(result)

    return batch_run_id, results, build_result_summary(results)


CONDITION_LABELS: dict[bool, str] = {
    False: "without_template",
    True: "with_template",
}


def _aggregate_golden_report(
    raw_runs: list[dict[str, Any]],
    question_ids: list[str],
    conditions: tuple[bool, ...],
    question_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    aggregates: list[dict[str, Any]] = []
    for question_id in question_ids:
        title = str(question_map.get(question_id, {}).get("title", ""))
        for condition in conditions:
            runs = [
                run
                for run in raw_runs
                if run.get("question_id") == question_id
                and bool(run.get("condition_memory")) == bool(condition)
            ]
            total = len(runs)
            sql_pass = sum(1 for run in runs if run.get("passed"))
            content_correct = sum(1 for run in runs if run.get("content_correct"))
            chart_rendered = sum(1 for run in runs if run.get("chart_rendered"))
            chart_types = Counter(str(run.get("chart_type") or "none") for run in runs)
            total_runtime = sum(float(run.get("runtime_seconds", 0.0) or 0.0) for run in runs)
            aggregates.append(
                {
                    "question_id": question_id,
                    "title": title,
                    "condition_memory": bool(condition),
                    "condition_label": CONDITION_LABELS.get(bool(condition), str(condition)),
                    "runs": total,
                    "sql_correct": sql_pass,
                    "sql_correct_pct": (sql_pass / total * 100.0) if total else 0.0,
                    "content_correct": content_correct,
                    "content_correct_pct": (content_correct / total * 100.0) if total else 0.0,
                    "chart_rendered": chart_rendered,
                    "chart_rendered_pct": (chart_rendered / total * 100.0) if total else 0.0,
                    "chart_type_distribution": dict(chart_types),
                    "average_runtime": (total_runtime / total) if total else 0.0,
                }
            )
    return aggregates


def run_golden_report(
    question_ids: list[str],
    *,
    repetitions: int = 30,
    conditions: tuple[bool, ...] = (False, True),
    config: SQLAgentConfig | None = None,
    runtime_mode: GoldenRuntimeMode | str | None = None,
    progress_callback: Any = None,
) -> dict[str, Any]:
    """Run each golden question ``repetitions`` times per condition and aggregate.

    ``conditions`` is a tuple of ``use_approved_memory`` values, e.g. ``(False, True)``
    to compare "without template" against "with template". Returns raw per-run rows plus
    per-(question, condition) aggregates (SQL-correct %, chart-rendered %, chart-type
    distribution, average runtime). Uses the orchestrator runtime by default so chart
    generation is exercised.
    """
    if repetitions < 1:
        raise ValueError("repetitions must be >= 1.")
    resolved_runtime_mode = resolve_golden_runtime_mode(runtime_mode, None)
    active_scenario = get_active_scenario().scenario_id
    question_map = load_golden_question_map()
    selected_ids = [question_id.upper() for question_id in question_ids if question_id.upper() in question_map]
    if not selected_ids:
        raise ValueError("No known golden question ids were selected for the report.")

    batch_run_id = f"golden_report_{generate_run_id()}"
    schema_context = load_schema_context()
    raw_runs: list[dict[str, Any]] = []
    total_steps = len(conditions) * repetitions * len(selected_ids)
    step = 0

    for condition in conditions:
        for repetition in range(1, repetitions + 1):
            for question_id in selected_ids:
                step += 1
                try:
                    result = evaluate_golden_question(
                        question_map[question_id],
                        batch_run_id=batch_run_id,
                        schema_context=schema_context,
                        use_approved_memory=bool(condition),
                        config=config,
                        runtime_mode=resolved_runtime_mode,
                    )
                except Exception as error:
                    result = build_error_result(
                        batch_run_id=batch_run_id,
                        question=question_map[question_id],
                        started_at_iso=current_timestamp(),
                        runtime_seconds=0.0,
                        failure_type="unexpected_error",
                        failure_reason=str(error),
                        use_approved_memory=bool(condition),
                        runtime_mode=resolved_runtime_mode,
                        active_scenario=active_scenario,
                    )
                result["repetition"] = repetition
                result["condition_memory"] = bool(condition)
                result["condition_label"] = CONDITION_LABELS.get(bool(condition), str(condition))
                raw_runs.append(result)
                if callable(progress_callback):
                    progress_callback(step, total_steps, result)

    aggregates = _aggregate_golden_report(raw_runs, selected_ids, tuple(conditions), question_map)
    return {
        "batch_run_id": batch_run_id,
        "scenario": active_scenario,
        "backend": active_backend_name(),
        "repetitions": repetitions,
        "conditions": [bool(condition) for condition in conditions],
        "question_ids": selected_ids,
        "raw_runs": raw_runs,
        "aggregates": aggregates,
    }


CONDITION_DISPLAY_LABELS: dict[str, str] = {
    "without_template": "ohne Template",
    "with_template": "mit Template",
}

GOLDEN_REPORT_CSV_FIELDS = (
    "question_id",
    "condition_label",
    "repetition",
    "passed",
    "content_correct",
    "status",
    "failure_type",
    "failure_reason",
    "chart_rendered",
    "chart_type",
    "runtime_seconds",
    "memory_candidate_ids",
    "generated_agent_sql",
    "model_used",
    "complexity_tier",
    "intent",
    "sql_repaired",
    "total_attempts",
)


def golden_report_dir() -> Path:
    return evaluation_dir() / "reports"


def golden_report_runs_path() -> Path:
    return evaluation_dir() / "golden_report_runs.jsonl"


def build_golden_report_csv(raw_runs: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(GOLDEN_REPORT_CSV_FIELDS), extrasaction="ignore")
    writer.writeheader()
    for run in raw_runs:
        writer.writerow({field: run.get(field, "") for field in GOLDEN_REPORT_CSV_FIELDS})
    return buffer.getvalue()


def write_golden_report_csv(path: Path, raw_runs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_golden_report_csv(raw_runs), encoding="utf-8", newline="")


def _format_chart_type_distribution(distribution: dict[str, int]) -> str:
    if not distribution:
        return "—"
    ordered = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{name}: {count}" for name, count in ordered)


def build_golden_report_markdown(report: dict[str, Any]) -> str:
    aggregates = report.get("aggregates", [])
    by_question: dict[str, list[dict[str, Any]]] = {}
    for row in aggregates:
        by_question.setdefault(str(row.get("question_id", "")), []).append(row)

    lines = [
        f"# Golden-Report — {report.get('scenario', '')}",
        "",
        f"- Läufe pro Frage und Bedingung: **{report.get('repetitions', 0)}**",
        f"- Backend: {report.get('backend', '')}",
        f"- Batch: `{report.get('batch_run_id', '')}`",
        f"- Erstellt: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]

    for question_id in sorted(by_question):
        rows = sorted(by_question[question_id], key=lambda item: bool(item.get("condition_memory")))
        title = str(rows[0].get("title", "")) if rows else ""
        lines.append(f"## {question_id} — {title}".rstrip())
        lines.append("")
        lines.append("| Bedingung | SQL korrekt | Inhaltlich korrekt | Chart erzeugt | Chart-Typen | Ø Laufzeit |")
        lines.append("|---|---|---|---|---|---|")
        for row in rows:
            label_key = str(row.get("condition_label", ""))
            label = CONDITION_DISPLAY_LABELS.get(label_key, label_key)
            sql_cell = f"{float(row.get('sql_correct_pct', 0.0)):.1f}% ({row.get('sql_correct', 0)}/{row.get('runs', 0)})"
            content_cell = (
                f"{float(row.get('content_correct_pct', 0.0)):.1f}% "
                f"({row.get('content_correct', 0)}/{row.get('runs', 0)})"
            )
            chart_cell = (
                f"{float(row.get('chart_rendered_pct', 0.0)):.1f}% "
                f"({row.get('chart_rendered', 0)}/{row.get('runs', 0)})"
            )
            types_cell = _format_chart_type_distribution(row.get("chart_type_distribution", {}))
            runtime_cell = f"{float(row.get('average_runtime', 0.0)):.2f}s"
            lines.append(f"| {label} | {sql_cell} | {content_cell} | {chart_cell} | {types_cell} | {runtime_cell} |")
        lines.append("")
    return "\n".join(lines)


def append_golden_report_runs(raw_runs: list[dict[str, Any]]) -> None:
    path = golden_report_runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for run in raw_runs:
            file.write(json.dumps(to_jsonable(run), sort_keys=True) + "\n")


def save_golden_report(report: dict[str, Any], out_dir: Path | None = None) -> dict[str, Path]:
    """Persist a golden report as CSV + Markdown and return the written paths."""
    target_dir = out_dir or golden_report_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = target_dir / f"golden_report_{timestamp}.csv"
    markdown_path = target_dir / f"golden_report_{timestamp}_summary.md"

    write_golden_report_csv(csv_path, report.get("raw_runs", []))
    markdown_path.write_text(build_golden_report_markdown(report), encoding="utf-8")
    append_golden_report_runs(report.get("raw_runs", []))
    return {"csv": csv_path, "markdown": markdown_path}
