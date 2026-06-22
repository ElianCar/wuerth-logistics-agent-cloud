from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
import re
from typing import Any

import yaml

from src.agent.memory_index_builder import master_index_path, scenario_memory_dir
from src.config.scenarios import PROJECT_ROOT, normalize_scenario_id


METHOD = "tfidf_vector_space"
DEFAULT_TOP_K = 3
DEFAULT_MIN_SCORE = 0.20
DEFAULT_AMBIGUITY_DELTA = 0.05

ENGLISH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "give",
    "how",
    "in",
    "is",
    "me",
    "of",
    "per",
    "please",
    "show",
    "tell",
    "the",
    "to",
    "what",
    "with",
}

GERMAN_STOPWORDS = {
    "alle",
    "als",
    "am",
    "an",
    "auf",
    "aus",
    "bei",
    "bitte",
    "das",
    "den",
    "der",
    "die",
    "ein",
    "eine",
    "für",
    "gib",
    "im",
    "in",
    "ist",
    "je",
    "mir",
    "mit",
    "nach",
    "pro",
    "und",
    "vom",
    "von",
    "was",
    "welche",
    "zeige",
    "zu",
}

STOPWORDS = ENGLISH_STOPWORDS | GERMAN_STOPWORDS

DOMAIN_SYNONYMS = {
    "umsatz": "revenue",
    "sales": "revenue",
    "turnover": "revenue",
    "erlös": "revenue",
    "erloes": "revenue",
    "gross profit": "gross_profit",
    "gross_profit": "gross_profit",
    "rohertrag": "gross_profit",
    "kunde": "customer",
    "kunden": "customer",
    "customer": "customer",
    "customers": "customer",
    "sold to party": "customer",
    "sold_to_party": "customer",
    "artikel": "material",
    "article": "material",
    "product": "material",
    "products": "material",
    "material number": "material",
    "material_number": "material",
    "versandstelle": "shipping_point",
    "shipping point": "shipping_point",
    "shipping_point": "shipping_point",
    "warehouse": "shipping_point",
    "logistics location": "shipping_point",
    "fracht": "freight",
    "frachtkosten": "freight",
    "freight cost": "freight",
    "freight costs": "freight",
    "freight_cost": "freight",
    "freight_costs": "freight",
    "verpackung": "packing",
    "packing cost": "packing",
    "packing costs": "packing",
    "packing_cost": "packing",
    "packing_costs": "packing",
    "lieferungen pro kunde": "delivery_count customer",
    "lieferungen je kunde": "delivery_count customer",
    "kunden haben die meisten lieferungen": "delivery_count customer",
    "shipments by customer": "delivery_count customer",
    "deliveries by customer": "delivery_count customer",
    "top customers by shipments": "delivery_count customer",
    "lieferungen nach lieferart": "delivery_count delivery_type",
    "lieferungen pro lieferart": "delivery_count delivery_type",
    "shipments by delivery type": "delivery_count delivery_type",
    "deliveries by delivery type": "delivery_count delivery_type",
    "rechnungen ohne passende lieferungen": "invoice_without_shipment",
    "invoices without shipments": "invoice_without_shipment",
    "invoice records without matching shipment records": "invoice_without_shipment",
    "lieferungen ohne passende rechnungen": "shipment_without_invoice",
    "shipments without invoices": "shipment_without_invoice",
    "shipment records without matching invoice records": "shipment_without_invoice",
    "lieferung": "shipment",
    "lieferungen": "shipment",
    "shipment": "shipment",
    "shipments": "shipment",
    "delivery": "shipment",
    "deliveries": "shipment",
    "delivery count": "delivery_count",
    "delivery_count": "delivery_count",
    "lieferanzahl": "shipment",
    "delivered quantity": "delivered_quantity",
    "delivered_quantity": "delivered_quantity",
    "gelieferte menge": "delivered_quantity",
    "liefermenge": "delivered_quantity",
    "quantity delivered": "delivered_quantity",
    "quantity": "quantity",
    "order": "order",
    "orders": "order",
    "auftrag": "order",
    "aufträge": "order",
    "auftraege": "order",
    "order count": "order_count",
    "order_count": "order_count",
    "invoice": "invoice",
    "invoices": "invoice",
    "rechnung": "invoice",
    "rechnungen": "invoice",
    "market segment": "market_segment",
    "market_segment": "market_segment",
    "marktsegment": "market_segment",
    "sales area": "sales_area",
    "sales_area": "sales_area",
    "verkaufsbereich": "sales_area",
    "delivery type": "delivery_type",
    "delivery_type": "delivery_type",
    "lieferart": "delivery_type",
    "ship to party": "customer",
    "ship_to_party": "customer",
    "shiptoparty": "customer",
    "soldtoparty": "customer",
    "unmatched": "unmatched",
    "without matching": "unmatched",
    "without": "unmatched",
    "missing": "unmatched",
    "ohne passende": "unmatched",
    "ohne": "unmatched",
}

