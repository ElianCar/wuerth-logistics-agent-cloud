from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import yaml

from src.agent.memory_index_builder import write_master_index
from src.agent.memory_lifecycle import (
    MemoryLifecycleError,
    approve_candidate_to_vsm,
    run_retrieval_smoke_test,
    write_approved_template,
)
from src.agent.memory_store import load_candidates, save_candidates
from src.agent.memory_vector_retriever import retrieve_memory_templates
from src.config.scenarios import (
    SCENARIOS,
    reset_active_scenario_id,
    set_active_scenario_id,
)


REVIEWER_ACTOR = {"actor_id": "template_reviewer", "actor_role": "reviewer"}


def approved_template(
    *,
    scenario: str,
    template_id: str,
    title: str,
    tables: list[str],
    terms: list[str],
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
        "searchable_terms": terms,
        "synonyms": {},
        "required_tables": tables,
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


def candidate_record(
    *,
    scenario: str,
    candidate_id: str = "cand_test_1",
    status: str = "pending_review",
    question: str = "Revenue by customer",
    sql: str = "SELECT c_custkey, SUM(l_extendedprice) FROM customer JOIN orders ON true JOIN lineitem ON true GROUP BY c_custkey",
    tables: list[str] | None = None,
) -> dict[str, object]:
    table_list = tables or ["customer", "orders", "lineitem"]
    return {
        "candidate_id": candidate_id,
        "scenario": scenario,
        "dataset_id": f"{scenario}_dataset",
        "run_id": "run_test_1",
        "status": status,
        "is_active": False,
        "candidate_type": "solution_template",
        "created_at": "2026-06-05T00:00:00",
        "updated_at": "2026-06-05T00:00:00",
        "original_question": question,
        "generated_answer": "answer",
        "generated_sql": sql,
        "final_sql": sql,
        "validation_success": True,
        "execution_success": True,
        "source_tables": table_list,
        "row_count": 3,
        "feedback": {},
        "review": {
            "reviewed_by": None,
            "reviewed_at": None,
            "review_comment": None,
            "rejection_reason": None,
            "approved_template_id": None,
        },
        "proposed_template": proposed_template(scenario=scenario, question=question, sql=sql, tables=table_list),
    }


def proposed_template(
    *,
    scenario: str,
    question: str = "Revenue by customer",
    sql: str = "SELECT 1",
    tables: list[str] | None = None,
) -> dict[str, object]:
    table_list = tables or ["customer", "orders", "lineitem"]
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


class MemoryLifecycleTests(unittest.TestCase):
    def scenario_memory_dir(self, temp_dir: str, scenario: str) -> Path:
        memory_dir = Path(temp_dir) / scenario
        ScenarioPatch(self, scenario, memory_dir)
        return memory_dir

    def test_approval_writes_approved_yaml_rebuilds_index_and_not_legacy_solution_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = self.scenario_memory_dir(temp_dir, "demo")
            candidate = candidate_record(scenario="demo")
            save_candidates([candidate])
            legacy_path = memory_dir / "solution_templates.yaml"
            legacy_path.write_text(
                yaml.safe_dump({"templates": [{"template_id": "legacy_keep"}]}, sort_keys=False),
                encoding="utf-8",
            )
            legacy_before = legacy_path.read_text(encoding="utf-8")

            result = approve_candidate_to_vsm(
                "cand_test_1",
                candidate["proposed_template"],
                scenario="demo",
                **REVIEWER_ACTOR,
            )

            template = result["template"]
            approved_files = sorted((memory_dir / "approved").glob("*.yaml"))
            self.assertEqual(len(approved_files), 1)
            self.assertEqual(approved_files[0].name, f"{template['id']}.yaml")
            written = yaml.safe_load(approved_files[0].read_text(encoding="utf-8"))
            self.assertEqual(written["scenario"], "demo")
            self.assertEqual(written["status"], "approved")
            self.assertTrue(written["is_active"])
            self.assertEqual(legacy_path.read_text(encoding="utf-8"), legacy_before)

            index = yaml.safe_load((memory_dir / "master_index.yaml").read_text(encoding="utf-8"))
            self.assertEqual(index["scenario"], "demo")
            self.assertEqual(index["template_count"], 1)
            self.assertEqual(index["templates"][0]["id"], template["id"])
            self.assertTrue(result["smoke_test"]["would_inject_prompt_guidance"])
            self.assertEqual(load_candidates()[0]["status"], "approved")
            self.assertEqual(load_candidates()[0]["review"]["runtime_memory_target"], "approved_yaml")

    def test_inactive_rejected_and_needs_changes_templates_are_not_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            write_approved_template(
                approved_template(
                    scenario="demo",
                    template_id="inactive",
                    title="Revenue by customer",
                    tables=["customer"],
                    terms=["revenue", "customer"],
                    is_active=False,
                ),
                memory_dir=memory_dir,
            )
            write_approved_template(
                approved_template(
                    scenario="demo",
                    template_id="rejected",
                    title="Rejected revenue",
                    tables=["customer"],
                    terms=["revenue"],
                    status="rejected",
                ),
                memory_dir=memory_dir,
            )
            write_approved_template(
                approved_template(
                    scenario="demo",
                    template_id="needs_changes",
                    title="Needs changes revenue",
                    tables=["customer"],
                    terms=["revenue"],
                    status="needs_changes",
                ),
                memory_dir=memory_dir,
            )

            index = write_master_index("demo", memory_dir=memory_dir)

        self.assertEqual(index["template_count"], 0)

    def test_retrieval_smoke_test_finds_newly_approved_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = self.scenario_memory_dir(temp_dir, "wuerth_local")
            candidate = candidate_record(
                scenario="wuerth_local",
                question="Frachtkosten pro Kunde",
                tables=["wuerth.shipments"],
                sql="SELECT shiptoparty, SUM(freight_costs) FROM wuerth.shipments GROUP BY shiptoparty",
            )
            save_candidates([candidate])

            result = approve_candidate_to_vsm(
                "cand_test_1",
                candidate["proposed_template"],
                scenario="wuerth_local",
                **REVIEWER_ACTOR,
            )
            smoke = run_retrieval_smoke_test(
                "wuerth_local",
                "Frachtkosten pro Kunde",
                template_id=result["template"]["id"],
                memory_dir=memory_dir,
            )

        self.assertTrue(smoke["would_inject_prompt_guidance"])
        self.assertEqual(smoke["top_matches"][0]["template_id"], result["template"]["id"])

    def test_demo_and_wuerth_retrieval_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            demo_dir = Path(temp_dir) / "demo"
            wuerth_dir = Path(temp_dir) / "wuerth_local"
            write_approved_template(
                approved_template(
                    scenario="demo",
                    template_id="demo_revenue_by_customer",
                    title="Revenue by customer",
                    tables=["customer", "orders", "lineitem"],
                    terms=["revenue", "customer"],
                ),
                memory_dir=demo_dir,
            )
            write_approved_template(
                approved_template(
                    scenario="wuerth_local",
                    template_id="wuerth_shipments_by_delivery_type",
                    title="Lieferungen nach Lieferart",
                    tables=["wuerth.shipments"],
                    terms=["shipment", "delivery_type", "lieferungen", "lieferart"],
                ),
                memory_dir=wuerth_dir,
            )
            write_master_index("demo", memory_dir=demo_dir)
            write_master_index("wuerth_local", memory_dir=wuerth_dir)

            wuerth_for_demo_query = retrieve_memory_templates(
                "wuerth_local",
                "Revenue by customer",
                memory_dir=wuerth_dir,
            )["memory_retrieval"]
            demo_for_wuerth_query = retrieve_memory_templates(
                "demo",
                "Lieferungen nach Lieferart",
                memory_dir=demo_dir,
            )["memory_retrieval"]

        self.assertEqual(wuerth_for_demo_query["candidates"], [])
        self.assertEqual(demo_for_wuerth_query["candidates"], [])

    def test_invalid_approved_schema_is_rejected_and_not_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            invalid = approved_template(
                scenario="demo",
                template_id="invalid",
                title="",
                tables=["customer"],
                terms=["customer"],
            )

            with self.assertRaises(MemoryLifecycleError):
                write_approved_template(invalid, memory_dir=memory_dir)

            index = write_master_index("demo", memory_dir=memory_dir)
            invalid_file_exists = (memory_dir / "approved" / "invalid.yaml").exists()

        self.assertEqual(index["template_count"], 0)
        self.assertFalse(invalid_file_exists)

    def test_index_rebuild_failure_is_surfaced_and_candidate_not_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = self.scenario_memory_dir(temp_dir, "demo")
            candidate = candidate_record(scenario="demo")
            save_candidates([candidate])

            def failing_index_writer(*args: object, **kwargs: object) -> dict[str, object]:
                raise RuntimeError("index boom")

            with self.assertRaises(MemoryLifecycleError) as context:
                approve_candidate_to_vsm(
                    "cand_test_1",
                    candidate["proposed_template"],
                    scenario="demo",
                    index_writer=failing_index_writer,
                    **REVIEWER_ACTOR,
                )

            approved_dir = memory_dir / "approved"
            approved_files = list(approved_dir.glob("*.yaml")) if approved_dir.exists() else []
            candidate_status = load_candidates()[0]["status"]

        self.assertIn("index boom", str(context.exception))
        self.assertEqual(approved_files, [])
        self.assertEqual(candidate_status, "pending_review")


if __name__ == "__main__":
    unittest.main()
