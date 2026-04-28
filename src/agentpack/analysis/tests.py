from __future__ import annotations

from pathlib import Path

_TEST_PATTERNS = [
    # Python
    lambda stem, parent: f"tests/{parent}/test_{stem}.py",
    lambda stem, parent: f"test_{stem}.py",
    lambda stem, parent: f"tests/test_{stem}.py",
    # JS/TS
    lambda stem, parent: f"{stem}.test.ts",
    lambda stem, parent: f"{stem}.spec.ts",
    lambda stem, parent: f"{stem}.test.js",
    lambda stem, parent: f"{stem}.spec.js",
    lambda stem, parent: f"__tests__/{stem}.test.ts",
    lambda stem, parent: f"__tests__/{stem}.test.js",
]


def find_related_tests(path: str, all_paths: set[str]) -> list[str]:
    p = Path(path)
    stem = p.stem
    parent = p.parent.name

    results: list[str] = []
    for pattern_fn in _TEST_PATTERNS:
        candidate = pattern_fn(stem, parent)
        if candidate in all_paths:
            results.append(candidate)
    return results
