from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import os
from typing import Any, Callable

from dotenv import load_dotenv


load_dotenv()


# Request-scoped accumulator for exact Anthropic API token usage (input/output).
# Isolated per execution context like the active-scenario ContextVar, so concurrent
# Streamlit sessions do not mix counts. Holds None when no run is active.
_token_usage: ContextVar[dict[str, int] | None] = ContextVar("llm_token_usage", default=None)


def reset_token_usage() -> None:
    """Start a fresh per-request token counter. Call once before a run."""
    _token_usage.set({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0})


def get_token_usage() -> dict[str, int]:
    """Return a copy of the current request's accumulated token usage."""
    current = _token_usage.get()
    if current is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
    return dict(current)


def record_token_usage(input_tokens: int, output_tokens: int) -> None:
    """Add exact token counts to the active request counter (no-op if none active).

    For code paths that bypass invoke_model (e.g. the Anthropic SDK used by the
    PowerPoint export). Counts only real API values; pass 0 when none are available.
    """
    current = _token_usage.get()
    if current is None:
        return
    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    current["input_tokens"] += input_tokens
    current["output_tokens"] += output_tokens
    current["total_tokens"] += input_tokens + output_tokens
    current["calls"] += 1


DEFAULT_GEMINI_PRIMARY_MODEL = "gemini-3.1-flash-lite-preview"
DEFAULT_GEMINI_BACKUP_MODEL = "gemini-2.5-flash"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
DEFAULT_OLLAMA_BACKUP_MODEL = "llama3.2:3b"
DEFAULT_ANTHROPIC_EASY_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_ANTHROPIC_MEDIUM_MODEL = "claude-sonnet-4-6"
DEFAULT_ANTHROPIC_HARD_MODEL = "claude-opus-4-8"
DEFAULT_ANTHROPIC_FALLBACK_MODEL = DEFAULT_ANTHROPIC_HARD_MODEL
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
    selected_provider = get_provider(provider)
    if selected_provider == "gemini":
        return os.getenv("GEMINI_PRIMARY_MODEL", DEFAULT_GEMINI_PRIMARY_MODEL)
    if selected_provider == "anthropic":
        return os.getenv("ANTHROPIC_PRIMARY_MODEL", DEFAULT_ANTHROPIC_MEDIUM_MODEL)
    return os.getenv("PRIMARY_MODEL") or os.getenv("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL


def get_backup_model(provider: str | None = None) -> str:
    selected_provider = get_provider(provider)
    if selected_provider == "gemini":
        return os.getenv("GEMINI_BACKUP_MODEL", DEFAULT_GEMINI_BACKUP_MODEL)
    if selected_provider == "anthropic":
        return os.getenv("ANTHROPIC_FALLBACK_MODEL", DEFAULT_ANTHROPIC_FALLBACK_MODEL)
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


def get_anthropic_api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY") or ""


def anthropic_api_key_is_placeholder() -> bool:
    api_key = get_anthropic_api_key().strip()
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
    if selected_provider == "anthropic":
        return _get_anthropic_llm(selected_model)
    if selected_provider == "ollama":
        return _get_ollama_llm(selected_model, ollama_host=ollama_host)

    raise ModelAdapterError(
        f"Unsupported LLM_PROVIDER '{selected_provider}'. Use 'anthropic', 'gemini', or 'ollama'."
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
    _accumulate_token_usage(raw_response)
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


def _get_anthropic_llm(model_name: str) -> Any:
    api_key = get_anthropic_api_key().strip()
    if not api_key:
        raise ModelAdapterError(
            "ANTHROPIC_API_KEY is not set. "
            "Add ANTHROPIC_API_KEY=<your-key> to .env before using the Anthropic provider."
        )

    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as error:
        raise ModelAdapterError(
            "Missing Anthropic dependency. Install requirements.txt so langchain-anthropic is available."
        ) from error

    return ChatAnthropic(**_anthropic_llm_kwargs(model_name=model_name, api_key=api_key))


def _anthropic_llm_kwargs(*, model_name: str, api_key: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model_name,
        "api_key": api_key,
        "max_tokens": get_max_output_tokens(),
    }
    if _anthropic_model_accepts_temperature(model_name):
        kwargs["temperature"] = get_temperature()
    return kwargs


def _anthropic_model_accepts_temperature(model_name: str) -> bool:
    return "opus" not in model_name.lower()


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


def _extract_token_usage(raw_response: Any) -> tuple[int, int]:
    """Read exact input/output token counts from the API response.

    Uses only values returned by the provider (Anthropic's `usage` field, surfaced
    by LangChain as `usage_metadata` / `response_metadata`). Never approximates: if
    no usage data is present, returns (0, 0).
    """
    usage = getattr(raw_response, "usage_metadata", None)
    if isinstance(usage, dict) and ("input_tokens" in usage or "output_tokens" in usage):
        return int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)

    metadata = getattr(raw_response, "response_metadata", None)
    if isinstance(metadata, dict):
        raw_usage = metadata.get("usage") or metadata.get("token_usage")
        if isinstance(raw_usage, dict):
            input_tokens = raw_usage.get("input_tokens", raw_usage.get("prompt_tokens", 0))
            output_tokens = raw_usage.get("output_tokens", raw_usage.get("completion_tokens", 0))
            return int(input_tokens or 0), int(output_tokens or 0)

    return 0, 0


def _accumulate_token_usage(raw_response: Any) -> None:
    """Add this response's exact token usage to the active request counter (no-op if none)."""
    current = _token_usage.get()
    if current is None:
        return
    input_tokens, output_tokens = _extract_token_usage(raw_response)
    current["input_tokens"] += input_tokens
    current["output_tokens"] += output_tokens
    current["total_tokens"] += input_tokens + output_tokens
    current["calls"] += 1


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
