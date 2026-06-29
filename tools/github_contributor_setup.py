from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT / ".github" / "contributor-labels.json"
ISSUES_PATH = ROOT / ".github" / "contributor-issues.json"
TOPICS_PATH = ROOT / ".github" / "repository-topics.json"
REPO = "vishal2612200/agentpack"


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply AgentPack contributor GitHub setup.")
    parser.add_argument("--apply", action="store_true", help="Create labels, topics, issues, and pins.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without changing GitHub.")
    args = parser.parse_args()

    apply = args.apply and not args.dry_run
    labels = _read_json(LABELS_PATH)
    issues = _read_json(ISSUES_PATH)
    topics = _read_json(TOPICS_PATH)

    _ensure_gh()
    _sync_topics(topics, apply=apply)
    _sync_labels(labels, apply=apply)
    created_or_existing = _sync_issues(issues, apply=apply)
    _pin_issues(issues, created_or_existing, apply=apply)

    mode = "applied" if apply else "dry-run"
    print(f"GitHub contributor setup {mode}.")
    return 0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_gh() -> None:
    _run(["gh", "auth", "status"], capture=True)


def _sync_topics(topics: list[str], *, apply: bool) -> None:
    existing = {
        item["name"]
        for item in _json(["gh", "repo", "view", REPO, "--json", "repositoryTopics"])["repositoryTopics"]
    }
    missing = [topic for topic in topics if topic not in existing]
    for topic in missing:
        _action(["gh", "repo", "edit", REPO, "--add-topic", topic], apply=apply)


def _sync_labels(labels: list[dict[str, str]], *, apply: bool) -> None:
    existing = {item["name"] for item in _json(["gh", "label", "list", "-R", REPO, "--limit", "200", "--json", "name"])}
    for label in labels:
        if label["name"] in existing:
            continue
        _action(
            [
                "gh",
                "label",
                "create",
                label["name"],
                "-R",
                REPO,
                "--color",
                label["color"],
                "--description",
                label["description"],
            ],
            apply=apply,
        )


def _sync_issues(issues: list[dict[str, Any]], *, apply: bool) -> dict[str, dict[str, Any]]:
    existing = {
        item["title"]: item
        for item in _json(["gh", "issue", "list", "-R", REPO, "--state", "all", "--limit", "200", "--json", "number,title,url"])
    }
    results: dict[str, dict[str, Any]] = {}
    for issue in issues:
        title = issue["title"]
        if title in existing:
            results[title] = existing[title]
            continue
        command = [
            "gh",
            "issue",
            "create",
            "-R",
            REPO,
            "--title",
            title,
            "--body",
            issue["body"],
        ]
        for label in issue["labels"]:
            command.extend(["--label", label])
        if apply:
            output = _run(command, capture=True).stdout.strip()
            results[title] = {"title": title, "url": output}
        else:
            _print_action(command)
    return results


def _pin_issues(issues: list[dict[str, Any]], issue_map: dict[str, dict[str, Any]], *, apply: bool) -> None:
    for issue in issues:
        if not issue.get("pinned"):
            continue
        title = issue["title"]
        issue_data = issue_map.get(title)
        if not issue_data:
            print(f"skip pin, issue not created yet: {title}")
            continue
        number = issue_data.get("number")
        if not number:
            print(f"pin manually after creation: {issue_data.get('url', title)}")
            continue
        issue_id = _json(["gh", "issue", "view", str(number), "-R", REPO, "--json", "id"])["id"]
        command = [
            "gh",
            "api",
            "graphql",
            "-f",
            "query=mutation($id:ID!){ pinIssue(input:{issueId:$id}) { issue { number } } }",
            "-f",
            f"id={issue_id}",
        ]
        _action(command, apply=apply)


def _action(command: list[str], *, apply: bool) -> None:
    if apply:
        _run(command, capture=False)
    else:
        _print_action(command)


def _print_action(command: list[str]) -> None:
    print("+ " + " ".join(_shell_quote(part) for part in command))


def _json(command: list[str]) -> Any:
    return json.loads(_run(command, capture=True).stdout)


def _run(command: list[str], *, capture: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def _shell_quote(value: str) -> str:
    if not value or any(char.isspace() or char in "\"'`$" for char in value):
        return "'" + value.replace("'", "'\"'\"'") + "'"
    return value


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        raise SystemExit(exc.returncode) from exc
