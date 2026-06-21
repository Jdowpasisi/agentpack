from __future__ import annotations

import json
import subprocess
from io import BytesIO

from agentpack.session.references import collect_repo_issue_references, extract_issue_references, merge_issue_references


def test_extract_issue_references_handles_common_tracker_formats():
    refs = extract_issue_references(
        "Fix #123 and GH-456",
        "https://github.com/acme/app/issues/789,",
        "branch feature/PLAT-321-login",
        "repeat #123",
    )

    assert refs == [
        "#123",
        "GH-456",
        "https://github.com/acme/app/issues/789",
        "PLAT-321",
    ]


def test_merge_issue_references_dedupes_case_insensitively():
    assert merge_issue_references(["GH-1", "gh-1", "#2"]) == ["GH-1", "#2"]


def test_collect_repo_issue_references_reads_branch_commits_and_gh(tmp_path, monkeypatch):
    commands: list[list[str]] = []

    def fake_git(args, cwd):
        if args[:3] == ["git", "rev-parse", "--is-inside-work-tree"]:
            return "true\n"
        if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return "feature/PLAT-777-memory"
        if args[:3] == ["git", "log", "-5"]:
            return "fix linked GH-42\n"
        return None

    def fake_run(args, **kwargs):
        commands.append(args)
        if args[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({
                    "number": 9,
                    "title": "Improve memory references",
                    "state": "OPEN",
                    "url": "https://github.com/acme/app/pull/9",
                    "labels": [{"name": "memory"}],
                    "closingIssuesReferences": [
                        {
                            "number": 42,
                            "title": "Track issue refs",
                            "state": "OPEN",
                            "url": "https://github.com/acme/app/issues/42",
                            "labels": [{"name": "bug"}],
                        }
                    ],
                }),
                "",
            )
        if args[:3] == ["gh", "issue", "view"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({
                    "number": int(args[3]),
                    "title": "Issue title",
                    "state": "OPEN",
                    "url": f"https://github.com/acme/app/issues/{args[3]}",
                    "labels": [{"name": "triage"}],
                }),
                "",
            )
        return subprocess.CompletedProcess(args, 1, "", "nope")

    monkeypatch.setattr("agentpack.core.git._run", fake_git)
    monkeypatch.setattr("subprocess.run", fake_run)

    refs = collect_repo_issue_references(tmp_path, "Fix #42")
    payload = [item.to_dict() for item in refs]

    assert [item["ref"] for item in payload] == ["#42", "PLAT-777", "GH-42", "PR #9"]
    assert payload[0]["title"] == "Track issue refs"
    assert payload[-1]["kind"] == "github_pr"
    assert any(command[:3] == ["gh", "pr", "view"] for command in commands)


def test_collect_repo_issue_references_enriches_jira_when_configured(tmp_path, monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return BytesIO(json.dumps({
                "fields": {
                    "summary": "Memory tracker bug",
                    "status": {"name": "In Progress"},
                    "labels": ["agentpack"],
                }
            }).encode("utf-8")).read()

    requests = []

    def fake_git(args, cwd):
        if args[:3] == ["git", "rev-parse", "--is-inside-work-tree"]:
            return "true\n"
        return None

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, timeout, request.headers))
        return FakeResponse()

    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
    monkeypatch.setenv("JIRA_EMAIL", "dev@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")
    monkeypatch.setattr("agentpack.core.git._run", fake_git)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", ""))

    refs = collect_repo_issue_references(tmp_path, "Fix PLAT-321")
    payload = [item.to_dict() for item in refs]

    assert payload[0]["ref"] == "PLAT-321"
    assert payload[0]["title"] == "Memory tracker bug"
    assert payload[0]["state"] == "In Progress"
    assert payload[0]["labels"] == ["agentpack"]
    assert requests[0][0] == "https://jira.example.com/rest/api/3/issue/PLAT-321?fields=summary,status,labels"
    assert "Authorization" in requests[0][2]
