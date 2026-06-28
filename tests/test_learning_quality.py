from agentpack.learning.models import AgentLesson, LearningCard, LearningReport, LearningSourceFile, QuizQuestion, SkillEvidence
from agentpack.learning.quality import score_learning_report
from agentpack.core.models import Citation


def _cite(path: str, claim_id: str) -> Citation:
    return Citation(path=path, start_line=1, end_line=1, kind="summary", claim_id=claim_id)


def test_quality_gate_rewards_grounded_learning_not_generic_journal():
    report = LearningReport(
        task="Add AgentPack Learn",
        scope="task",
        source_files=[
            LearningSourceFile(
                path="src/agentpack/commands/learn.py",
                change_kind="added",
                why="Added CLI behavior.",
                concepts=["CLI design"],
                citations=[_cite("src/agentpack/commands/learn.py", "source")],
            )
        ],
        summary=["Worked on: Add AgentPack Learn"],
        concepts=["CLI design"],
        decisions=["Keep learning inside the CLI."],
        risks=["Output can become generic."],
        tests=["Updated tests/test_learn_command.py for CLI behavior."],
        claim_citations={
            "summary:1": [_cite("src/agentpack/commands/learn.py", "summary")],
            "decision:1": [_cite("src/agentpack/commands/learn.py", "decision")],
            "risk:1": [_cite("src/agentpack/commands/learn.py", "risk")],
            "test:1": [_cite("src/agentpack/commands/learn.py", "test")],
        },
        learning_cards=[
            LearningCard(
                title="CLI Design",
                body="Commands need predictable output.",
                files=["src/agentpack/commands/learn.py"],
                citations=[_cite("src/agentpack/commands/learn.py", "card")],
            )
        ],
        agent_lessons=[
            AgentLesson(
                rule="When editing CLI commands, update docs and CLI tests.",
                evidence_files=["src/agentpack/commands/learn.py"],
                citations=[_cite("src/agentpack/commands/learn.py", "lesson")],
            )
        ],
        skill_evidence=[
            SkillEvidence(
                skill="CLI design",
                task="Add AgentPack Learn",
                evidence_files=["src/agentpack/commands/learn.py"],
                confidence=80,
                citations=[_cite("src/agentpack/commands/learn.py", "skill")],
            )
        ],
        quiz=[
            QuizQuestion(
                question="What makes CLI output automation-friendly?",
                answer="Stable output and deterministic exit codes.",
            )
        ],
    )

    result = score_learning_report(report)

    assert result.score >= 70
    assert result.issues == []
    assert result.citation_coverage == 1.0


def test_quality_gate_flags_generic_output_without_evidence():
    report = LearningReport(
        task="Fix stuff",
        scope="task",
        summary=["Worked on code."],
        learning_cards=[LearningCard(title="Development", body="You wrote code.", files=[])],
    )

    result = score_learning_report(report)

    assert result.score < 70
    assert "No changed-file evidence" in result.issues
    assert "No claim-level citations" in result.issues
    assert "No agent lessons" in result.issues


def test_quality_gate_flags_file_evidence_without_claim_citations():
    report = LearningReport(
        task="Add AgentPack Learn",
        scope="task",
        source_files=[
            LearningSourceFile(
                path="src/agentpack/commands/learn.py",
                change_kind="added",
                why="Added CLI behavior.",
                concepts=["CLI design"],
            )
        ],
        concepts=["CLI design"],
        learning_cards=[
            LearningCard(title="CLI Design", body="Commands need predictable output.", files=["src/agentpack/commands/learn.py"])
        ],
        agent_lessons=[
            AgentLesson(rule="When editing CLI commands, update docs and CLI tests.", evidence_files=["src/agentpack/commands/learn.py"])
        ],
        skill_evidence=[
            SkillEvidence(skill="CLI design", task="Add AgentPack Learn", evidence_files=["src/agentpack/commands/learn.py"], confidence=80)
        ],
        quiz=[
            QuizQuestion(question="Why cite claims?", answer="To prove learning output came from source evidence.")
        ],
    )

    result = score_learning_report(report)

    assert "No claim-level citations" in result.issues
    assert "Uncited learning claims" in result.issues
    assert result.citation_coverage == 0.0
