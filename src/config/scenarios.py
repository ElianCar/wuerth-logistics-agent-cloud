from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import os
from pathlib import Path
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATABRICKS_ALLOWED_TABLES = (
    "workspace.default.datenabzug_projekt_tum_invoices",
    "workspace.default.datenabzug_projekt_tum_shipments",
)

WUERTH_LOCAL_ALLOWED_TABLES = (
    "wuerth.invoices",
    "wuerth.shipments",
)

DEMO_ALLOWED_TABLES = (
    "region",
    "nation",
    "supplier",
    "customer",
    "part",
    "partsupp",
    "orders",
    "lineitem",
)

LOCAL_SCENARIO_OPTIONS = ("demo", "wuerth_local", "databricks")
SUPPORTED_SCENARIOS = {"databricks", "demo", "wuerth_local"}
DEFAULT_SCENARIO_ID = "demo"

_active_scenario_id: ContextVar[str | None] = ContextVar("active_data_scenario", default=None)


@dataclass(frozen=True)
class ScenarioConfig:
    scenario_id: str
    label: str
    backend_name: str
    backend_display_name: str
    sql_dialect: str
    semantic_layer_path: Path
    memory_dir: Path
    evaluation_dir: Path
    dataset_id: str
    allowed_tables: tuple[str, ...]

    @property
    def semantic_layer_filename(self) -> str:
        return self.semantic_layer_path.name

    @property
    def safe_metadata(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_label": self.label,
            "backend_name": self.backend_name,
            "backend_display_name": self.backend_display_name,
            "sql_dialect": self.sql_dialect,
            "semantic_layer": self.semantic_layer_filename,
            "dataset_id": self.dataset_id,
            "allowed_tables": list(self.allowed_tables),
        }


SCENARIOS: dict[str, ScenarioConfig] = {
    "databricks": ScenarioConfig(
        scenario_id="databricks",
        label="Würth Databricks",
        backend_name="databricks",
        backend_display_name="Databricks SQL Warehouse",
        sql_dialect="Databricks SQL",
        semantic_layer_path=PROJECT_ROOT / "semantic_layer" / "databricks" / "wuerth_semantic_layer.yaml",
        memory_dir=PROJECT_ROOT / "memory" / "databricks",
        evaluation_dir=PROJECT_ROOT / "evaluation" / "databricks",
        dataset_id="wuerth_shipment_invoice_v1",
        allowed_tables=DATABRICKS_ALLOWED_TABLES,
    ),
    "wuerth_local": ScenarioConfig(
        scenario_id="wuerth_local",
        label="Würth local CSV data",
        backend_name="postgres",
        backend_display_name="PostgreSQL Würth local database",
        sql_dialect="PostgreSQL",
        semantic_layer_path=PROJECT_ROOT / "semantic_layer" / "databricks" / "wuerth_semantic_layer.yaml",
        memory_dir=PROJECT_ROOT / "memory" / "wuerth_local",
        evaluation_dir=PROJECT_ROOT / "evaluation" / "wuerth_local",
        dataset_id="wuerth_local_shipment_invoice_csv_v1",
        allowed_tables=WUERTH_LOCAL_ALLOWED_TABLES,
    ),
    "demo": ScenarioConfig(
        scenario_id="demo",
        label="Demo data",
        backend_name="postgres",
        backend_display_name="PostgreSQL demo database",
        sql_dialect="PostgreSQL",
        semantic_layer_path=PROJECT_ROOT / "semantic_layer" / "demo" / "tpch_semantic_layer.yaml",
        memory_dir=PROJECT_ROOT / "memory" / "demo",
        evaluation_dir=PROJECT_ROOT / "evaluation" / "demo",
        dataset_id="demo_tpch",
        allowed_tables=DEMO_ALLOWED_TABLES,
    ),
}


class ScenarioConfigError(ValueError):
    """Raised when the active data scenario is unsupported or misconfigured."""


def normalize_scenario_id(value: str | None) -> str:
    scenario_id = (value or "").strip().lower()
    if not scenario_id:
        return DEFAULT_SCENARIO_ID
    if scenario_id not in SUPPORTED_SCENARIOS:
        supported = ", ".join(sorted(SUPPORTED_SCENARIOS))
        raise ScenarioConfigError(
            f"Unsupported DATA_SCENARIO '{scenario_id}'. Use one of: {supported}."
        )
    return scenario_id


def configured_scenario_id() -> str:
    return normalize_scenario_id(os.getenv("DATA_SCENARIO", DEFAULT_SCENARIO_ID))


def get_active_scenario_id() -> str:
    override = _active_scenario_id.get()
    if override:
        return normalize_scenario_id(override)
    return configured_scenario_id()


def set_active_scenario_id(scenario_id: str) -> None:
    _active_scenario_id.set(normalize_scenario_id(scenario_id))


def reset_active_scenario_id() -> None:
    _active_scenario_id.set(None)


def get_active_scenario() -> ScenarioConfig:
    return SCENARIOS[get_active_scenario_id()]


def get_scenario_options() -> list[ScenarioConfig]:
    return [SCENARIOS[scenario_id] for scenario_id in LOCAL_SCENARIO_OPTIONS]


def load_semantic_layer_text(scenario: ScenarioConfig | None = None) -> str:
    active_scenario = scenario or get_active_scenario()
    path = active_scenario.semantic_layer_path
    if not path.exists():
        raise FileNotFoundError(f"Semantic layer file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        semantic_layer = yaml.safe_load(file)

    if not semantic_layer:
        raise RuntimeError(f"Semantic layer file is empty: {path}")

    return yaml.safe_dump(semantic_layer, sort_keys=False, allow_unicode=True)
