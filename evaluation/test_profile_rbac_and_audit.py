from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from src.agent.access_control import TemplateAction, can
from src.agent.memory_index_builder import write_master_index
from src.agent.memory_lifecycle import (
    approve_candidate_to_vsm,
    deactivate_approved_template,
    reactivate_approved_template,
    write_approved_template,
)
from src.agent.memory_store import (
    create_candidate_from_run,
    load_candidates,
    mark_candidate_needs_changes,
    reject_candidate,
    save_candidates,
)
from src.agent.profiles import DEMO_PROFILES, PermissionRole, ResponseProfile
from src.agent.response_profiles import display_policy_for_response_profile
from src.config.scenarios import SCENARIOS, reset_active_scenario_id, set_active_scenario_id


VIEWER = {"actor_id": "management_user", "actor_role": "viewer"}
CONTRIBUTOR = {"actor_id": "business_analyst", "actor_role": "contributor"}
REVIEWER = {"actor_id": "template_reviewer", "actor_role": "reviewer"}
ADMIN = {"actor_id": "admin_developer", "actor_role": "admin"}


def run_record(run_id: str = "run_test_1") -> dict[str, object]:
    return {
        "run_id": run_id,
        "question": "Revenue by customer",
        "user_question": "Revenue by customer",
        "answer": "answer",
        "final_answer": "answer",
        "generated_sql": "SELECT c_custkey, SUM(l_extendedprice) FROM customer GROUP BY c_custkey",
        "final_sql": "SELECT c_custkey, SUM(l_extendedprice) FROM customer GROUP BY c_custkey",
        "validation_success": True,
        "execution_success": True,
        "source_tables": ["customer"],
        "row_count": 3,
        "run_context": "chat",
    }


def proposed_template(
    *,
    scenario: str,
    question: str = "Revenue by customer",
    sql: str = "SELECT 1",
    tables: list[str] | None = None,
) -> dict[str, object]:
    table_list = tables or ["customer"]
    return {
        "scenario": scenario,
        "dataset_id": f"{scenario}_dataset",
        "intent": question,
        "trigger_phrases": [question],
        "required_tables": table_list,
        "metric_definitions": {},
        "join_logic": [],
        "sql_skeleton": sql,
        "notes": "Reviewed template guidance.",
    }


def candidate_record(
    *,
    scenario: str,
    candidate_id: str,
    status: str = "pending_review",
) -> dict[str, object]:
    template = proposed_template(scenario=scenario)
    return {
        "candidate_id": candidate_id,
        "scenario": scenario,
        "dataset_id": f"{scenario}_dataset",
        "run_id": f"run_{candidate_id}",
        "status": status,
        "is_active": False,
        "candidate_type": "solution_template",
        "created_at": "2026-06-05T00:00:00",
        "updated_at": "2026-06-05T00:00:00",
        "original_question": "Revenue by customer",
        "generated_answer": "answer",
        "generated_sql": "SELECT 1",
        "final_sql": "SELECT 1",
        "validation_success": True,
        "execution_success": True,
        "source_tables": ["customer"],
        "row_count": 1,
        "feedback": {},
        "review": {
            "reviewed_by": None,
            "reviewed_at": None,
            "review_comment": None,
            "rejection_reason": None,
            "approved_template_id": None,
        },
        "proposed_template": template,
    }


def approved_template(
    *,
    scenario: str,
    template_id: str,
    title: str = "Revenue by customer",
    status: str = "approved",
    is_active: bool = True,
) -> dict[str, object]:
    return {
        "id": template_id,
        "scenario": scenario,
        "status": status,
        "is_active": is_active,
        "title": title,
        "intent": title.lower().replace(" ", "_"),
        "trigger_phrases": [title],
        "searchable_summary": f"{title} memory template.",
        "searchable_terms": ["revenue", "customer"],
        "synonyms": {},
        "required_tables": ["customer"],
        "required_columns": [],
        "business_rules": ["Use as prompt guidance only."],
        "sql_pattern": "Aggregate requested metric by requested dimension.",
        "do_not_use_when": ["Different scenario or unrelated metric."],
        "validation_checks": ["Final SQL must pass normal validation."],
        "source_question": title,
        "source_sql": "SELECT 1",
        "approved_by": "manual_review",
        "approved_at": "2026-06-05T00:00:00",
        "version": 1,
    }


