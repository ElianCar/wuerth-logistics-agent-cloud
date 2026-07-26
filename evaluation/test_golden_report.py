from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src.agent.golden_test_runner as runner


QUESTION_MAP = {
    "Q01": {"question_id": "Q01", "title": "Count question"},
    "Q02": {"question_id": "Q02", "title": "Ranking question"},
}


def make_fake_evaluate():
    """Deterministic fake: with-template always passes, without-template passes 50%.

    Q02 renders faceted_bar on a pass and bar otherwise; Q01 renders no chart.
    """
    calls: dict[tuple[str, bool], int] = {}

    def fake_evaluate(question, *, batch_run_id, schema_context, use_approved_memory, config=None, runtime_mode=None):
        qid = question["question_id"]
        key = (qid, bool(use_approved_memory))
        index = calls.get(key, 0)
        calls[key] = index + 1

        passed = True if use_approved_memory else (index % 2 == 0)
        if qid == "Q02":
            chart_type = "faceted_bar" if passed else "bar"
        else:
            chart_type = "none"
        return {
            "question_id": qid,
            "title": question.get("title", ""),
            "passed": passed,
            "status": "passed" if passed else "failed",
            "failure_type": "" if passed else "output_mismatch",
            "chart_rendered": chart_type != "none",
            "chart_type": chart_type,
            "runtime_seconds": 1.0,
        }

    return fake_evaluate


class GoldenReportTests(unittest.TestCase):
    def run_report(self, repetitions=4, **kwargs):
        with patch.object(runner, "evaluate_golden_question", make_fake_evaluate()), patch.object(
            runner, "load_golden_question_map", return_value=QUESTION_MAP
        ), patch.object(runner, "load_schema_context", return_value=""), patch.object(
            runner, "active_backend_name", return_value="databricks"
        ), patch.object(
            runner, "get_active_scenario", return_value=SimpleNamespace(scenario_id="databricks")
        ):
            return runner.run_golden_report(
                ["Q01", "Q02"], repetitions=repetitions, conditions=(False, True), **kwargs
            )

    def aggregate_for(self, report, question_id, condition):
        for row in report["aggregates"]:
            if row["question_id"] == question_id and row["condition_memory"] is condition:
                return row
        raise AssertionError(f"no aggregate for {question_id}/{condition}")

    def test_raw_run_count_matches_matrix(self) -> None:
        report = self.run_report()
        # 2 questions x 4 repetitions x 2 conditions
        self.assertEqual(len(report["raw_runs"]), 16)
        self.assertEqual(len(report["aggregates"]), 4)

    def test_with_template_improves_sql_pass_rate(self) -> None:
        report = self.run_report()
        q02_off = self.aggregate_for(report, "Q02", False)
        q02_on = self.aggregate_for(report, "Q02", True)
        self.assertEqual(q02_off["sql_correct_pct"], 50.0)
        self.assertEqual(q02_on["sql_correct_pct"], 100.0)
        self.assertEqual(q02_on["sql_correct"], 4)
        self.assertEqual(q02_on["runs"], 4)

    def test_chart_type_distribution_recorded(self) -> None:
        report = self.run_report()
        q02_on = self.aggregate_for(report, "Q02", True)
        self.assertEqual(q02_on["chart_type_distribution"], {"faceted_bar": 4})
        self.assertEqual(q02_on["chart_rendered_pct"], 100.0)

        q02_off = self.aggregate_for(report, "Q02", False)
        self.assertEqual(q02_off["chart_type_distribution"], {"faceted_bar": 2, "bar": 2})

        q01_on = self.aggregate_for(report, "Q01", True)
        self.assertEqual(q01_on["chart_type_distribution"], {"none": 4})
        self.assertEqual(q01_on["chart_rendered_pct"], 0.0)

    def test_condition_labels_present(self) -> None:
        report = self.run_report()
        labels = {row["condition_label"] for row in report["aggregates"]}
        self.assertEqual(labels, {"without_template", "with_template"})

    def test_repetitions_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            self.run_report(repetitions=0)

    def test_content_correct_tracked_independently_of_sql_correct(self) -> None:
        # content_correct (loose, order-agnostic) can be True even when the strict
        # positional "passed" check fails — e.g. the Q02 reordered-columns case.
        def fake_evaluate(question, *, batch_run_id, schema_context, use_approved_memory, config=None, runtime_mode=None):
            return {
                "question_id": question["question_id"],
                "title": question.get("title", ""),
                "passed": False,
                "content_correct": True,
                "status": "failed",
                "failure_type": "output_mismatch",
                "chart_rendered": False,
                "chart_type": "none",
                "runtime_seconds": 1.0,
            }

        with patch.object(runner, "evaluate_golden_question", fake_evaluate), patch.object(
            runner, "load_golden_question_map", return_value=QUESTION_MAP
        ), patch.object(runner, "load_schema_context", return_value=""), patch.object(
            runner, "active_backend_name", return_value="databricks"
        ), patch.object(
            runner, "get_active_scenario", return_value=SimpleNamespace(scenario_id="databricks")
        ):
            report = runner.run_golden_report(["Q02"], repetitions=3, conditions=(True,))

        q02_on = self.aggregate_for(report, "Q02", True)
        self.assertEqual(q02_on["sql_correct_pct"], 0.0)
        self.assertEqual(q02_on["content_correct_pct"], 100.0)
        self.assertEqual(q02_on["content_correct"], 3)


