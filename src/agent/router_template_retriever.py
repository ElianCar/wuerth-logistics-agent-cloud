from __future__ import annotations

from typing import Any


def find_similar_templates_for_router(
    user_question: str,
    memory_intent_key: str | None,
    intent: str | None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return router-level template candidates.

    TODO: Replace this placeholder with vector-space or embedding-based cosine
    similarity retrieval. Router candidates are metadata only and must not
    generate SQL, approve templates, bypass validation, call an LLM, call a
    database, mutate memory, or influence SQL generation.
    """

    _ = (user_question, memory_intent_key, intent, limit)
    return []
