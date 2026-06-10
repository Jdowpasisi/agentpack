from pathlib import Path

import pytest

from agentpack.learning.collector import LearningInputs
from agentpack.learning.models import LearningReport, LearningSourceFile
from agentpack.learning.provider import LearningProviderError, run_concept_provider_command, run_provider_command


def test_provider_command_merges_json_fields(tmp_path: Path):
    script = tmp_path / "provider.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "print(json.dumps({'summary': ['Provider taught: ' + payload['task']], 'next_practice': 'Provider drill'}))\n",
        encoding="utf-8",
    )
    report = LearningReport(task="Add provider", scope="task")

    enriched = run_provider_command(f"python {script}", report)

    assert enriched.summary == ["Provider taught: Add provider"]
    assert enriched.next_practice == "Provider drill"


def test_provider_command_rejects_invalid_json(tmp_path: Path):
    script = tmp_path / "provider.py"
    script.write_text("print('not json')\n", encoding="utf-8")

    with pytest.raises(LearningProviderError):
        run_provider_command(f"python {script}", LearningReport(task="Add provider", scope="task"))


def test_concept_provider_command_adds_concepts_and_topics(tmp_path: Path):
    script = tmp_path / "concept_provider.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "assert payload['changed_files'][0]['diff_excerpt']\n"
        "print(json.dumps({\n"
        "  'concepts': ['distributed locking'],\n"
        "  'source_file_concepts': {'src/lock.py': ['distributed locking']},\n"
        "  'learning_topics': [{\n"
        "    'title': 'Distributed Locking',\n"
        "    'why': 'Study lock ownership, expiry, and contention.',\n"
        "    'prompt': 'Teach me distributed locking from this task.',\n"
        "    'files': ['src/lock.py'],\n"
        "    'concepts': ['distributed locking']\n"
        "  }]\n"
        "}))\n",
        encoding="utf-8",
    )
    inputs = LearningInputs(
        task="Add Redis lock",
        since="HEAD~1",
        changed_files={"src/lock.py": "modified"},
        diffs={"src/lock.py": "+ redis.set(lock_key, owner, nx=True, ex=ttl)\n"},
    )
    report = LearningReport(
        task="Add Redis lock",
        scope="task",
        since="HEAD~1",
        source_files=[LearningSourceFile(path="src/lock.py", change_kind="modified", why="Modified implementation.")],
        concepts=["caching"],
    )

    enriched = run_concept_provider_command(f"python {script}", inputs, report)

    assert enriched.concepts == ["caching", "distributed locking"]
    assert enriched.source_files[0].concepts == ["distributed locking"]
    assert enriched.learning_topics[0].title == "Distributed Locking"


def test_concept_provider_command_rejects_invalid_json(tmp_path: Path):
    script = tmp_path / "concept_provider.py"
    script.write_text("print('not json')\n", encoding="utf-8")
    inputs = LearningInputs(task="Add provider", since=None, changed_files={}, diffs={})

    with pytest.raises(LearningProviderError):
        run_concept_provider_command(f"python {script}", inputs, LearningReport(task="Add provider", scope="task"))
