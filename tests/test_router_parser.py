from __future__ import annotations

from agentpack.router.parser import parse_rule_file, parse_skill_file


def test_parse_skill_frontmatter_name_description(tmp_path):
    skill_dir = tmp_path / ".codex" / "skills" / "django-pytest"
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\n"
        "name: django-pytest\n"
        "description: Use for Django test debugging and pytest workflows.\n"
        "---\n\n"
        "## When to use\n"
        "Use this when debugging pytest fixtures, mocks, and flaky Django tests.\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)

    assert skill.name == "django-pytest"
    assert skill.description == "Use for Django test debugging and pytest workflows."
    assert "pytest" in skill.triggers
    assert "pytest" in skill.tools_required
    assert skill.side_effect_level == "command"


def test_parse_skill_rich_frontmatter(tmp_path):
    path = tmp_path / ".agentpack" / "skills" / "pytest-debugging" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "name: pytest-debugging\n"
        "description: Debug failing Python tests.\n"
        "domains: [quality, testing]\n"
        "task_types: [debug, test]\n"
        "languages: [python]\n"
        "frameworks: [pytest]\n"
        "triggers:\n"
        "  - assertion error\n"
        "anti_triggers: [frontend, playwright]\n"
        "applies_to_paths: tests/**/*.py\n"
        "anti_paths:\n"
        "  - apps/web/**\n"
        "priority: 70\n"
        "confidence_threshold: 0.6\n"
        "---\n\n"
        "Run targeted pytest commands.\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)

    assert skill.domains == ["quality", "testing"]
    assert skill.task_types == ["debug", "test"]
    assert skill.languages == ["python"]
    assert skill.frameworks == ["pytest"]
    assert "assertion error" in skill.triggers
    assert skill.anti_triggers == ["frontend", "playwright"]
    assert skill.applies_to_paths == ["tests/**/*.py"]
    assert skill.anti_paths == ["apps/web/**"]
    assert skill.priority == 70
    assert skill.confidence_threshold == 0.6


def test_parse_karpathy_skill_frontmatter(tmp_path):
    path = tmp_path / "skills" / "karpathy-guidelines" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "name: karpathy-guidelines\n"
        "description: Behavioral guidelines to reduce common LLM coding mistakes. Use when writing, reviewing, or refactoring code to avoid overcomplication, make surgical changes, surface assumptions, and define verifiable success criteria.\n"
        "license: MIT\n"
        "---\n\n"
        "# Karpathy Guidelines\n\n"
        "Behavioral guidelines to reduce common LLM coding mistakes.\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)

    assert skill.name == "karpathy-guidelines"
    assert "refactoring" in skill.triggers
    assert skill.side_effect_level == "none"


def test_parse_skill_inferred_triggers_use_dynamic_description_evidence(tmp_path):
    path = tmp_path / ".claude" / "skills" / "golang-pro" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "name: golang-pro\n"
        "description: Implements concurrent Go patterns using goroutines and channels, designs and builds microservices with gRPC or REST.\n"
        "---\n\n"
        "Use this when building production Go applications.\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)

    assert "golang" in skill.triggers
    assert "go" in skill.triggers
    assert "goroutine" in skill.triggers
    assert "channel" in skill.triggers
    assert "microservice" in skill.triggers
    assert "grpc" in skill.triggers
    assert "rest" in skill.triggers
    assert "applications" not in skill.triggers
    assert "application" not in skill.triggers
    assert "building" not in skill.triggers
    assert "builds" not in skill.triggers
    assert "designs" not in skill.triggers
    assert "implements" not in skill.triggers


def test_parse_skill_inferred_triggers_prioritize_invoke_for_clause(tmp_path):
    path = tmp_path / ".claude" / "skills" / "graphql-architect" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "name: graphql-architect\n"
        "description: Use when designing GraphQL schemas. Invoke for schema design, resolvers with DataLoader, query optimization, federation directives.\n"
        "---\n\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)
    visible = [trigger for trigger in skill.triggers if trigger not in {"graphql-architect", "graphql", "architect"}]

    assert visible[:4] == ["schema-design", "schema", "design", "resolver-dataloader"]
    assert "dataloader" in visible
    assert "query-optimization" in visible


def test_parse_skill_inferred_triggers_keep_compound_domain_phrases(tmp_path):
    path = tmp_path / ".claude" / "skills" / "graphify" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "name: graphify\n"
        "description: Any input (code, docs, papers, images) to knowledge graph to clustered communities to HTML, JSON, and audit report.\n"
        "---\n\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)

    assert "knowledge-graph" in skill.triggers
    assert "audit-report" in skill.triggers
    assert "html" in skill.triggers
    assert "json" in skill.triggers
    assert "any" not in skill.triggers
    assert "input" not in skill.triggers
    assert "clustered" not in skill.triggers
    assert "communities" not in skill.triggers


def test_parse_skill_inferred_triggers_canonicalize_plural_duplicates(tmp_path):
    path = tmp_path / ".claude" / "skills" / "graphql-architect" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "name: graphql-architect\n"
        "description: Use when designing GraphQL schemas and schema resolvers with Apollo Federation and real-time subscriptions.\n"
        "---\n\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)

    assert "schema" in skill.triggers
    assert "schemas" not in skill.triggers
    assert skill.triggers.count("schema") == 1
    assert "real-time" in skill.triggers


def test_parse_skill_h1_fallback_and_dangerous_external(tmp_path):
    path = tmp_path / ".agentpack" / "skills" / "deploy" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Production Deploy\n\n"
        "Deploy to cloud, migrate the database, and send Slack updates.\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(path, root=tmp_path)

    assert skill.name == "Production Deploy"
    assert skill.side_effect_level == "external"


def test_parse_cursor_mdc_rule_frontmatter(tmp_path):
    path = tmp_path / ".cursor" / "rules" / "tests.mdc"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "description: Test rules\n"
        "globs: tests/**, */tests/**\n"
        "---\n\n"
        "Always write focused tests.\n",
        encoding="utf-8",
    )

    rule = parse_rule_file(path, root=tmp_path, source=".cursor/rules", priority=60)

    assert rule.name == "tests.mdc"
    assert rule.description == "Test rules"
    assert rule.scope_paths == ["tests/**", "*/tests/**"]
    assert rule.priority == 60
