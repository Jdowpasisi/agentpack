from pathlib import Path

import pytest

from agentpack.learning.models import LearningReport
from agentpack.learning.provider import LearningProviderError, run_provider_command


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
