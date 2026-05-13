from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable

from dotenv import load_dotenv


load_dotenv()


DEFAULT_GEMINI_PRIMARY_MODEL = "gemini-3.1-flash-lite-preview"
DEFAULT_GEMINI_BACKUP_MODEL = "gemini-2.5-flash"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
DEFAULT_OLLAMA_BACKUP_MODEL = "llama3.2:3b"
PLACEHOLDER_API_KEY = "key"


class ModelAdapterError(RuntimeError):
    """Raised when the configured model provider cannot return usable text."""


class GeminiConfigurationError(ModelAdapterError):
    """Raised when Gemini is selected but cannot be configured."""


@dataclass(frozen=True)
class ModelResponse:
    model_name: str
    raw_response: Any
    response_text: str
    fallback_triggered: bool = False


ValidationFn = Callable[[str], object]


def get_provider(provider: str | None = None) -> str:
    configured_provider = provider if provider is not None else os.getenv("LLM_PROVIDER", "gemini")
    return configured_provider.strip().lower() or "gemini"


def get_primary_model(provider: str | None = None) -> str:
    if get_provider(provider) == "gemini":
        return os.getenv("GEMINI_PRIMARY_MODEL", DEFAULT_GEMINI_PRIMARY_MODEL)
    return os.getenv("PRIMARY_MODEL") or os.getenv("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL


def get_backup_model(provider: str | None = None) -> str:
    if get_provider(provider) == "gemini":
        return os.getenv("GEMINI_BACKUP_MODEL", DEFAULT_GEMINI_BACKUP_MODEL)
    return os.getenv("FALLBACK_MODEL", DEFAULT_OLLAMA_BACKUP_MODEL)


def get_temperature() -> float:
    return float(os.getenv("LLM_TEMPERATURE", "0"))


def get_max_output_tokens() -> int:
    return int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1024"))


def get_gemini_api_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


def gemini_api_key_is_placeholder() -> bool:
    api_key = get_gemini_api_key().strip()
    return not api_key or api_key == PLACEHOLDER_API_KEY


def get_llm(
    model_name: str | None = None,
    *,
    provider: str | None = None,
    ollama_host: str | None = None,
) -> Any:
    selected_provider = get_provider(provider)
    selected_model = model_name or get_primary_model(selected_provider)

    if selected_provider == "gemini":
        return _get_gemini_llm(selected_model)
    if selected_provider == "ollama":
        return _get_ollama_llm(selected_model, ollama_host=ollama_host)

    raise ModelAdapterError(
        f"Unsupported LLM_PROVIDER '{selected_provider}'. Use 'gemini' or 'ollama'."
    )


def invoke_model(
    prompt: str,
    model_name: str | None = None,
    *,
    provider: str | None = None,
    ollama_host: str | None = None,
) -> ModelResponse:
    selected_provider = get_provider(provider)
    selected_model = model_name or get_primary_model(selected_provider)
    llm = get_llm(selected_model, provider=selected_provider, ollama_host=ollama_host)
    raw_response = llm.invoke(prompt)
    response_text = _extract_response_text(raw_response)

    if not response_text:
        raise ModelAdapterError(f"Model '{selected_model}' returned an empty response.")

    return ModelResponse(
        model_name=selected_model,
        raw_response=raw_response,
        response_text=response_text,
    )


def invoke_with_fallback(
    prompt: str,
    validation_fn: ValidationFn | None = None,
    *,
    provider: str | None = None,
    ollama_host: str | None = None,
) -> ModelResponse:
    selected_provider = get_provider(provider)
    primary_model = get_primary_model(selected_provider)
    backup_model = get_backup_model(selected_provider)
    attempts = [primary_model]
    if backup_model != primary_model:
        attempts.append(backup_model)

    errors: list[str] = []
    for model_name in attempts:
        try:
            response = invoke_model(
                prompt,
                model_name=model_name,
                provider=selected_provider,
                ollama_host=ollama_host,
            )
            _validate_response_text(response.response_text, validation_fn)
            return ModelResponse(
                model_name=response.model_name,
                raw_response=response.raw_response,
                response_text=response.response_text,
                fallback_triggered=model_name != primary_model,
            )
        except Exception as error:
            errors.append(f"{model_name}: {error}")

    raise ModelAdapterError("Both LLM attempts failed. " + " | ".join(errors))


def _get_gemini_llm(model_name: str) -> Any:
    api_key = get_gemini_api_key().strip()
    if not api_key or api_key == PLACEHOLDER_API_KEY:
        raise GeminiConfigurationError(
            "GEMINI_API_KEY is still set to the placeholder value 'key'. "
            "Replace GEMINI_API_KEY=key in .env with a real Gemini API key before using Gemini."
        )

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as error:
        raise ModelAdapterError(
            "Missing Gemini dependency. Install requirements.txt so "
            "langchain-google-genai and google-genai are available."
        ) from error

    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=get_temperature(),
        max_output_tokens=get_max_output_tokens(),
        max_retries=0,
    )


def _get_ollama_llm(model_name: str, *, ollama_host: str | None = None) -> Any:
    try:
        from langchain_ollama import ChatOllama
    except ImportError as error:
        raise ModelAdapterError(
            "Missing Ollama dependency. Install requirements.txt so langchain-ollama is available."
        ) from error

    return ChatOllama(
        model=model_name,
        base_url=ollama_host or os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        temperature=get_temperature(),
    )


def _extract_response_text(raw_response: Any) -> str:
    content = getattr(raw_response, "content", raw_response)

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()

    return str(content).strip()


def _validate_response_text(response_text: str, validation_fn: ValidationFn | None) -> None:
    if validation_fn is None:
        return

    validation = validation_fn(response_text)
    if validation is None or validation is True:
        return

    if validation is False:
        raise ModelAdapterError("Model response failed validation.")

    is_valid = getattr(validation, "is_valid", None)
    if is_valid is not None:
        if bool(is_valid):
            return
        error = getattr(validation, "error", "") or getattr(validation, "message", "")
        raise ModelAdapterError(f"Model response failed validation: {error}")

    if isinstance(validation, tuple) and validation:
        is_valid = bool(validation[0])
        if is_valid:
            return
        message = validation[1] if len(validation) > 1 else ""
        raise ModelAdapterError(f"Model response failed validation: {message}")

    raise ModelAdapterError(f"Model response failed validation: {validation}")
