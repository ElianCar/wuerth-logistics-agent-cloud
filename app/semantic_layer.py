from src.config.scenarios import SCENARIOS, load_semantic_layer_text

SEMANTIC_LAYER_PATH = SCENARIOS["demo"].semantic_layer_path


def get_semantic_layer_text() -> str:
    return load_semantic_layer_text(SCENARIOS["demo"])
