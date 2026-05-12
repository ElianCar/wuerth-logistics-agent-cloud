from src.llm.model_adapter import invoke_model


def generate_sql(prompt: str) -> str:
    try:
        return invoke_model(prompt).response_text
    except Exception as error:
        raise RuntimeError(f"Could not get a response from the configured LLM: {error}") from error
