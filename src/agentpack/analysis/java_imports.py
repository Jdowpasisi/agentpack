from __future__ import annotations

import re
from pathlib import Path

_IMPORT = re.compile(r"^import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;", re.MULTILINE)
_KOTLIN_IMPORT = re.compile(r"^import\s+([\w.]+(?:\.\*)?)", re.MULTILINE)


def extract_imports(path: Path) -> list[str]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []

    suffix = path.suffix.lower()
    pattern = _KOTLIN_IMPORT if suffix == ".kt" else _IMPORT
    return [m.group(1) for m in pattern.finditer(text)]
