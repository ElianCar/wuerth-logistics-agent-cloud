from __future__ import annotations

import unittest

from src.agent.memory_template_schema import (
    PROMPT_GUIDANCE_FIELDS,
    RETRIEVAL_FIELDS,
    is_retrievable_template,
    validate_template,
)


def valid_template(**overrides: object) -> dict[str, object]:
    template: dict[str, object] = {
        "id": "revenue_by_shipping_point",
        "scenario": "wuerth_local",
        "status": "approved",
        "is_active": True,
        "title": "Revenue by shipping point",
        "intent": "revenue_by_dimension",
        "trigger_phrases": ["Umsatz pro Versandstelle"],
        "searchable_summary": "Revenue grouped by shipping point.",
        "searchable_terms": ["revenue", "shipping_point"],
        "synonyms": {"umsatz": "revenue"},
        "required_tables": ["wuerth.shipments"],
        "required_columns": ["shipping_point", "revenue"],
        "business_rules": ["Use approved revenue columns only."],
        "sql_pattern": "Aggregate one metric by one dimension.",
        "do_not_use_when": ["Revenue is unsupported."],
        "validation_checks": ["SELECT only."],
        "source_question": "Umsatz pro Versandstelle",
        "source_sql": "",
        "approved_by": "manual_review",
        "approved_at": "2026-06-05T00:00:00",
        "version": 1,
    }
    template.update(overrides)
    return template


class MemoryTemplateSchemaTests(unittest.TestCase):
    def test_valid_approved_template_passes_validation(self) -> None:
        result = validate_template(valid_template(), expected_scenario="wuerth_local")

        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])
        self.assertTrue(
            is_retrievable_template(result.template, expected_scenario="wuerth_local")
        )

    def test_missing_id_fails_validation(self) -> None:
        template = valid_template()
        del template["id"]

        result = validate_template(template, expected_scenario="wuerth_local")

        self.assertFalse(result.is_valid)
        self.assertIn("required field missing: id.", result.errors)

    def test_wrong_scenario_fails_validation(self) -> None:
        result = validate_template(valid_template(scenario="demo"), expected_scenario="wuerth_local")

        self.assertFalse(result.is_valid)
        self.assertIn("scenario must match the scenario directory 'wuerth_local'.", result.errors)

    def test_pending_status_is_valid_file_but_not_retrievable(self) -> None:
        result = validate_template(valid_template(status="pending_review"), expected_scenario="wuerth_local")

        self.assertTrue(result.is_valid)
        self.assertFalse(
            is_retrievable_template(result.template, expected_scenario="wuerth_local")
        )

    def test_inactive_template_is_valid_file_but_not_retrievable(self) -> None:
        result = validate_template(valid_template(is_active=False), expected_scenario="wuerth_local")

        self.assertTrue(result.is_valid)
        self.assertFalse(
            is_retrievable_template(result.template, expected_scenario="wuerth_local")
        )

    def test_required_list_fields_must_be_lists(self) -> None:
        result = validate_template(valid_template(required_tables="wuerth.shipments"), expected_scenario="wuerth_local")

        self.assertFalse(result.is_valid)
        self.assertIn("required_tables must be a list.", result.errors)

    def test_version_must_be_integer(self) -> None:
        result = validate_template(valid_template(version="1"), expected_scenario="wuerth_local")

        self.assertFalse(result.is_valid)
        self.assertIn("version must be an integer.", result.errors)

    def test_unknown_fields_are_preserved_and_reported(self) -> None:
        result = validate_template(valid_template(owner_team="analytics"), expected_scenario="wuerth_local")

        self.assertTrue(result.is_valid)
        self.assertIn("owner_team", result.unknown_fields)
        self.assertEqual(result.template["owner_team"], "analytics")

    def test_retrieval_and_guidance_fields_are_separated(self) -> None:
        self.assertIn("searchable_summary", RETRIEVAL_FIELDS)
        self.assertIn("source_sql", PROMPT_GUIDANCE_FIELDS)
        self.assertNotIn("source_sql", RETRIEVAL_FIELDS)
        self.assertNotIn("business_rules", RETRIEVAL_FIELDS)


if __name__ == "__main__":
    unittest.main()
