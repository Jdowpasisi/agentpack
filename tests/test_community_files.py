from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_community_files_exist() -> None:
    for rel in (
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/ISSUE_TEMPLATE/docs.yml",
        ".github/ISSUE_TEMPLATE/config.yml",
    ):
        assert (ROOT / rel).exists(), rel


def test_issue_templates_include_required_fields() -> None:
    for path in (ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        if path.name != "config.yml":
            assert "name:" in text, path
            assert "description:" in text, path
            assert "body:" in text, path
            assert "validations:" in text, path


def test_contributing_documents_route_json_alias() -> None:
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert 'agentpack route --task "<task>" --json' in text
