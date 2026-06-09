from agentpack.learning.feedback import apply_feedback_to_report, load_feedback_summary, record_learning_feedback
from agentpack.learning.models import AgentLesson, LearningCard, LearningReport, LearningSourceFile, SkillEvidence


def _report() -> LearningReport:
    return LearningReport(
        task="Add learning feedback",
        scope="task",
        source_files=[
            LearningSourceFile(
                path="src/agentpack/commands/learn.py",
                change_kind="modified",
                why="Modified CLI behavior.",
                concepts=["CLI design"],
            )
        ],
        concepts=["CLI design"],
        learning_cards=[
            LearningCard(
                title="CLI design",
                body="Commands need stable output.",
                files=["src/agentpack/commands/learn.py"],
            )
        ],
        agent_lessons=[
            AgentLesson(
                rule="When editing CLI commands, update command docs and CLI tests.",
                evidence_files=["src/agentpack/commands/learn.py"],
            )
        ],
        skill_evidence=[
            SkillEvidence(
                skill="CLI design",
                task="Add learning feedback",
                evidence_files=["src/agentpack/commands/learn.py"],
                confidence=80,
            )
        ],
    )


def test_feedback_summary_tracks_targeted_suppression(tmp_path):
    path = tmp_path / ".agentpack" / "learning-feedback.jsonl"

    record_learning_feedback(path, _report(), "not-helpful", "too noisy", "skill:CLI design")
    summary = load_feedback_summary(path)
    updated = apply_feedback_to_report(_report(), summary)

    assert "CLI design" in summary.suppressed_skills
    assert updated.concepts == []
    assert updated.skill_evidence == []


def test_feedback_summary_marks_helpful_lessons_accepted(tmp_path):
    path = tmp_path / ".agentpack" / "learning-feedback.jsonl"

    record_learning_feedback(path, _report(), "helpful", "good reminder", "skill:CLI design")
    summary = load_feedback_summary(path)
    updated = apply_feedback_to_report(_report(), summary)

    assert updated.agent_lessons[0].status == "accepted"
    assert updated.agent_lessons[0].confidence >= 90
    assert updated.skill_evidence[0].confidence == 90


def test_feedback_summary_applies_skill_rename(tmp_path):
    path = tmp_path / ".agentpack" / "learning-feedback.jsonl"

    record_learning_feedback(path, _report(), "helpful", "better name", "rename:CLI design=>CLI workflow design")
    summary = load_feedback_summary(path)
    updated = apply_feedback_to_report(_report(), summary)

    assert updated.concepts == ["CLI workflow design"]
    assert updated.skill_evidence[0].skill == "CLI workflow design"
