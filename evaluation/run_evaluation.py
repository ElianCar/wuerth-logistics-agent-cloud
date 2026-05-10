from pathlib import Path
import csv
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.llm_client import generate_sql
from app.prompt_builder import build_sql_generation_prompt
from app.query_executor import execute_sql, run_explain
from app.schema import get_schema_text
from app.semantic_layer import get_semantic_layer_text
from app.sql_validator import extract_used_tables, validate_sql


GOLDEN_QUESTIONS_PATH = PROJECT_ROOT / "evaluation" / "golden_questions.yaml"
EVALUATION_RESULTS_PATH = PROJECT_ROOT / "evaluation" / "evaluation_results.csv"


def load_golden_questions() -> list[dict]:
    with GOLDEN_QUESTIONS_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or []


def contains_all_keywords(sql: str, expected_keywords: list[str]) -> bool:
    normalized_sql = " ".join(sql.upper().split())
    return all(keyword.upper() in normalized_sql for keyword in expected_keywords)


def contains_all_tables(sql: str, expected_tables: list[str]) -> bool:
    used_tables = set(extract_used_tables(sql))
    return all(table in used_tables for table in expected_tables)


def evaluate_question(test_case: dict, schema_text: str, semantic_layer_text: str) -> dict:
    question = test_case["question"]
    generated_sql = ""
    row_count = 0
    validation_ok = False
    explain_ok = False
    execution_ok = False
    error_message = ""

    try:
        prompt = build_sql_generation_prompt(
            question=question,
            schema_text=schema_text,
            semantic_layer_text=semantic_layer_text,
        )
        raw_sql = generate_sql(prompt)
        validation = validate_sql(raw_sql)
        generated_sql = validation.sql
        validation_ok = validation.is_valid

        if not validation_ok:
            error_message = validation.message
        else:
            try:
                run_explain(generated_sql)
                explain_ok = True
            except RuntimeError as error:
                error_message = str(error)

            if explain_ok:
                try:
                    _columns, rows = execute_sql(generated_sql)
                    row_count = len(rows)
                    execution_ok = True
                except RuntimeError as error:
                    error_message = str(error)
    except Exception as error:
        error_message = str(error)

    expected_tables_ok = contains_all_tables(generated_sql, test_case.get("expected_tables", []))
    expected_keywords_ok = contains_all_keywords(generated_sql, test_case.get("expected_sql_keywords", []))
    overall_ok = (
        expected_tables_ok
        and expected_keywords_ok
        and validation_ok
        and explain_ok
        and execution_ok
    )

    return {
        "id": test_case["id"],
        "question": question,
        "generated_sql": generated_sql,
        "used_tables": ", ".join(extract_used_tables(generated_sql)),
        "expected_tables_ok": expected_tables_ok,
        "expected_keywords_ok": expected_keywords_ok,
        "validation_ok": validation_ok,
        "explain_ok": explain_ok,
        "execution_ok": execution_ok,
        "row_count": row_count,
        "overall_status": "passed" if overall_ok else "failed",
        "error_message": error_message,
    }


def save_results(results: list[dict]) -> None:
    EVALUATION_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "question",
        "generated_sql",
        "used_tables",
        "expected_tables_ok",
        "expected_keywords_ok",
        "validation_ok",
        "explain_ok",
        "execution_ok",
        "row_count",
        "overall_status",
        "error_message",
    ]

    with EVALUATION_RESULTS_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


def print_summary_table(results: list[dict]) -> None:
    table_rows = [
        [
            result["id"],
            result["question"],
            result["expected_tables_ok"],
            result["expected_keywords_ok"],
            result["validation_ok"],
            result["explain_ok"],
            result["execution_ok"],
            result["row_count"],
            result["overall_status"],
        ]
        for result in results
    ]
    headers = [
        "id",
        "question",
        "expected_tables_ok",
        "expected_keywords_ok",
        "validation_ok",
        "explain_ok",
        "execution_ok",
        "row_count",
        "overall_status",
    ]

    try:
        from tabulate import tabulate

        print(tabulate(table_rows, headers=headers, tablefmt="github"))
    except ImportError:
        print(",".join(headers))
        for row in table_rows:
            print(",".join(str(value) for value in row))


def main() -> None:
    test_cases = load_golden_questions()
    if not test_cases:
        raise RuntimeError(f"No golden questions found in {GOLDEN_QUESTIONS_PATH}")

    schema_text = get_schema_text()
    semantic_layer_text = get_semantic_layer_text()

    results = []
    for test_case in test_cases:
        print(f"Evaluating {test_case['id']}: {test_case['question']}")
        results.append(evaluate_question(test_case, schema_text, semantic_layer_text))

    save_results(results)
    print()
    print_summary_table(results)

    total_questions = len(results)
    passed_questions = sum(1 for result in results if result["overall_status"] == "passed")
    failed_questions = total_questions - passed_questions
    pass_rate = (passed_questions / total_questions) * 100 if total_questions else 0

    print()
    print(f"Total questions: {total_questions}")
    print(f"Passed questions: {passed_questions}")
    print(f"Failed questions: {failed_questions}")
    print(f"Pass rate: {pass_rate:.1f}%")
    print(f"Saved results to: {EVALUATION_RESULTS_PATH}")


if __name__ == "__main__":
    main()
