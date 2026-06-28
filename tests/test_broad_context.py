from pathlib import Path

from agentpack.analysis.broad_context import build_broad_context
from agentpack.application.pack_service import PackRequest, PackService
from agentpack.core.models import FileInfo


def test_pack_renders_broad_context_for_share_task(tmp_path: Path) -> None:
    (tmp_path / ".agentpack").mkdir()
    (tmp_path / ".agentpack" / "config.toml").write_text(
        "[context]\ndefault_budget = 12000\nmax_file_tokens = 4000\nbroad_context = \"auto\"\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"demo\"\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "src" / "auth").mkdir(parents=True)
    (tmp_path / "src" / "auth" / "routes.py").write_text(
        "def login():\n    return 'ok'\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text("def test_login():\n    assert True\n", encoding="utf-8")

    result = PackService().run(PackRequest(
        root=tmp_path,
        agent="generic",
        task="share broad repo context for review",
        mode="deep",
        budget=0,
        since=None,
        refresh=True,
        task_source="test",
    ))

    assert result.pack.broad_context is not None
    assert any(
        citation.support_text
        for module in result.pack.broad_context.module_summaries
        for citation in module.citations
    )
    rendered = (tmp_path / ".agentpack" / "context.md").read_text(encoding="utf-8")
    assert "## Broad Repo Context" in rendered
    assert "## Module Summaries" in rendered
    assert "## Sharing Receipts" in rendered


def test_broad_context_builds_semantic_clusters(tmp_path: Path) -> None:
    file_info = FileInfo(
        path="src/auth.py",
        abs_path=tmp_path / "src" / "auth.py",
        language="python",
        size_bytes=10,
        estimated_tokens=5,
    )

    context = build_broad_context(
        files=[file_info],
        summaries={"src/auth.py": {"role": "authentication", "summary": "Auth entrypoint"}},
        scored=[(file_info, 100.0, ["filename keyword match"])],
        intent="share",
        max_module_summaries=10,
        max_inventory_files=10,
        budget_tokens=2000,
    )

    assert context.semantic_clusters == ["authentication: src/auth.py"]
