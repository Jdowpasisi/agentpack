from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from agentpack.core.config import load_config
from agentpack.core.token_estimator import estimate_tokens
from agentpack.renderers.toon import is_toon_friendly, render_toon

StructuredFormat = Literal["auto", "toon", "json"]


def to_machine(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def choose_llm_format(root: Path, value: Any, *, requested: StructuredFormat = "auto") -> Literal["toon", "json"]:
    if requested == "json":
        return "json"
    if requested == "toon":
        return "toon"

    cfg = load_config(root)
    configured = cfg.agentic.llm_structured_format
    if configured == "json":
        return "json"
    if configured == "toon":
        return "toon"
    if not cfg.agentic.enforce_llm_toon:
        return "json"

    if not is_toon_friendly(value):
        return "json"

    json_text = json.dumps(value, indent=2, sort_keys=True)
    toon_text = render_toon(value)
    if cfg.agentic.toon_fallback_when_larger and estimate_tokens(toon_text) >= estimate_tokens(json_text):
        return "json"
    return "toon"


def to_llm(root: Path, value: Any, *, requested: StructuredFormat = "auto", root_name: str | None = None) -> str:
    chosen = choose_llm_format(root, value, requested=requested)
    if chosen == "json":
        return to_machine(value)
    return render_toon(value, root_name=root_name)
