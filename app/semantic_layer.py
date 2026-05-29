from src.config.scenarios import get_active_scenario, load_semantic_layer_text

SEMANTIC_LAYER_PATH = get_active_scenario().semantic_layer_path


def get_semantic_layer_text() -> str:
    return load_semantic_layer_text(get_active_scenario())
