from typing import Sequence


def generate_sql_with_ollama(
    *,
    model: str,
    ollama_host: str,
    messages: Sequence[tuple[str, str]],
) -> str:
    try:
        from langchain_ollama import ChatOllama
    except ImportError as error:
        raise RuntimeError(
            "LangChain Ollama integration is not installed. "
            "Run: pip install -r requirements.txt"
        ) from error

    llm = ChatOllama(
        model=model,
        base_url=ollama_host,
        temperature=0,
    )
    response = llm.invoke(list(messages))
    return str(response.content).strip()