class ScenarioPatch:
    def __init__(self, test_case: unittest.TestCase, scenario: str, memory_dir: Path) -> None:
        self.scenario = scenario
        self.original = SCENARIOS[scenario]
        SCENARIOS[scenario] = replace(self.original, memory_dir=memory_dir)
        set_active_scenario_id(scenario)
        test_case.addCleanup(self.cleanup)

    def cleanup(self) -> None:
        SCENARIOS[self.scenario] = self.original
        reset_active_scenario_id()


def read_audit_rows(log_dir: Path) -> list[dict[str, str]]:
    with (log_dir / "memory_audit_log.csv").open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


class ProfileRbacAndAuditTests(unittest.TestCase):
    def test_demo_profiles_have_separate_permission_and_response_profiles(self) -> None:
        self.assertEqual(DEMO_PROFILES["management_user"].permission_role, PermissionRole.VIEWER)
        self.assertEqual(DEMO_PROFILES["management_user"].response_profile, ResponseProfile.MANAGEMENT)
        self.assertEqual(DEMO_PROFILES["business_analyst"].permission_role, PermissionRole.CONTRIBUTOR)
        self.assertEqual(DEMO_PROFILES["business_analyst"].response_profile, ResponseProfile.ANALYST)
        self.assertEqual(DEMO_PROFILES["template_reviewer"].permission_role, PermissionRole.REVIEWER)
        self.assertEqual(DEMO_PROFILES["template_reviewer"].response_profile, ResponseProfile.ANALYST)
        self.assertEqual(DEMO_PROFILES["admin_developer"].permission_role, PermissionRole.ADMIN)
        self.assertEqual(DEMO_PROFILES["admin_developer"].response_profile, ResponseProfile.TECHNICAL)

    def test_role_permissions_match_demo_contract(self) -> None:
        self.assertFalse(can("viewer", TemplateAction.CREATE_CANDIDATE))
        self.assertTrue(can("contributor", TemplateAction.CREATE_CANDIDATE))
        self.assertFalse(can("contributor", TemplateAction.APPROVE_CANDIDATE))
        self.assertTrue(can("reviewer", TemplateAction.APPROVE_CANDIDATE))
        self.assertFalse(can("reviewer", TemplateAction.DEACTIVATE_TEMPLATE))
        self.assertTrue(can("admin", TemplateAction.REACTIVATE_TEMPLATE))

    def test_response_profile_display_policies_keep_presentation_separate(self) -> None:
        management = display_policy_for_response_profile("management")
        analyst = display_policy_for_response_profile("analyst")
        technical = display_policy_for_response_profile("technical")

        self.assertFalse(management.show_sql_inline)
        self.assertFalse(management.show_reporting_audit)
        self.assertEqual(management.summary_heading, "Business Summary")
        self.assertTrue(analyst.show_sql_inline)
        self.assertFalse(analyst.show_technical_debug)
        self.assertTrue(technical.show_sql_inline)
        self.assertTrue(technical.show_reporting_audit)
        self.assertTrue(technical.show_technical_debug)

    def test_viewer_cannot_create_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ScenarioPatch(self, "demo", Path(temp_dir) / "demo")
            with patch.dict("os.environ", {"LOG_DIR": str(Path(temp_dir) / "logs")}, clear=False):
                with self.assertRaises(PermissionError):
                    create_candidate_from_run(run_record(), **VIEWER)

    def test_contributor_can_create_candidate_but_cannot_approve(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            ScenarioPatch(self, "demo", memory_dir)
            log_dir = Path(temp_dir) / "logs"
            with patch.dict("os.environ", {"LOG_DIR": str(log_dir)}, clear=False):
                candidate, created, _message = create_candidate_from_run(
                    run_record(),
                    **CONTRIBUTOR,
                )

                self.assertTrue(created)
                self.assertEqual(load_candidates()[0]["status"], "pending_review")
                with self.assertRaises(PermissionError):
                    approve_candidate_to_vsm(
                        str(candidate["candidate_id"]),
                        candidate["proposed_template"],
                        scenario="demo",
                        **CONTRIBUTOR,
                    )

                audit_rows = read_audit_rows(log_dir)
                self.assertEqual(audit_rows[-1]["actor_role"], "contributor")
                self.assertEqual(audit_rows[-1]["action"], "candidate_created")
                self.assertEqual(audit_rows[-1]["candidate_id"], candidate["candidate_id"])
                self.assertEqual(audit_rows[-1]["scenario"], "demo")
                self.assertTrue(audit_rows[-1]["timestamp"])

    def test_reviewer_can_review_candidates_but_cannot_deactivate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            ScenarioPatch(self, "demo", memory_dir)
            with patch.dict("os.environ", {"LOG_DIR": str(Path(temp_dir) / "logs")}, clear=False):
                save_candidates(
                    [
                        candidate_record(scenario="demo", candidate_id="approve_me"),
                        candidate_record(scenario="demo", candidate_id="reject_me"),
                        candidate_record(scenario="demo", candidate_id="change_me"),
                    ]
                )

                approved = approve_candidate_to_vsm(
                    "approve_me",
                    proposed_template(scenario="demo"),
                    scenario="demo",
                    **REVIEWER,
                )
                rejected = reject_candidate(
                    "reject_me",
                    "Not reusable enough.",
                    scenario="demo",
                    **REVIEWER,
                )
                changes = mark_candidate_needs_changes(
                    "change_me",
                    "Please tighten the trigger phrases.",
                    scenario="demo",
                    **REVIEWER,
                )

                self.assertEqual(rejected["status"], "rejected")
                self.assertEqual(changes["status"], "needs_changes")
                with self.assertRaises(PermissionError):
                    deactivate_approved_template(
                        approved["template"]["id"],
                        "Reviewer cannot deactivate.",
                        scenario="demo",
                        **REVIEWER,
                    )

    def test_admin_can_deactivate_and_reactivate_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            ScenarioPatch(self, "demo", memory_dir)
            with patch.dict("os.environ", {"LOG_DIR": str(Path(temp_dir) / "logs")}, clear=False):
                write_approved_template(
                    approved_template(scenario="demo", template_id="admin_template"),
                    memory_dir=memory_dir,
                )
                initial_index = write_master_index("demo", memory_dir=memory_dir)
                self.assertEqual(initial_index["template_count"], 1)

                deactivated = deactivate_approved_template(
                    "admin_template",
                    "Outdated business rule.",
                    scenario="demo",
                    **ADMIN,
                )
                self.assertEqual(deactivated["template"]["status"], "disabled")
                self.assertEqual(deactivated["index"]["template_count"], 0)

                reactivated = reactivate_approved_template(
                    "admin_template",
                    scenario="demo",
                    **ADMIN,
                )
                self.assertEqual(reactivated["template"]["status"], "approved")
                self.assertTrue(reactivated["template"]["is_active"])
                self.assertEqual(reactivated["index"]["template_count"], 1)

    def test_scenario_isolation_is_preserved_for_approved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            demo_dir = Path(temp_dir) / "demo"
            wuerth_dir = Path(temp_dir) / "wuerth_local"
            ScenarioPatch(self, "demo", demo_dir)
            ScenarioPatch(self, "wuerth_local", wuerth_dir)
            log_dir = Path(temp_dir) / "logs"
            with patch.dict("os.environ", {"LOG_DIR": str(log_dir)}, clear=False):
                set_active_scenario_id("demo")
                save_candidates([candidate_record(scenario="demo", candidate_id="demo_candidate")])
                demo_result = approve_candidate_to_vsm(
                    "demo_candidate",
                    proposed_template(scenario="demo"),
                    scenario="demo",
                    **REVIEWER,
                )

                set_active_scenario_id("wuerth_local")
                save_candidates([
                    candidate_record(
                        scenario="wuerth_local",
                        candidate_id="wuerth_candidate",
                    )
                ])
                wuerth_result = approve_candidate_to_vsm(
                    "wuerth_candidate",
                    proposed_template(
                        scenario="wuerth_local",
                        question="Frachtkosten pro Kunde",
                        tables=["wuerth.shipments"],
                    ),
                    scenario="wuerth_local",
                    **REVIEWER,
                )

                self.assertTrue(str(demo_result["template_path"]).startswith(str(demo_dir)))
                self.assertTrue(str(wuerth_result["template_path"]).startswith(str(wuerth_dir)))
                demo_index = yaml.safe_load((demo_dir / "master_index.yaml").read_text(encoding="utf-8"))
                wuerth_index = yaml.safe_load((wuerth_dir / "master_index.yaml").read_text(encoding="utf-8"))
                self.assertEqual(demo_index["scenario"], "demo")
                self.assertEqual(wuerth_index["scenario"], "wuerth_local")
                self.assertEqual(demo_index["template_count"], 1)
                self.assertEqual(wuerth_index["template_count"], 1)


if __name__ == "__main__":
    unittest.main()
