from __future__ import annotations

from pathlib import Path
import argparse
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.golden_test_runner import load_golden_questions, run_golden_tests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run integrated Golden Test Mode from the CLI.")
    parser.add_argument(
        "question_ids",
        nargs="*",
        help="Optional question IDs such as Q01 Q02 or W01 W02. Defaults to all questions for the active scenario.",
    )
    parser.add_argument(
        "--no-approved-memory",
        action="store_true",
        help="Disable approved memory/templates during the run.",
    )
    parser.add_argument(
        "--use-orchestrator",
        action="store_true",
        help="Deprecated compatibility flag. Orchestrator is now the default Golden runtime.",
    )
    parser.add_argument(
        "--runtime-mode",
        choices=["orchestrator", "direct_sql_agent"],
        default="orchestrator",
        help="Golden runtime path. Defaults to the real chat Orchestrator path.",
    )
    parser.add_argument(
        "--direct-sql-agent",
        action="store_true",
        help="Debug only: bypass router/orchestrator and run the SQL agent directly.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    questions = load_golden_questions()
    question_ids = args.question_ids or [question["question_id"] for question in questions]
    runtime_mode = "direct_sql_agent" if args.direct_sql_agent else args.runtime_mode
    if args.use_orchestrator:
        runtime_mode = "orchestrator"
    batch_run_id, results, summary = run_golden_tests(
        question_ids,
        use_approved_memory=not args.no_approved_memory,
        runtime_mode=runtime_mode,
    )

    print(f"Golden run: {batch_run_id}")
    for result in results:
        status = result.get("status", "")
        reason = result.get("failure_reason", "")
        suffix = f" - {reason}" if reason else ""
        print(f"{result.get('question_id', '')}: {status}{suffix}")

    print()
    print(f"Total tests run: {summary['total_tests_run']}")
    print(f"Passed: {summary['passed']}")
    print(f"Output mismatch: {summary['failed_output_mismatch']}")
    print(f"SQL validation failures: {summary['failed_sql_validation']}")
    print(f"Execution errors: {summary['failed_execution_error']}")
    print(f"Pass rate: {summary['pass_rate'] * 100:.1f}%")
    print(f"Average runtime: {summary['average_runtime']:.2f}s")


if __name__ == "__main__":
    main()
