from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DOCS = [
    ROOT / "README.md",
    ROOT / "docs/architecture.md",
    ROOT / "docs/commands.md",
    ROOT / "docs/configuration.md",
    ROOT / "docs/integrations.md",
    ROOT / "docs/benchmarking.md",
    ROOT / "docs/development.md",
    ROOT / "docs/limitations.md",
]


LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def test_root_readme_is_lean() -> None:
    line_count = len((ROOT / "README.md").read_text(encoding="utf-8").splitlines())

    assert line_count <= 500


def test_split_docs_exist() -> None:
    for path in DOCS:
        assert path.exists(), f"missing {path}"


def test_local_markdown_links_have_targets() -> None:
    for path in DOCS + [ROOT / "benchmarks/README.md"]:
        text = path.read_text(encoding="utf-8")
        for target in LINK_RE.findall(text):
            if _is_external_or_fragment(target):
                continue
            target_path = target.split("#", 1)[0]
            resolved = (path.parent / target_path).resolve()
            assert resolved.exists(), f"{path} links to missing {target}"


def _is_external_or_fragment(target: str) -> bool:
    return (
        target.startswith("#")
        or target.startswith("http://")
        or target.startswith("https://")
        or target.startswith("mailto:")
    )
