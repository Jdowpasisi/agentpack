from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = ROOT / ".codex-plugin" / "plugin.json"
SKILLS_DIR = ROOT / "skills"


def test_codex_plugin_manifest_points_to_skills() -> None:
    manifest = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))

    assert manifest["name"] == "agentpack"
    assert manifest["skills"] == "./skills/"
    assert manifest["interface"]["displayName"] == "AgentPack"
    description = " ".join(
        [
            manifest["description"],
            manifest["interface"]["shortDescription"],
            manifest["interface"]["longDescription"],
        ]
    ).lower()
    assert "local context engine" in description
    assert "not a coding agent" in description


def test_codex_plugin_skills_delegate_to_existing_cli() -> None:
    expected = {
        "agentpack.md",
        "agentpack-route.md",
        "agentpack-pack.md",
        "agentpack-refresh.md",
        "agentpack-review.md",
    }

    assert {path.name for path in SKILLS_DIR.glob("*.md")} == expected

    combined = "\n".join(path.read_text(encoding="utf-8") for path in SKILLS_DIR.glob("*.md"))
    assert "agentpack route --task" in combined
    assert "agentpack task set" in combined
    assert "agentpack pack --task auto" in combined
    assert "agentpack guard --agent codex --repair-stale --refresh-context" in combined
    assert "agentpack benchmark capture --since main --task" in combined
    assert "not a coding agent" in combined.lower()
    assert "map, not proof" in combined.lower()


def test_codex_plugin_docs_keep_local_first_boundary() -> None:
    docs = (ROOT / "docs" / "codex-plugin.md").read_text(encoding="utf-8").lower()

    assert "local context engine, not a coding agent" in docs
    assert "does not upload code" in docs
    assert "does not reimplement ranking, scanning, packing, mcp, or benchmarking" in docs
    assert "@agentpack-route" in docs
    assert "@agentpack-pack" in docs


def test_agent_plugin_distribution_docs_cover_supported_hosts() -> None:
    docs = (ROOT / "docs" / "agent-plugins.md").read_text(encoding="utf-8").lower()

    for host in (
        "codex",
        "claude code",
        "cursor",
        "windsurf",
        "github copilot",
        "cline",
        "kiro",
        "opencode",
        "antigravity",
        "generic",
    ):
        assert host in docs

    assert "does not reimplement ranking, scanning, packing, mcp, or benchmarking" in docs
    assert "local context engine, not a coding agent" in docs
    assert "agentpack guard --agent <agent> --repair-stale --refresh-context" in docs
    assert "native-integrations/cursor-extension/" in docs
    assert "native-integrations/windsurf-extension/" in docs


def test_portable_agent_rules_exist_for_common_hosts() -> None:
    paths = [
        "agent-rules/agentpack.md",
        ".cursorrules",
        ".cursor/rules/agentpack.mdc",
        ".windsurf/rules/agentpack.md",
        ".github/copilot-instructions.md",
        ".clinerules/agentpack.md",
        ".kiro/steering/agentpack.md",
        ".opencode/agentpack.md",
    ]

    for rel in paths:
        text = (ROOT / rel).read_text(encoding="utf-8")
        lower = text.lower()
        assert "agentpack" in lower
        assert ".agentpack/context.md" in text or "agentpack route --task" in text
        assert "agentpack pack --task auto" in text or "agentpack guard --agent" in text
        assert "starting map, not proof" in lower or "starting points" in lower
