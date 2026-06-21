from __future__ import annotations

from pathlib import Path
import argparse
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.memory_vector_retriever import retrieve_memory_templates
from src.config.scenarios import normalize_scenario_id


DEFAULT_QUERIES = (
    "Lieferungen pro Kunde",
    "Shipments by customer",
    "Frachtkosten pro Kunde",
    "Freight cost by customer",
    "Gelieferte Menge pro Kunde",
    "Delivered quantity by customer",
    "Lieferungen nach Lieferart",
    "Shipments by delivery type",
    "Aufträge pro Kunde",
    "Invoice orders by customer",
    "Aufträge nach Marktsegment",
    "Invoice orders by market segment",
    "Rechnungen ohne passende Lieferungen",
    "Invoices without shipments",
    "Lieferungen ohne passende Rechnungen",
    "Shipments without invoices",
    "Umsatz pro Kunde",
    "Revenue by customer",
    "Tell me a joke",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate standalone memory template retrieval.")
    parser.add_argument("scenario", nargs="?", default="wuerth_local")
    return parser.parse_args()


def main() -> None:
    scenario = normalize_scenario_id(parse_args().scenario)
    for query in DEFAULT_QUERIES:
        result = retrieve_memory_templates(scenario, query)["memory_retrieval"]
        top_candidate = result["candidates"][0] if result["candidates"] else {}
        print(f"Query: {query}")
        print(f"  preprocessed: {result['query_preprocessed']}")
        print(f"  top_candidate: {top_candidate.get('template_id', '')}")
        print(f"  score: {top_candidate.get('score', '')}")
        print(f"  matched_terms: {top_candidate.get('matched_terms', [])}")
        print(f"  ambiguous: {result['ambiguous']}")
        print(f"  no_match_reason: {result['no_match_reason']}")


if __name__ == "__main__":
    main()
