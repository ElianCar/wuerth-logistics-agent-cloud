from __future__ import annotations

import unittest

from src.agent.golden_test_runner import compare_query_results


def result(columns: list[str], rows: list[tuple]) -> dict:
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


class GoldenResultComparisonTests(unittest.TestCase):
    def test_same_values_with_different_column_names_pass(self) -> None:
        expected = result(["customer", "revenue"], [("A", 10)])
        actual = result(["name", "total"], [("A", 10)])

        comparison = compare_query_results(expected, actual, {})

        self.assertTrue(comparison["passed"])

    def test_same_rows_in_different_order_pass_by_default(self) -> None:
        expected = result(["id"], [(1,), (2,), (3,)])
        actual = result(["id"], [(3,), (1,), (2,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertTrue(comparison["passed"])

    def test_legacy_question_flags_do_not_override_new_defaults(self) -> None:
        expected = result(["id"], [(1,), (2,), (3,)])
        actual = result(["renamed"], [(3,), (1,), (2,)])
        question = {"order_sensitive": True, "compare_column_names": True}

        comparison = compare_query_results(expected, actual, question)

        self.assertTrue(comparison["passed"])

    def test_same_rows_in_different_order_fail_when_order_required(self) -> None:
        expected = result(["id"], [(1,), (2,), (3,)])
        actual = result(["id"], [(3,), (1,), (2,)])
        question = {"compare": {"ignore_row_order": False}}

        comparison = compare_query_results(expected, actual, question)

        self.assertFalse(comparison["passed"])
        self.assertIn("row values differ with order enforced", comparison["issues"])

    def test_missing_row_fails(self) -> None:
        expected = result(["id"], [(1,), (2,)])
        actual = result(["id"], [(1,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertIn("row count mismatch", comparison["issues"])
        self.assertIn("row values differ ignoring order", comparison["issues"])

    def test_extra_row_fails(self) -> None:
        expected = result(["id"], [(1,)])
        actual = result(["id"], [(1,), (2,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertIn("row count mismatch", comparison["issues"])
        self.assertIn("row values differ ignoring order", comparison["issues"])

    def test_duplicate_row_count_mismatch_fails(self) -> None:
        expected = result(["id"], [(1,), (1,), (2,)])
        actual = result(["id"], [(1,), (2,), (2,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertIn("duplicate row count mismatch", comparison["issues"])

    def test_duplicate_numeric_rows_within_tolerance_pass(self) -> None:
        expected = result(["amount"], [(1.0,), (1.0,)])
        actual = result(["amount"], [(1.0000004,), (1.0000004,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertTrue(comparison["passed"])

    def test_numeric_values_within_tolerance_pass(self) -> None:
        expected = result(["value"], [(1.0000001,), ("2.0000001",)])
        actual = result(["value"], [(1.0000002,), (2.0000002,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertTrue(comparison["passed"])

    def test_numeric_values_outside_tolerance_fail(self) -> None:
        expected = result(["value"], [(1.0,)])
        actual = result(["value"], [(1.01,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertIn("numeric value outside tolerance", comparison["issues"])

    def test_more_than_50_rows_are_compared_fully(self) -> None:
        expected_rows = [(index,) for index in range(60)]
        actual_rows = [(index,) for index in range(50)]
        expected = result(["id"], expected_rows)
        actual = result(["id"], actual_rows)

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertIn("row count mismatch", comparison["issues"])
        self.assertEqual(comparison["row_count_mismatch"]["expected_rows"], 60)
        self.assertEqual(comparison["row_count_mismatch"]["actual_rows"], 50)

    def test_column_count_mismatch_fails(self) -> None:
        expected = result(["id", "name"], [(1, "A")])
        actual = result(["id"], [(1,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertIn("column count mismatch", comparison["issues"])

    def test_null_values_compare_correctly(self) -> None:
        expected = result(["value"], [(None,), (float("nan"),)])
        actual = result(["value"], [(None,), (None,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertTrue(comparison["passed"])

    def test_string_values_are_trimmed_only(self) -> None:
        expected = result(["name"], [("  Supplier A ",)])
        actual = result(["name"], [("Supplier A",)])

        comparison = compare_query_results(expected, actual, {})

        self.assertTrue(comparison["passed"])


if __name__ == "__main__":
    unittest.main()
