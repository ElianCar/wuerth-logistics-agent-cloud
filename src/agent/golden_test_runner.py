from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

from app.db import get_connection
from src.agent.db import load_schema_context
from src.agent.id_utils import generate_run_id
from src.agent.langgraph_sql_agent import SQLAgentConfig, run_sql_agent
from src.agent.logging_utils import current_timestamp
from src.agent.sql_validator import validate_generated_sql


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_DIR = PROJECT_ROOT / "evaluation"
GOLDEN_QUESTIONS_PATH = EVALUATION_DIR / "golden_questions.yaml"
SOLUTION_SQL_DIR = EVALUATION_DIR / "solution_sql"
GOLDEN_RESULTS_PATH = EVALUATION_DIR / "golden_results.jsonl"
BACKEND_NAME = "postgresql"


def question_sort_key(question: dict[str, Any]) -> int:
    question_id = str(question.get("question_id", "")).upper()
    try:
        return int(question_id.removeprefix("Q"))
    except ValueError:
        return 999


def load_golden_questions(path: Path = GOLDEN_QUESTIONS_PATH) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
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
    path = SOLUTION_SQL_DIR / sql_file
    return path.read_text(encoding="utf-8").strip()


def execute_read_only_sql_full(sql: str, user_question: str = "") -> dict[str, Any]:
    cleaned_sql = sql.strip().rstrip(";").strip()
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
        return Decimal(str(value))
    return None


def numeric_values_equal(
    expected: Decimal,
    actual: Decimal,
    *,
    abs_tolerance: float,
    rel_tolerance: float,
) -> bool:
    difference = abs(expected - actual)
    abs_limit = Decimal(str(abs_tolerance))
    rel_limit = Decimal(str(rel_tolerance)) * max(abs(expected), Decimal("1"))
    return difference <= max(abs_limit, rel_limit)


def values_equal(
    expected: Any,
    actual: Any,
    *,
    abs_tolerance: float,
    rel_tolerance: float,
) -> bool:
    if is_nullish(expected) or is_nullish(actual):
        return is_nullish(expected) and is_nullish(actual)

    expected_decimal = decimal_or_none(expected)
    actual_decimal = decimal_or_none(actual)
    if expected_decimal is not None and actual_decimal is not None:
        return numeric_values_equal(
            expected_decimal,
            actual_decimal,
            abs_tolerance=abs_tolerance,
            rel_tolerance=rel_tolerance,
        )

    if isinstance(expected, (date, datetime)) or isinstance(actual, (date, datetime)):
        return to_jsonable(expected) == to_jsonable(actual)

    return expected == actual


