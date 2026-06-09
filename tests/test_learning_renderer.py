from agentpack.learning.models import (
    AgentLesson,
    LearningCard,
    LearningReport,
    LearningSourceFile,
    QuizQuestion,
    SkillEvidence,
)
from agentpack.learning.renderers import (
    learning_report_to_dict,
    render_agent_lessons_markdown,
    render_learning_markdown,
)


def _report() -> LearningReport:
    return LearningReport(
        task="Add AgentPack Learn",
        scope="task",
        since="HEAD~1",
        source_files=[
            LearningSourceFile(
                path="src/agentpack/commands/learn.py",
                change_kind="added",
                why="Added CLI behavior.",
                concepts=["CLI design"],
            )
        ],
        summary=["Worked on: Add AgentPack Learn"],
        concepts=["CLI design"],
        decisions=["Keep learning in the existing CLI."],
        risks=["Summary output can become noisy."],
        tests=["Updated tests/test_learn_command.py for CLI behavior."],
        learning_cards=[
            LearningCard(
                title="CLI Design",
                body="Commands need explicit flags and predictable output.",
                files=["src/agentpack/commands/learn.py"],
            )
        ],
        quiz=[
            QuizQuestion(
                question="What makes CLI output automation-friendly?",
                answer="Stable output and deterministic exit codes.",
            )
        ],
        agent_lessons=[
            AgentLesson(
                rule="When editing CLI commands, update command docs and CLI tests.",
                evidence_files=["src/agentpack/commands/learn.py"],
                reason="CLI behavior is user-visible.",
            )
        ],
        skill_evidence=[
            SkillEvidence(
                skill="CLI design",
                task="Add AgentPack Learn",
                evidence_files=["src/agentpack/commands/learn.py"],
                confidence=80,
            )
        ],
        next_practice="Run the command with Markdown and JSON output.",
    )


def test_render_learning_markdown_contains_core_sections():
    rendered = render_learning_markdown(_report())

    assert "# AgentPack Learning Summary" in rendered
    assert "## Changed Files" in rendered
    assert "`src/agentpack/commands/learn.py`" in rendered
    assert "## Learning Cards" in rendered
    assert "## Agent Lessons" in rendered
    assert "## Skill Evidence" in rendered
    assert "## Quiz" in rendered


def test_learning_report_to_dict_is_json_safe():
    payload = learning_report_to_dict(_report())

    assert payload["task"] == "Add AgentPack Learn"
    assert payload["source_files"][0]["path"] == "src/agentpack/commands/learn.py"


def test_render_agent_lessons_markdown_is_context_pack_ready():
    rendered = render_agent_lessons_markdown(_report())

    assert "# Agent Lessons" in rendered
    assert "When editing CLI commands" in rendered
    assert "`src/agentpack/commands/learn.py`" in rendered
