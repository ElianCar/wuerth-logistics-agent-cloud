from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.agent.memory_vector_retriever import METHOD, preprocess_text, retrieve_memory_templates
from src.config.scenarios import get_active_scenario_id, normalize_scenario_id


DISABLED_REASON = "memory_retrieval_disabled"
MISSING_OR_EMPTY_REASON = "master_index_missing_or_empty"
ERROR_REASON = "memory_retrieval_error"


def memory_retrieval_enabled() -> bool:
    value = os.getenv("MEMORY_RETRIEVAL_ENABLED", "true").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def empty_memory_retrieval(
    *,
    enabled: bool,
    scenario: str,
    query_original: str,
    query_preprocessed: str,
    no_match_reason: str,
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "method": METHOD,
        "scenario": scenario,
        "query_original": query_original,
        "query_preprocessed": query_preprocessed,
        "candidates": [],
        "top_matches": [],
        "min_score": None,
        "no_match_reason": no_match_reason,
        "ambiguous": False,
    }


def retrieve_memory_for_router(
    user_question: str,
    *,
    scenario: str | None = None,
    limit: int = 3,
    memory_dir: Path | None = None,
    index_path: Path | None = None,
) -> dict[str, Any]:
    """Return scenario-local memory retrieval metadata for router state."""

    scenario_id = normalize_scenario_id(scenario or get_active_scenario_id())
    if not memory_retrieval_enabled():
        return empty_memory_retrieval(
            enabled=False,
            scenario=scenario_id,
            query_original=user_question,
            query_preprocessed="",
            no_match_reason=DISABLED_REASON,
        )

    query_preprocessed = preprocess_text(user_question)
    try:
        result = retrieve_memory_templates(
            scenario_id,
            user_question,
            memory_dir=memory_dir,
            index_path=index_path,
            top_k=limit,
        )["memory_retrieval"]
    except Exception as error:
        failed = empty_memory_retrieval(
            enabled=True,
            scenario=scenario_id,
            query_original=user_question,
            query_preprocessed=query_preprocessed,
            no_match_reason=ERROR_REASON,
        )
        failed["error_type"] = type(error).__name__
        failed["error_message"] = str(error)
        return failed

    # The standalone retriever uses enabled=false for missing/empty indexes and
    # safety-filtered indexes. At router level the feature was enabled, so keep
    # enabled=true while preserving the no-match reason.
    normalized = {
        "enabled": True,
        "method": result.get("method", METHOD),
        "scenario": scenario_id,
        "query_original": result.get("query_original", user_question),
        "query_preprocessed": result.get("query_preprocessed", query_preprocessed),
        "candidates": list(result.get("candidates", []) or []),
        "top_matches": list(result.get("top_matches", []) or []),
        "min_score": result.get("min_score"),
        "no_match_reason": result.get("no_match_reason", ""),
        "ambiguous": bool(result.get("ambiguous", False)),
    }
    if not normalized["candidates"] and not normalized["no_match_reason"]:
        normalized["no_match_reason"] = MISSING_OR_EMPTY_REASON
    return normalized


def find_similar_templates_for_router(
    user_question: str,
    memory_intent_key: str | None,
    intent: str | None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return router-level template candidates for backward compatibility."""

    _ = (memory_intent_key, intent)
    return retrieve_memory_for_router(
        user_question,
        limit=limit,
    )["candidates"]
