from __future__ import annotations

import json
from typing import Any


def render_toon(value: Any, *, root_name: str | None = None) -> str:
    lines: list[str] = ["@format toon"]
    if root_name:
        lines.append(f"@root {root_name}")
    lines.extend(_render_value(value, indent=0, key=None))
    return "\n".join(lines).rstrip() + "\n"


def is_toon_friendly(value: Any) -> bool:
    return _max_depth(value) <= 3 and not _has_mixed_sequence(value)


def _render_value(value: Any, *, indent: int, key: str | None) -> list[str]:
    prefix = " " * indent

    if isinstance(value, dict):
        if key is not None:
            header = f"{prefix}{key}:"
            body = _render_mapping(value, indent=indent + 2)
            return [header, *body]
        return _render_mapping(value, indent=indent)

    if isinstance(value, list):
        return _render_list(value, indent=indent, key=key)

    if key is None:
        return [f"{prefix}{_format_scalar(value)}"]
    return [f"{prefix}{key}: {_format_scalar(value)}"]


def _render_mapping(value: dict[str, Any], *, indent: int) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for key, item in value.items():
        safe_key = _format_key(str(key))
        if _is_scalar(item):
            lines.append(f"{prefix}{safe_key}: {_format_scalar(item)}")
            continue
        lines.extend(_render_value(item, indent=indent, key=safe_key))
    if not lines:
        lines.append(f"{prefix}{{}}")
    return lines


def _render_list(value: list[Any], *, indent: int, key: str | None) -> list[str]:
    prefix = " " * indent
    if _is_uniform_object_array(value):
        headers = list(value[0].keys()) if value else []
        header_text = "|".join(_format_key(str(name)) for name in headers)
        if key is None:
            lines = [f"{prefix}[{header_text}]:"]
        else:
            lines = [f"{prefix}{key}[{header_text}]:"]
        for row in value:
            parts = [_format_cell(row.get(name)) for name in headers]
            lines.append(f"{prefix}  - {' | '.join(parts)}")
        return lines

    if key is not None:
        lines = [f"{prefix}{key}[]:"]
        next_indent = indent + 2
    else:
        lines = []
        next_indent = indent
    item_prefix = " " * next_indent

    if not value:
        lines.append(f"{item_prefix}[]")
        return lines

    for item in value:
        if _is_scalar(item):
            lines.append(f"{item_prefix}- {_format_scalar(item)}")
            continue
        lines.append(f"{item_prefix}-")
        lines.extend(_render_value(item, indent=next_indent + 2, key=None))
    return lines


def _format_cell(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return _format_scalar(value)


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return json.dumps(value, sort_keys=True)
    if _safe_string(value):
        return value
    return json.dumps(value)


def _safe_string(value: str) -> bool:
    if not value or value != value.strip():
        return False
    forbidden = {"\n", "\r", "\t", "|", '"'}
    return not any(char in value for char in forbidden)


def _format_key(value: str) -> str:
    return value.replace(" ", "_")


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _is_uniform_object_array(value: list[Any]) -> bool:
    if not value or not all(isinstance(item, dict) for item in value):
        return False
    headers = list(value[0].keys())
    if not headers:
        return False
    for item in value:
        if list(item.keys()) != headers:
            return False
        if any(isinstance(field, (dict, list)) for field in item.values()):
            return False
    return True


def _max_depth(value: Any, depth: int = 0) -> int:
    if isinstance(value, dict):
        return max((_max_depth(item, depth + 1) for item in value.values()), default=depth + 1)
    if isinstance(value, list):
        return max((_max_depth(item, depth + 1) for item in value), default=depth + 1)
    return depth


def _has_mixed_sequence(value: Any) -> bool:
    if isinstance(value, list):
        if not value:
            return False
        kinds = {type(item) for item in value}
        if len(kinds) > 1:
            return True
        return any(_has_mixed_sequence(item) for item in value)
    if isinstance(value, dict):
        return any(_has_mixed_sequence(item) for item in value.values())
    return False
