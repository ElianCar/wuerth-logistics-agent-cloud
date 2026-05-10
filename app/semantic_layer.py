from pathlib import Path

import yaml


SEMANTIC_LAYER_PATH = (
    Path(__file__).resolve().parent.parent
    / "semantic_layer"
    / "tpch_semantic_layer.yaml"
)


def get_semantic_layer_text() -> str:
    if not SEMANTIC_LAYER_PATH.exists():
        raise FileNotFoundError(f"Semantic layer file not found: {SEMANTIC_LAYER_PATH}")

    with SEMANTIC_LAYER_PATH.open("r", encoding="utf-8") as file:
        semantic_layer = yaml.safe_load(file)

    if not semantic_layer:
        raise RuntimeError(f"Semantic layer file is empty: {SEMANTIC_LAYER_PATH}")

    return yaml.safe_dump(semantic_layer, sort_keys=False)
