from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from src.agent.memory_index_builder import build_master_index, write_master_index


def template_data(**overrides: object) -> dict[str, object]:
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


def write_template(memory_dir: Path, name: str, data: dict[str, object]) -> Path:
    approved_dir = memory_dir / "approved"
    approved_dir.mkdir(parents=True, exist_ok=True)
    path = approved_dir / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


class MemoryIndexBuilderTests(unittest.TestCase):
    def test_creates_master_index_with_required_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(memory_dir, "revenue.yaml", template_data())

            index = build_master_index(
                "wuerth_local",
                memory_dir=memory_dir,
                generated_at="2026-06-05T00:00:00Z",
            )

        self.assertEqual(index["schema_version"], 1)
        self.assertEqual(index["scenario"], "wuerth_local")
        self.assertEqual(index["generated_at"], "2026-06-05T00:00:00Z")
        self.assertEqual(index["template_count"], 1)
        self.assertEqual(len(index["templates"]), 1)

    def test_includes_only_approved_active_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(memory_dir, "approved.yaml", template_data(id="approved_template"))
            write_template(memory_dir, "pending.yaml", template_data(id="pending_template", status="pending_review"))
            write_template(memory_dir, "rejected.yaml", template_data(id="rejected_template", status="rejected"))
            write_template(memory_dir, "inactive.yaml", template_data(id="inactive_template", is_active=False))
            write_template(memory_dir, "wrong.yaml", template_data(id="wrong_template", scenario="demo"))

            index = build_master_index("wuerth_local", memory_dir=memory_dir)

        self.assertEqual(index["template_count"], 1)
        self.assertEqual(index["templates"][0]["id"], "approved_template")

    def test_creates_empty_index_when_approved_directory_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"

            index = build_master_index("wuerth_local", memory_dir=memory_dir)

        self.assertEqual(index["template_count"], 0)
        self.assertEqual(index["templates"], [])

    def test_write_master_index_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(memory_dir, "revenue.yaml", template_data())

            index = write_master_index("wuerth_local", memory_dir=memory_dir)
            written = yaml.safe_load((memory_dir / "master_index.yaml").read_text(encoding="utf-8"))

        self.assertEqual(index["template_count"], 1)
        self.assertEqual(written["template_count"], 1)

    def test_index_record_contains_checksum_and_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(memory_dir, "revenue.yaml", template_data())

            index = build_master_index("wuerth_local", memory_dir=memory_dir)

        record = index["templates"][0]
        self.assertTrue(record["checksum"].startswith("sha256:"))
        self.assertEqual(record["path"], "wuerth_local/approved/revenue.yaml")

    def test_searchable_text_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(
                memory_dir,
                "revenue.yaml",
                template_data(
                    synonyms={"versandstelle": "shipping_point", "umsatz": "revenue"},
                ),
            )

            index = build_master_index("wuerth_local", memory_dir=memory_dir)

        self.assertEqual(
            index["templates"][0]["searchable_text"],
            "revenue_by_shipping_point wuerth_local Revenue by shipping point "
            "revenue_by_dimension Revenue grouped by shipping point. Umsatz pro Versandstelle "
            "revenue shipping_point wuerth.shipments shipping_point revenue umsatz revenue "
            "versandstelle shipping_point",
        )

    def test_index_generation_ignores_candidate_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "wuerth_local"
            write_template(memory_dir, "approved.yaml", template_data(id="approved_template"))
            candidates_dir = memory_dir / "candidates"
            candidates_dir.mkdir(parents=True)
            (candidates_dir / "candidate.yaml").write_text(
                yaml.safe_dump(template_data(id="candidate_template")),
                encoding="utf-8",
            )
            (memory_dir / "memory_candidates.yaml").write_text(
                yaml.safe_dump({"candidates": [template_data(id="legacy_candidate")]}),
                encoding="utf-8",
            )

            index = build_master_index("wuerth_local", memory_dir=memory_dir)

        self.assertEqual(index["template_count"], 1)
        self.assertEqual(index["templates"][0]["id"], "approved_template")


if __name__ == "__main__":
    unittest.main()
