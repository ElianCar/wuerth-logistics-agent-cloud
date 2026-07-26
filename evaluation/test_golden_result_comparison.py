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

    def test_identical_result_is_both_passed_and_content_correct(self) -> None:
        expected = result(["id", "name"], [(1, "A")])
        actual = result(["id", "name"], [(1, "A")])

        comparison = compare_query_results(expected, actual, {})

        self.assertTrue(comparison["passed"])
        self.assertTrue(comparison["content_correct"])

    def test_reordered_columns_fail_strict_but_are_content_correct(self) -> None:
        # Mirrors the observed Q02 case: the agent leads with "plant" instead of
        # "metric" — same values, different column order. Strict positional
        # comparison must still fail (it does not realign columns), but the
        # looser content check should recognize the values as equivalent.
        expected = result(
            ["metric", "plant", "product", "value", "rank"],
            [("Lieferpositionen", "1012", "ABC", 5.0, 1)],
        )
        actual = result(
            ["plant", "metrik", "product", "wert", "rang"],
            [("1012", "Lieferpositionen", "ABC", 5.0, 1)],
        )

        comparison = compare_query_results(expected, actual, {"compare": {"numeric_tolerance": 0.01}})

        self.assertFalse(comparison["passed"])
        self.assertIn("value mismatch", comparison["issues"])
        self.assertTrue(comparison["content_correct"])

    def test_genuinely_wrong_values_fail_both_metrics(self) -> None:
        expected = result(["a", "b"], [(1, 2)])
        actual = result(["a", "b"], [(9, 9)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertFalse(comparison["content_correct"])

    def test_column_count_mismatch_is_not_content_correct(self) -> None:
        expected = result(["id", "name"], [(1, "A")])
        actual = result(["id"], [(1,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertFalse(comparison["content_correct"])

    def test_truncated_but_correct_rows_are_content_correct(self) -> None:
        # The agent returned fewer rows than the reference (e.g. it appended LIMIT),
        # but every row it did return is genuinely in the reference.
        expected = result(["id"], [(1,), (2,)])
        actual = result(["id"], [(1,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertTrue(comparison["content_correct"])

    def test_truncated_with_reordered_columns_is_content_correct(self) -> None:
        # Mirrors the observed Q02 case: agent truncates to fewer rows AND leads with a
        # different column than the reference.
        expected = result(
            ["metric", "plant", "value"],
            [("Lieferpositionen", "1012", 5.0), ("Umsatz", "1012", 99.0), ("Umsatz", "1013", 7.0)],
        )
        actual = result(["plant", "metrik", "wert"], [("1012", "Lieferpositionen", 5.0)])

        comparison = compare_query_results(expected, actual, {"compare": {"numeric_tolerance": 0.01}})

        self.assertFalse(comparison["passed"])
        self.assertTrue(comparison["content_correct"])

    def test_truncated_with_one_wrong_row_is_not_content_correct(self) -> None:
        expected = result(["id"], [(1,), (2,), (3,)])
        actual = result(["id"], [(1,), (99,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertFalse(comparison["content_correct"])

    def test_empty_actual_result_is_not_content_correct(self) -> None:
        expected = result(["id"], [(1,), (2,)])
        actual = result(["id"], [])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertFalse(comparison["content_correct"])

    def test_more_rows_than_reference_is_not_content_correct(self) -> None:
        expected = result(["id"], [(1,)])
        actual = result(["id"], [(1,), (2,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["passed"])
        self.assertFalse(comparison["content_correct"])

    def test_duplicate_actual_rows_need_matching_reference_duplicates(self) -> None:
        expected = result(["id"], [(1,), (2,)])
        actual = result(["id"], [(1,), (1,)])

        comparison = compare_query_results(expected, actual, {})

        self.assertFalse(comparison["content_correct"])

    def test_multiset_match_does_not_reuse_a_value_twice(self) -> None:
        # Expected row has two distinct values (1, 2). An actual row of (1, 1) must
        # not be treated as a multiset match just because "1" appears in both.
        from src.agent.golden_test_runner import row_values_match_as_multiset

        self.assertFalse(
            row_values_match_as_multiset((1, 2), (1, 1), numeric_tolerance=0.01)
        )
        self.assertTrue(
            row_values_match_as_multiset((1, 2), (2, 1), numeric_tolerance=0.01)
        )


if __name__ == "__main__":
    unittest.main()