UNSAFE_QUERY_TERMS = {
    "alter",
    "create",
    "delete",
    "drop",
    "insert",
    "merge",
    "truncate",
    "update",
}


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _apply_phrase_synonyms(value: str) -> str:
    normalized = value.lower()
    for phrase, replacement in sorted(DOMAIN_SYNONYMS.items(), key=lambda item: len(item[0]), reverse=True):
        escaped = re.escape(phrase).replace(r"\ ", r"\s+")
        normalized = re.sub(
            rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])",
            replacement,
            normalized,
            flags=re.IGNORECASE,
        )
    return normalized


def _safe_singularize(token: str) -> str:
    if token in DOMAIN_SYNONYMS:
        return DOMAIN_SYNONYMS[token]
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
        return token[:-1]
    return token


def preprocess_tokens(value: str) -> list[str]:
    text = _apply_phrase_synonyms(value)
    text = re.sub(r"[^\w\säöüß]", " ", text, flags=re.IGNORECASE)
    raw_tokens = re.findall(r"[A-Za-z0-9_äöüß]+", text.lower())

    tokens: list[str] = []
    for token in raw_tokens:
        canonical = DOMAIN_SYNONYMS.get(token, token)
        canonical = _safe_singularize(canonical)
        canonical = DOMAIN_SYNONYMS.get(canonical, canonical)
        if canonical in STOPWORDS or not canonical:
            continue
        if canonical not in tokens:
            tokens.append(canonical)
    return tokens


def preprocess_text(value: str) -> str:
    return " ".join(preprocess_tokens(value))