SAMPLE_REPORT = {
    "batch_run_id": "golden_report_abc",
    "scenario": "databricks",
    "backend": "databricks",
    "repetitions": 2,
    "raw_runs": [
        {
            "question_id": "Q01",
            "condition_label": "without_template",
            "repetition": 1,
            "passed": True,
            "content_correct": True,
            "status": "passed",
            "chart_rendered": False,
            "chart_type": "none",
            "runtime_seconds": 1.5,
            "generated_agent_sql": "SELECT 1",
            "ignored_extra_field": "dropped",
        },
        {
            "question_id": "Q01",
            "condition_label": "with_template",
            "repetition": 1,
            "passed": False,
            "content_correct": True,
            "status": "failed",
            "failure_type": "output_mismatch",
            "chart_rendered": True,
            "chart_type": "bar",
            "runtime_seconds": 2.0,
        },
    ],
    "aggregates": [
        {
            "question_id": "Q01",
            "title": "Zähltest",
            "condition_memory": False,
            "condition_label": "without_template",
            "runs": 2,
            "sql_correct": 1,
            "sql_correct_pct": 50.0,
            "content_correct": 2,
            "content_correct_pct": 100.0,
            "chart_rendered": 0,
            "chart_rendered_pct": 0.0,
            "chart_type_distribution": {"none": 2},
            "average_runtime": 1.5,
        },
        {
            "question_id": "Q01",
            "title": "Zähltest",
            "condition_memory": True,
            "condition_label": "with_template",
            "runs": 2,
            "sql_correct": 2,
            "sql_correct_pct": 100.0,
            "content_correct": 2,
            "content_correct_pct": 100.0,
            "chart_rendered": 1,
            "chart_rendered_pct": 50.0,
            "chart_type_distribution": {"bar": 1, "none": 1},
            "average_runtime": 1.2,
        },
    ],
}


class GoldenReportOutputTests(unittest.TestCase):
    def test_csv_has_header_and_one_row_per_run(self) -> None:
        csv_text = runner.build_golden_report_csv(SAMPLE_REPORT["raw_runs"])
        lines = [line for line in csv_text.splitlines() if line.strip()]

        self.assertEqual(len(lines), 3)  # header + 2 runs
        self.assertEqual(lines[0].split(","), list(runner.GOLDEN_REPORT_CSV_FIELDS))
        self.assertIn("without_template", lines[1])
        self.assertNotIn("dropped", csv_text)  # extra fields are not written

    def test_csv_tolerates_missing_fields(self) -> None:
        csv_text = runner.build_golden_report_csv([{"question_id": "Q09"}])

        self.assertIn("Q09", csv_text)

    def test_markdown_contains_both_conditions_with_percentages(self) -> None:
        markdown = runner.build_golden_report_markdown(SAMPLE_REPORT)

        self.assertIn("# Golden-Report — databricks", markdown)
        self.assertIn("## Q01 — Zähltest", markdown)
        self.assertIn(
            "| ohne Template | 50.0% (1/2) | 100.0% (2/2) | 0.0% (0/2) | none: 2 | 1.50s |", markdown
        )
        self.assertIn(
            "| mit Template | 100.0% (2/2) | 100.0% (2/2) | 50.0% (1/2) | bar: 1, none: 1 | 1.20s |", markdown
        )

    def test_markdown_handles_empty_chart_distribution(self) -> None:
        report = {**SAMPLE_REPORT, "aggregates": [{**SAMPLE_REPORT["aggregates"][0], "chart_type_distribution": {}}]}

        self.assertIn("—", runner.build_golden_report_markdown(report))


if __name__ == "__main__":
    unittest.main()
