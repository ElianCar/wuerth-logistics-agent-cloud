from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

import yaml

from src.agent.logging_utils import get_log_dir
from src.config.scenarios import get_active_scenario


def get_solution_templates_path() -> Path:
    return get_active_scenario().memory_dir / "solution_templates.yaml"


def _log_retrieval_error(message: str) -> None:
    try:
        log_path = get_log_dir() / "memory_retriever_errors.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as file:
            file.write(f"{timestamp} {message}\n")
    except OSError:
        pass


def _load_solution_templates() -> list[dict[str, Any]]:
    path = get_solution_templates_path()
    if not path.exists() or path.stat().st_size == 0:
        return []

    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except yaml.YAMLError as error:
        _log_retrieval_error(f"Invalid YAML in {path}: {error}")
        return []
    except OSError as error:
        _log_retrieval_error(f"Could not read {path}: {error}")
        return []

    templates = data.get("templates", [])
    if not isinstance(templates, list):
        _log_retrieval_error(f"{path} does not contain a templates list.")
        return []
    return [template for template in templates if isinstance(template, dict)]


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_]+", value.lower())
        if len(token) > 2
    }


def _template_score(question: str, template: dict[str, Any]) -> int:
    question_lower = question.lower()
    question_tokens = _tokens(question)
    score = 0

    intent = str(template.get("intent", ""))
    if intent and intent.lower() in question_lower:
        score += 10
    score += len(question_tokens & _tokens(intent)) * 2

    trigger_phrases = template.get("trigger_phrases", [])
    if isinstance(trigger_phrases, list):
        for phrase in trigger_phrases:
            phrase_text = str(phrase)
            if phrase_text and phrase_text.lower() in question_lower:
                score += 20
            score += len(question_tokens & _tokens(phrase_text))

    return score


def load_approved_solution_templates(
    question: str,
    max_templates: int = 3,
) -> list[dict[str, Any]]:
    scenario = get_active_scenario()
    templates = []
    for template in _load_solution_templates():
        if template.get("status") != "approved":
            continue
        if template.get("is_active") is not True:
            continue
        if template.get("scenario") != scenario.scenario_id:
            continue
        if template.get("dataset_id") != scenario.dataset_id:
            continue
        score = _template_score(question, template)
        if score > 0:
            templates.append((score, template))

    templates.sort(key=lambda item: item[0], reverse=True)
    return [template for _score, template in templates[:max_templates]]
