import ollama

from app.config import get_config


def generate_sql(prompt: str) -> str:
    config = get_config()
    client = ollama.Client(host=config.ollama_host)

    try:
        response = client.chat(
            model=config.ollama_model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            options={
                "temperature": 0,
            },
        )
    except Exception as error:
        raise RuntimeError(
            "Could not get a response from Ollama. "
            f"Make sure Ollama is running at {config.ollama_host} and the model "
            f"'{config.ollama_model}' is installed. Try: "
            f"ollama serve; ollama pull {config.ollama_model}. "
            f"Original error: {error}"
        ) from error

    try:
        return response["message"]["content"].strip()
    except Exception as error:
        raise RuntimeError(f"Unexpected Ollama response format: {response}") from error
