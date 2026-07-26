from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.golden_test_runner import (
    build_golden_report_markdown,
    golden_questions_path,
    run_golden_report,
    save_golden_report,
)
from src.config.scenarios import get_active_scenario


DEFAULT_QUESTIONS = "Q01,Q02,Q03,Q04"

CONDITION_FLAGS = {
    "off": False,
    "on": True,
    "without_template": False,
    "with_template": True,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run golden questions repeatedly, once without and once with approved memory "
            "templates, and write a comparison report (CSV + Markdown)."
        )
    )
    parser.add_argument(
        "--questions",
        default=DEFAULT_QUESTIONS,
        help="Comma-separated golden question ids. Default: Q01,Q02,Q03,Q04.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=30,
        help="How many times to run each question per condition. Default: 30.",
    )
    parser.add_argument(
        "--conditions",
        default="off,on",
        help="Comma-separated conditions (off=no templates, on=templates). Default: off,on.",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="Output directory. Default: evaluation/<scenario>/reports.",
    )
    return parser.parse_args()


def resolve_conditions(raw: str) -> tuple[bool, ...]:
    conditions: list[bool] = []
    for token in raw.split(","):
        key = token.strip().lower()
        if not key:
            continue
        if key not in CONDITION_FLAGS:
            raise SystemExit(f"Unknown condition '{token}'. Use off, on, or both (off,on).")
        value = CONDITION_FLAGS[key]
        if value not in conditions:
            conditions.append(value)
    if not conditions:
        raise SystemExit("No valid conditions provided.")
    return tuple(conditions)


def main() -> None:
    args = parse_args()
    scenario = get_active_scenario()
    questions_path = golden_questions_path()
    if not questions_path.exists():
        raise SystemExit(
            f"No golden_questions.yaml found for active scenario '{scenario.scenario_id}' "
            f"at {questions_path}. Set DATA_SCENARIO to the intended scenario and ensure the "
            f"golden definition exists."
        )

    question_ids = [token.strip().upper() for token in args.questions.split(",") if token.strip()]
    conditions = resolve_conditions(args.conditions)

    total = len(conditions) * args.repetitions * len(question_ids)
    print(
        f"Running golden report for scenario '{scenario.scenario_id}': "
        f"{len(question_ids)} questions x {args.repetitions} repetitions x {len(conditions)} "
        f"conditions = {total} agent runs."
    )

    def _progress(step: int, steps: int, result: dict) -> None:
        status = "OK" if result.get("passed") else str(result.get("failure_type") or "fail")
        print(
            f"  [{step}/{steps}] {result.get('question_id', '')} "
            f"{result.get('condition_label', '')}: {status} "
            f"chart={result.get('chart_type', 'none')}"
        )

    report = run_golden_report(
        question_ids,
        repetitions=args.repetitions,
        conditions=conditions,
        progress_callback=_progress,
    )

    out_dir = Path(args.out_dir) if args.out_dir else None
    paths = save_golden_report(report, out_dir)

    print("")
    print(f"Raw runs:  {paths['csv']}")
    print(f"Summary:   {paths['markdown']}")
    print("")
    print(build_golden_report_markdown(report))


if __name__ == "__main__":
    main()
