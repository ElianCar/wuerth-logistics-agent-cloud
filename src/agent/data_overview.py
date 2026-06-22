"""Deterministic data overview builder.

Produces a Markdown overview of the active scenario combining a static catalog
(tables, columns, KPIs, example questions) parsed from the semantic layer with
live metrics from real read-only SQL queries. No LLM calls, no approximation:
if a profiling query fails, its metric is omitted rather than estimated.
"""
from __future__ import annotations

from typing import Any, Callable

import yaml

from src.agent.db import execute_read_only_sql
from src.config.scenarios import ScenarioConfig, get_active_scenario


Executor = Callable[[str, str], dict[str, Any]]


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


def _fmt_num(value: Any) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return _fmt_int(int(number))
    return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _load_semantic_layer(scenario: ScenarioConfig) -> dict[str, Any]:
    path = scenario.semantic_layer_path
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    return data if isinstance(data, dict) else {}


def _clean(text: Any) -> str:
    return " ".join(str(text).split()) if text else ""


def _table_columns(table: dict[str, Any]) -> list[str]:
    columns = table.get("columns")
    if isinstance(columns, dict):
        return list(columns.keys())
    important = table.get("important_columns")
    if isinstance(important, list):
        return [str(c) for c in important]
    return []


def _build_catalog_markdown(scenario: ScenarioConfig, layer: dict[str, Any]) -> list[str]:
    lines: list[str] = [f"## Datenüberblick – {scenario.label}", ""]

    dataset = layer.get("dataset")
    if isinstance(dataset, dict):
        description = _clean(dataset.get("description"))
        if description:
            lines.append(description)
            lines.append("")

    tables = layer.get("tables")
    if isinstance(tables, dict) and tables:
        lines.append("### Tabellen")
        for name, table in tables.items():
            if not isinstance(table, dict):
                continue
            display = table.get("business_name") or name
            lines.append(f"**{display}** (`{table.get('fully_qualified_name', name)}`)")
            description = _clean(table.get("description"))
            if description:
                lines.append(description)
            columns = _table_columns(table)
            if columns:
                lines.append(f"Spalten: {', '.join(f'`{c}`' for c in columns)}")
            lines.append("")

    kpis = layer.get("kpis")
    if isinstance(kpis, dict) and kpis:
        lines.append("### Verfügbare Kennzahlen (KPIs)")
        for _group, group_kpis in kpis.items():
            if not isinstance(group_kpis, dict):
                continue
            for _key, kpi in group_kpis.items():
                if not isinstance(kpi, dict):
                    continue
                display = kpi.get("business_name") or _key
                status = str(kpi.get("status", "")).strip()
                if status and "not_supported" in status:
                    lines.append(f"- {display} — _nicht unterstützt_ ({_clean(kpi.get('reason'))})")
                else:
                    lines.append(f"- {display}")
        lines.append("")

    warning = ""
    if isinstance(dataset, dict):
        warning = _clean(dataset.get("important_warning"))
    if warning:
        lines.append("### Wichtige Einschränkungen")
        lines.append(warning)
        lines.append("")

    return lines


def _split_invoice_shipment(scenario: ScenarioConfig) -> tuple[str | None, str | None]:
    invoices = shipments = None
    for table in scenario.allowed_tables:
        lowered = table.lower()
        if "invoice" in lowered:
            invoices = table
        elif "shipment" in lowered:
            shipments = table
    return invoices, shipments


def _run_scalar_row(executor: Executor, sql: str) -> dict[str, Any] | None:
    try:
        result = executor(sql, "")
    except Exception:
        return None
    rows = result.get("rows") or []
    columns = result.get("columns") or []
    if not rows or not columns:
        return None
    first = rows[0]
    if isinstance(first, dict):
        return first
    return {str(col): first[idx] for idx, col in enumerate(columns) if idx < len(first)}


def _build_live_metrics_markdown(scenario: ScenarioConfig, executor: Executor) -> list[str]:
    if scenario.scenario_id not in {"databricks", "wuerth_local"}:
        return []

    invoices, shipments = _split_invoice_shipment(scenario)
    lines: list[str] = ["### Aktuelle Kennzahlen (live aus der Datenbank)"]
    any_metric = False

    if invoices:
        inv = _run_scalar_row(
            executor,
            f"SELECT COUNT(*) AS zeilen, COUNT(DISTINCT order_number) AS auftraege, "
            f"COUNT(DISTINCT customer) AS kunden, COUNT(DISTINCT sales_area) AS vertriebszentren, "
            f"MIN(order_date) AS von, MAX(order_date) AS bis FROM {invoices}",
        )
        if inv:
            any_metric = True
            lines.append(f"**Rechnungen** (`{invoices}`)")
            lines.append(f"- Zeilen: {_fmt_int(inv.get('zeilen'))}")
            lines.append(f"- Aufträge (eindeutig): {_fmt_int(inv.get('auftraege'))}")
            lines.append(f"- Kunden (eindeutig): {_fmt_int(inv.get('kunden'))}")
            lines.append(f"- Vertriebszentren (eindeutig): {_fmt_int(inv.get('vertriebszentren'))}")
            if inv.get("von") is not None and inv.get("bis") is not None:
                lines.append(f"- Zeitraum (order_date): {inv.get('von')} bis {inv.get('bis')}")
            lines.append("")

    if shipments:
        shp = _run_scalar_row(
            executor,
            f"SELECT COUNT(*) AS zeilen, COUNT(DISTINCT delivery_number) AS lieferungen, "
            f"SUM(TRY_CAST(freight_costs AS DOUBLE)) AS frachtkosten FROM {shipments}"
            if scenario.scenario_id == "databricks"
            else f"SELECT COUNT(*) AS zeilen, COUNT(DISTINCT delivery_number) AS lieferungen, "
            f"SUM(freight_costs) AS frachtkosten FROM {shipments}",
        )
        if shp:
            any_metric = True
            lines.append(f"**Lieferungen** (`{shipments}`)")
            lines.append(f"- Zeilen: {_fmt_int(shp.get('zeilen'))}")
            lines.append(f"- Lieferungen (eindeutig): {_fmt_int(shp.get('lieferungen'))}")
            lines.append(f"- Frachtkosten gesamt: {_fmt_num(shp.get('frachtkosten'))}")
            lines.append("")

    if not any_metric:
        return ["### Aktuelle Kennzahlen", "_Live-Kennzahlen sind derzeit nicht abrufbar._", ""]
    return lines


def _example_questions(scenario: ScenarioConfig) -> list[str]:
    if scenario.scenario_id in {"databricks", "wuerth_local"}:
        return [
            "### Beispiel-Fragen",
            "- Wie viele Aufträge gibt es im Vertriebszentrum <ID> im Zeitraum 01.07.2025 – 31.12.2025?",
            "- Welche Produkte sind gemessen an Frachtkosten die Top 3 je Vertriebszentrum?",
            "- Wer ist der häufigste Kunde im Vertriebszentrum <ID>?",
            "",
        ]
    return []


def build_data_overview(
    scenario: ScenarioConfig | None = None,
    executor: Executor = execute_read_only_sql,
) -> str:
    active = scenario or get_active_scenario()
    layer = _load_semantic_layer(active)

    lines: list[str] = []
    lines.extend(_build_catalog_markdown(active, layer))
    lines.extend(_build_live_metrics_markdown(active, executor))
    lines.extend(_example_questions(active))

    return "\n".join(lines).strip()
