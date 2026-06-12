from __future__ import annotations

from typing import Literal

PackMode = Literal["lite", "balanced", "deep"]

ACTIVE_MODES: tuple[str, ...] = ("lite", "balanced", "deep")
LEGACY_MODE_ALIASES: dict[str, str] = {"minimal": "balanced"}
REQUESTED_MODES: tuple[str, ...] = ACTIVE_MODES + tuple(LEGACY_MODE_ALIASES)
MODE_HELP = "lite|balanced|deep"


def normalize_mode(mode: str | None) -> str:
    value = (mode or "balanced").strip().lower()
    return LEGACY_MODE_ALIASES.get(value, value)


def is_requested_mode(value: str | None) -> bool:
    return (value or "").strip().lower() in REQUESTED_MODES


def invalid_mode_message(value: str) -> str:
    return f"Unknown mode: {value}. Use {MODE_HELP}."
