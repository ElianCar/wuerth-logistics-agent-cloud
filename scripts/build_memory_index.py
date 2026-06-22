from __future__ import annotations

from pathlib import Path
import argparse
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.memory_index_builder import master_index_path, write_master_index
from src.config.scenarios import normalize_scenario_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a scenario-local approved memory template master index."
    )
    parser.add_argument(
        "scenario",
        help="Scenario id, for example demo, wuerth_local, or databricks.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include approved inactive templates for diagnostics. Defaults to active only.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scenario = normalize_scenario_id(args.scenario)
    index = write_master_index(
        scenario,
        include_inactive=bool(args.include_inactive),
    )
    path = master_index_path(scenario)
    print(f"Built {path}")
    print(f"Scenario: {index['scenario']}")
    print(f"Templates indexed: {index['template_count']}")


if __name__ == "__main__":
    main()