def _load_master_index(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data if isinstance(data, dict) else None


def _path_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _record_path_is_safe(record_path: str, memory_dir: Path) -> bool:
    if not record_path:
        return False
    raw_path = Path(record_path)
    candidates = [raw_path] if raw_path.is_absolute() else [
        PROJECT_ROOT / raw_path,
        memory_dir.parent / raw_path,
        memory_dir / raw_path,
    ]
    return any(_path_inside(candidate, memory_dir) for candidate in candidates)


def _filtered_index_records(
    index: dict[str, Any],
    *,
    scenario: str,
    memory_dir: Path,
) -> list[dict[str, Any]]:
    if index.get("scenario") != scenario:
        return []
    templates = index.get("templates", [])
    if not isinstance(templates, list):
        return []

    records: list[dict[str, Any]] = []
    for record in templates:
        if not isinstance(record, dict):
            continue
        if record.get("scenario", scenario) != scenario:
            continue
        if record.get("status") != "approved":
            continue
        if record.get("is_active") is not True:
            continue
        if not _record_path_is_safe(str(record.get("path", "")), memory_dir):
            continue
        records.append(record)
    return records


def _term_frequencies(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = float(len(tokens))
    return {token: count / total for token, count in counts.items()}


def _idf(documents: list[list[str]]) -> dict[str, float]:
    doc_count = len(documents)
    vocabulary = sorted({token for document in documents for token in set(document)})
    return {
        token: math.log((1 + doc_count) / (1 + sum(1 for document in documents if token in document))) + 1
        for token in vocabulary
    }


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    return {
        token: frequency * idf[token]
        for token, frequency in _term_frequencies(tokens).items()
        if token in idf
    }


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(token, 0.0) for token, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _memory_retrieval_result(
    *,
    enabled: bool,
    scenario: str,
    query_original: str,
    query_preprocessed: str,
    candidates: list[dict[str, Any]] | None = None,
    no_match_reason: str = "",
    ambiguous: bool = False,
) -> dict[str, Any]:
    return {
        "memory_retrieval": {
            "enabled": enabled,
            "method": METHOD,
            "scenario": scenario,
            "query_original": query_original,
            "query_preprocessed": query_preprocessed,
            "candidates": candidates or [],
            "no_match_reason": no_match_reason,
            "ambiguous": ambiguous,
        }
    }


def retrieve_memory_templates(
    scenario: str,
    user_question: str,
    *,
    memory_dir: Path | None = None,
    index_path: Path | None = None,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    ambiguity_delta: float = DEFAULT_AMBIGUITY_DELTA,
) -> dict[str, Any]:
    # Standalone retrieval returns guidance metadata only. It does not call an
    # LLM, generate SQL, execute SQL, or bypass later SQL validation.
    scenario_id = normalize_scenario_id(scenario)
    resolved_memory_dir = scenario_memory_dir(scenario_id, memory_dir)
    resolved_index_path = index_path or master_index_path(scenario_id, resolved_memory_dir)
    query_preprocessed = preprocess_text(user_question)

    if memory_dir is None and index_path is not None and not _path_inside(
        resolved_index_path,
        resolved_memory_dir,
    ):
        return _memory_retrieval_result(
            enabled=False,
            scenario=scenario_id,
            query_original=user_question,
            query_preprocessed=query_preprocessed,
            no_match_reason="index_path_outside_scenario_memory_dir",
        )

    index = _load_master_index(resolved_index_path)
    if not index or not index.get("templates"):
        return _memory_retrieval_result(
            enabled=False,
            scenario=scenario_id,
            query_original=user_question,
            query_preprocessed=query_preprocessed,
            no_match_reason="master_index_missing_or_empty",
        )

    if index.get("scenario") != scenario_id:
        return _memory_retrieval_result(
            enabled=False,
            scenario=scenario_id,
            query_original=user_question,
            query_preprocessed=query_preprocessed,
            no_match_reason="index_scenario_mismatch",
        )

    records = _filtered_index_records(index, scenario=scenario_id, memory_dir=resolved_memory_dir)
    if not records:
        return _memory_retrieval_result(
            enabled=False,
            scenario=scenario_id,
            query_original=user_question,
            query_preprocessed=query_preprocessed,
            no_match_reason="master_index_missing_or_empty",
        )

    query_tokens = preprocess_tokens(user_question)
    if not query_tokens:
        return _memory_retrieval_result(
            enabled=True,
            scenario=scenario_id,
            query_original=user_question,
            query_preprocessed=query_preprocessed,
            no_match_reason="empty_query_after_preprocessing",
        )

    if any(token in UNSAFE_QUERY_TERMS for token in query_tokens):
        return _memory_retrieval_result(
            enabled=True,
            scenario=scenario_id,
            query_original=user_question,
            query_preprocessed=query_preprocessed,
            no_match_reason="unsafe_or_non_analytical_query",
        )

    template_tokens = [preprocess_tokens(str(record.get("searchable_text", ""))) for record in records]
    documents = [*template_tokens, query_tokens]
    idf = _idf(documents)
    query_vector = _tfidf_vector(query_tokens, idf)

    scored: list[tuple[float, dict[str, Any], list[str]]] = []
    for record, tokens in zip(records, template_tokens):
        score = _cosine_similarity(query_vector, _tfidf_vector(tokens, idf))
        matched_terms = [token for token in query_tokens if token in set(tokens)]
        if score >= min_score:
            scored.append((score, record, matched_terms))

    scored.sort(key=lambda item: (-item[0], str(item[1].get("id", ""))))
    selected = scored[: max(0, top_k)]
    if not selected:
        return _memory_retrieval_result(
            enabled=True,
            scenario=scenario_id,
            query_original=user_question,
            query_preprocessed=query_preprocessed,
            no_match_reason="no_template_above_threshold",
        )

    ambiguous = (
        len(selected) > 1
        and selected[0][0] - selected[1][0] < ambiguity_delta
    )
    candidates = [
        {
            "template_id": record.get("id", ""),
            "score": round(score, 6),
            "path": record.get("path", ""),
            "intent": record.get("intent", ""),
            "title": record.get("title", ""),
            "matched_terms": matched_terms,
            "required_tables": record.get("tables", []),
            "required_columns": record.get("columns", []),
            "passed_threshold": True,
        }
        for score, record, matched_terms in selected
    ]

    return _memory_retrieval_result(
        enabled=True,
        scenario=scenario_id,
        query_original=user_question,
        query_preprocessed=query_preprocessed,
        candidates=candidates,
        ambiguous=ambiguous,
    )
