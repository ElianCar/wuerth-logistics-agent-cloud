from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from src.agent.memory_index_builder import build_master_index, write_master_index


def template_data(
    *,
    scenario: str,
    template_id: str,
    tables: list[str],
    columns: list[str],
    status: str = "approved",
    is_active: bool = True,
) -> dict[str, object]:
    return {
        "id": template_id,
        "scenario": scenario,
        "status": status,
        "is_active": is_active,
        "title": f"{template_id} title",
        "intent": template_id,
        "trigger_phrases": [template_id],
        "searchable_summary": f"{template_id} searchable summary",
        "searchable_terms": template_id.split("_"),
        "synonyms": {},
        "required_tables": tables,
        "required_columns": columns,
        "business_rules": ["Use verified schema only."],
        "sql_pattern": "SELECT pattern only.",
        "do_not_use_when": ["Different scenario."],
        "validation_checks": ["SELECT only."],
        "source_question": template_id,
        "source_sql": "",
        "approved_by": "test",
        "approved_at": "2026-06-05T00:00:00",
        "version": 1,
    }


def write_template(memory_dir: Path, name: str, data: dict[str, object]) -> None:
    approved_dir = memory_dir / "approved"
    approved_dir.mkdir(parents=True, exist_ok=True)
    (approved_dir / name).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


class MemoryScenarioIsolationTests(unittest.TestCase):
    def test_demo_index_generation_includes_only_demo_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            write_template(
                memory_dir,
                "demo.yaml",
                template_data(
                    scenario="demo",
                    template_id="demo_revenue_by_customer",
                    tables=["customer", "orders", "lineitem"],
                    columns=["c_custkey", "o_orderkey", "l_extendedprice"],
                ),
            )
            write_template(
                memory_dir,
                "wrong.yaml",
                template_data(
                    scenario="wuerth_local",
                    template_id="wuerth_freight",
                    tables=["wuerth.shipments"],
                    columns=["freight_costs"],
                ),
            )

            index = build_master_index("demo", memory_dir=memory_dir)

        self.assertEqual(index["scenario"], "demo")
        self.assertEqual(index["template_count"], 1)
        self.assertEqual(index["templates"][0]["id"], "demo_revenue_by_customer")

    def test_wuerth_index_generation_includes_only_wuerth_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(
                memory_dir,
                "wuerth.yaml",
                template_data(
                    scenario="wuerth_local",
                    template_id="wuerth_freight_by_customer",
                    tables=["wuerth.shipments"],
                    columns=["freight_costs", "shiptoparty"],
                ),
            )
            write_template(
                memory_dir,
                "wrong.yaml",
                template_data(
                    scenario="demo",
                    template_id="demo_revenue",
                    tables=["lineitem"],
                    columns=["l_extendedprice"],
                ),
            )

            index = build_master_index("wuerth_local", memory_dir=memory_dir)

        self.assertEqual(index["scenario"], "wuerth_local")
        self.assertEqual(index["template_count"], 1)
        self.assertEqual(index["templates"][0]["id"], "wuerth_freight_by_customer")

    def test_candidate_files_and_solution_templates_are_not_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            write_template(
                memory_dir,
                "approved.yaml",
                template_data(
                    scenario="demo",
                    template_id="approved_demo",
                    tables=["lineitem"],
                    columns=["l_extendedprice"],
                ),
            )
            (memory_dir / "memory_candidates.yaml").write_text(
                yaml.safe_dump({"candidates": [template_data(scenario="demo", template_id="candidate", tables=["lineitem"], columns=["l_extendedprice"])]}),
                encoding="utf-8",
            )
            (memory_dir / "solution_templates.yaml").write_text(
                yaml.safe_dump({"templates": [template_data(scenario="demo", template_id="legacy_solution", tables=["lineitem"], columns=["l_extendedprice"])]}),
                encoding="utf-8",
            )
            candidates_dir = memory_dir / "candidates"
            candidates_dir.mkdir(parents=True)
            (candidates_dir / "candidate.yaml").write_text(
                yaml.safe_dump(template_data(scenario="demo", template_id="candidate_file", tables=["lineitem"], columns=["l_extendedprice"])),
                encoding="utf-8",
            )

            index = build_master_index("demo", memory_dir=memory_dir)

        self.assertEqual(index["template_count"], 1)
        self.assertEqual(index["templates"][0]["id"], "approved_demo")

    def test_write_master_index_creates_missing_approved_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "demo"
            index = write_master_index("demo", memory_dir=memory_dir)

            written = yaml.safe_load((memory_dir / "master_index.yaml").read_text(encoding="utf-8"))

            self.assertTrue((memory_dir / "approved").exists())
            self.assertEqual(index["template_count"], 0)
            self.assertEqual(written["templates"], [])

    def test_path_containment_excludes_symlink_outside_approved_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            memory_dir = root / "demo"
            approved_dir = memory_dir / "approved"
            approved_dir.mkdir(parents=True)
            outside = root / "outside.yaml"
            outside.write_text(
                yaml.safe_dump(
                    template_data(
                        scenario="demo",
                        template_id="outside",
                        tables=["lineitem"],
                        columns=["l_extendedprice"],
                    )
                ),
                encoding="utf-8",
            )
            symlink = approved_dir / "outside.yaml"
            try:
                symlink.symlink_to(outside)
            except OSError:
                self.skipTest("Symlinks are not available on this filesystem.")

            index = build_master_index("demo", memory_dir=memory_dir)

        self.assertEqual(index["template_count"], 0)


if __name__ == "__main__":
    unittest.main()
