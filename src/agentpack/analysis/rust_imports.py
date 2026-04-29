from __future__ import annotations

import re
from pathlib import Path

# mod foo; / mod foo { — internal module declarations
_MOD = re.compile(r"^\s*(?:pub\s+)?mod\s+(\w+)\s*[;{]", re.MULTILINE)
# use foo::bar; / use foo::{bar, baz};
_USE = re.compile(r"^\s*(?:pub\s+)?use\s+([\w::{}, ]+)\s*;", re.MULTILINE)
# extern crate foo;
_EXTERN = re.compile(r"^\s*extern\s+crate\s+(\w+)\s*;", re.MULTILINE)


def extract_imports(path: Path, text: str | None = None) -> list[str]:
    if text is None:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return []

    imports: list[str] = []
    for m in _MOD.finditer(text):
        imports.append(m.group(1))
    for m in _USE.finditer(text):
        # strip whitespace and braces for a clean root crate name
        raw = m.group(1).split("::")[0].strip()
        if raw:
            imports.append(raw)
    for m in _EXTERN.finditer(text):
        imports.append(m.group(1))

    return list(dict.fromkeys(imports))  # deduplicate, preserve order
