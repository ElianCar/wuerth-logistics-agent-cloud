from __future__ import annotations

from datetime import datetime
import re
from uuid import uuid4


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _suffix() -> str:
    return uuid4().hex[:4]


def _readable_id(prefix: str) -> str:
    return f"{prefix}_{_timestamp()}_{_suffix()}"


def generate_run_id() -> str:
    return _readable_id("run")


def generate_feedback_id() -> str:
    return _readable_id("fb")


def generate_candidate_id() -> str:
    return _readable_id("cand")


def _slugify(value: str | None) -> str:
    if not value:
        return "solution_template"
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug[:48].strip("_") or "solution_template"


def generate_template_id(intent: str | None = None) -> str:
    return f"tmpl_{_slugify(intent)}_{_timestamp()}_{_suffix()}"


def generate_audit_id() -> str:
    return _readable_id("audit")