def rows_equal(
    expected: tuple[Any, ...] | list[Any],
    actual: tuple[Any, ...] | list[Any],
    *,
    abs_tolerance: float,
    rel_tolerance: float,
) -> bool:
    if len(expected) != len(actual):
        return False
    return all(
        values_equal(
            expected_value,
            actual_value,
            abs_tolerance=abs_tolerance,
            rel_tolerance=rel_tolerance,
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
    abs_tolerance: float,
    rel_tolerance: float,
) -> dict[str, Any] | None:
    for row_index, (expected_row, actual_row) in enumerate(zip(expected_rows, actual_rows)):
        for column_index, (expected_value, actual_value) in enumerate(zip(expected_row, actual_row)):
            if not values_equal(
                expected_value,
                actual_value,
                abs_tolerance=abs_tolerance,
                rel_tolerance=rel_tolerance,
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
    abs_tolerance: float,
    rel_tolerance: float,
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    unmatched_actual_indexes = set(range(len(actual_rows)))
    missing_rows = []

    for expected_row in expected_rows:
        matched_index = None
        for actual_index in sorted(unmatched_actual_indexes):
            if rows_equal(
                expected_row,
                actual_rows[actual_index],
                abs_tolerance=abs_tolerance,
                rel_tolerance=rel_tolerance,
            ):
                matched_index = actual_index
                break
        if matched_index is None:
            missing_rows.append(expected_row)
        else:
            unmatched_actual_indexes.remove(matched_index)

    unexpected_rows = [actual_rows[index] for index in sorted(unmatched_actual_indexes)]
    return missing_rows, unexpected_rows


def compare_query_results(
    expected: dict[str, Any],
    actual: dict[str, Any],
    question: dict[str, Any],
) -> dict[str, Any]:
    expected_columns = list(expected.get("columns", []))
    actual_columns = list(actual.get("columns", []))
    expected_rows = [tuple(row) for row in expected.get("rows", [])]
    actual_rows = [tuple(row) for row in actual.get("rows", [])]
    order_sensitive = bool(question.get("order_sensitive", False))
    compare_column_names = bool(question.get("compare_column_names", True))
    abs_tolerance = float(question.get("numeric_abs_tolerance", 0.0) or 0.0)
    rel_tolerance = float(question.get("numeric_rel_tolerance", 0.0) or 0.0)

    issues: list[str] = []
    summary: dict[str, Any] = {
        "passed": True,
        "issues": issues,
        "order_sensitive": order_sensitive,
        "compare_column_names": compare_column_names,
    }

    if len(expected_columns) != len(actual_columns):
        issues.append("shape mismatch")
        summary["shape_mismatch"] = {
            "expected_columns": len(expected_columns),
            "actual_columns": len(actual_columns),
            "expected_rows": len(expected_rows),
            "actual_rows": len(actual_rows),
        }

    if compare_column_names and expected_columns != actual_columns:
        issues.append("column mismatch")
        summary["column_mismatch"] = {
            "expected_columns": expected_columns,
            "actual_columns": actual_columns,
        }

    if len(expected_rows) != len(actual_rows):
        if "shape mismatch" not in issues:
            issues.append("shape mismatch")
        summary.setdefault("shape_mismatch", {})
        summary["shape_mismatch"].update(
            {
                "expected_rows": len(expected_rows),
                "actual_rows": len(actual_rows),
            }
        )

    comparable_shape = len(expected_columns) == len(actual_columns)
    if not comparable_shape:
        summary["passed"] = False
        return summary

    if order_sensitive:
        ordered_match = (
            len(expected_rows) == len(actual_rows)
            and all(
                rows_equal(
                    expected_row,
                    actual_row,
                    abs_tolerance=abs_tolerance,
                    rel_tolerance=rel_tolerance,
                )
                for expected_row, actual_row in zip(expected_rows, actual_rows)
            )
        )
        if not ordered_match:
            missing_rows, unexpected_rows = match_unordered_rows(
                expected_rows,
                actual_rows,
                abs_tolerance=abs_tolerance,
                rel_tolerance=rel_tolerance,
            )
            if not missing_rows and not unexpected_rows and len(expected_rows) == len(actual_rows):
                issues.append("order mismatch")
            else:
                issues.append("value mismatch")
                summary["value_mismatch"] = first_mismatch(
                    expected_rows,
                    actual_rows,
                    expected_columns,
                    abs_tolerance=abs_tolerance,
                    rel_tolerance=rel_tolerance,
                )
                summary["missing_rows"] = to_jsonable(missing_rows[:5])
                summary["unexpected_rows"] = to_jsonable(unexpected_rows[:5])
    else:
        missing_rows, unexpected_rows = match_unordered_rows(
            expected_rows,
            actual_rows,
            abs_tolerance=abs_tolerance,
            rel_tolerance=rel_tolerance,
        )
        if missing_rows or unexpected_rows:
            issues.append("missing rows" if missing_rows else "unexpected rows")
            summary["missing_rows"] = to_jsonable(missing_rows[:5])
            summary["unexpected_rows"] = to_jsonable(unexpected_rows[:5])

    unique_issues = []
    for issue in issues:
        if issue not in unique_issues:
            unique_issues.append(issue)
    summary["issues"] = unique_issues
    summary["passed"] = not unique_issues
    return summary


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
) -> dict[str, Any]:
    max_preview_rows = int(question.get("max_preview_rows", 20) or 20)
    agent_state = agent_state or {}
    status = "error" if failure_type.startswith("reference_") or failure_type in {"agent_error", "unexpected_error"} else "failed"
    return {
        "golden_run_id": batch_run_id,
        "agent_run_id": agent_state.get("run_id", ""),
        "question_id": question.get("question_id", ""),
        "title": question.get("title", ""),
        "question": question.get("question", ""),
        "status": status,
        "passed": False,
        "failure_type": failure_type,
        "failure_reason": failure_reason,
        "runtime_seconds": runtime_seconds,
        "expected_row_count": int((expected_result or {}).get("row_count", 0) or 0),
        "actual_row_count": int((actual_result or {}).get("row_count", 0) or 0),
        "generated_agent_sql": generated_sql,
        "reference_sql": reference_sql,
        "expected_output_preview": preview_result(expected_result or {}, max_preview_rows),
        "actual_output_preview": preview_result(actual_result or {}, max_preview_rows),
        "diff_summary": {"passed": False, "issues": [failure_type]},
        "validation_errors": [failure_reason] if "validation" in failure_type else [],
        "execution_errors": {failure_type: failure_reason} if "execution" in failure_type else {},
        "model_used": agent_state.get("model_used") or agent_state.get("selected_model", ""),
        "memory_templates_enabled": use_approved_memory,
        "backend": BACKEND_NAME,
        "timestamp": started_at_iso,
        "agent_result_status": agent_state.get("result_status", ""),
        "agent_trace_steps": agent_state.get("trace_steps", []),
    }


def evaluate_golden_question(
    question: dict[str, Any],
    *,
    batch_run_id: str,
    schema_context: str,
    use_approved_memory: bool,
    config: SQLAgentConfig | None = None,
) -> dict[str, Any]:
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
        )

    try:
        agent_state = run_sql_agent(
            question.get("question", ""),
            config=config,
            run_context="golden_test",
            use_approved_memory=use_approved_memory,
            enable_memory_candidate_generation=False,
            log_to_query_log=False,
            schema_loader=lambda: schema_context,
            sql_executor=execute_read_only_sql_full,
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
        )

    generated_sql = str(agent_state.get("generated_sql", ""))
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
            agent_state=agent_state,
            expected_result=expected_result,
            use_approved_memory=use_approved_memory,
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
            agent_state=agent_state,
            expected_result=expected_result,
            actual_result=actual_result,
            use_approved_memory=use_approved_memory,
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
        "model_used": agent_state.get("model_used") or agent_state.get("selected_model", ""),
        "memory_templates_enabled": use_approved_memory,
        "backend": BACKEND_NAME,
        "timestamp": started_at_iso,
        "agent_result_status": agent_state.get("result_status", ""),
        "agent_trace_steps": agent_state.get("trace_steps", []),
    }


def append_golden_result(result: dict[str, Any]) -> None:
    GOLDEN_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GOLDEN_RESULTS_PATH.open("a", encoding="utf-8") as file:
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
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
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
            )
        append_golden_result(result)
        results.append(result)

    return batch_run_id, results, build_result_summary(results)
