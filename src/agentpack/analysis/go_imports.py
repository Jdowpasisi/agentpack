from __future__ import annotations

import re
from pathlib import Path

_SINGLE = re.compile(r'^import\s+"([^"]+)"', re.MULTILINE)
_BLOCK_START = re.compile(r"^import\s+\(", re.MULTILINE)
_BLOCK_ENTRY = re.compile(r'^\s+(?:\w+\s+)?"([^"]+)"')


def extract_imports(path: Path, text: str | None = None) -> list[str]:
    if text is None:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return []

    imports: list[str] = []
    imports.extend(m.group(1) for m in _SINGLE.finditer(text))

    for block_m in _BLOCK_START.finditer(text):
        rest = text[block_m.end():]
        end = rest.find(")")
        if end == -1:
            continue
        block = rest[:end]
        for line in block.splitlines():
            m = _BLOCK_ENTRY.match(line)
            if m:
                imports.append(m.group(1))

    return imports
