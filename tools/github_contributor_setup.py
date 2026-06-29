from __future__ import annotations

import argparse
import json
import re
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
    failures: list[str] = []

    _ensure_gh()
    if apply:
        permission = _viewer_permission()
        if permission not in {"ADMIN", "MAINTAIN"}:
            print(f"GitHub contributor setup requires admin or maintain permission; current permission is {permission}.")
            return 1
    _sync_labels(labels, apply=apply, failures=failures)
    created_or_existing = _sync_issues(issues, apply=apply, failures=failures)
    _pin_issues(issues, created_or_existing, apply=apply, failures=failures)
    _sync_topics(topics, apply=apply, failures=failures)

    mode = "applied" if apply else "dry-run"
    print(f"GitHub contributor setup {mode}.")
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1 if apply else 0
    return 0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_gh() -> None:
    _run(["gh", "auth", "status"], capture=True)


def _viewer_permission() -> str:
    data = _json(["gh", "repo", "view", REPO, "--json", "viewerPermission"])
    return str(data.get("viewerPermission") or "")


def _sync_topics(topics: list[str], *, apply: bool, failures: list[str]) -> None:
    existing = {
        item["name"]
        for item in _json(["gh", "repo", "view", REPO, "--json", "repositoryTopics"])["repositoryTopics"]
    }
    missing = [topic for topic in topics if topic not in existing]
    for topic in missing:
        _action(["gh", "repo", "edit", REPO, "--add-topic", topic], apply=apply, failures=failures)


def _sync_labels(labels: list[dict[str, str]], *, apply: bool, failures: list[str]) -> None:
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
            failures=failures,
        )


def _sync_issues(issues: list[dict[str, Any]], *, apply: bool, failures: list[str]) -> dict[str, dict[str, Any]]:
    existing = {
        item["title"]: item
        for item in _json(["gh", "issue", "list", "-R", REPO, "--state", "all", "--limit", "200", "--json", "number,title,url,labels"])
    }
    results: dict[str, dict[str, Any]] = {}
    for issue in issues:
        title = issue["title"]
        if title in existing:
            results[title] = existing[title]
            _sync_issue_labels(existing[title], issue["labels"], apply=apply, failures=failures)
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
            try:
                output = _run(command, capture=True).stdout.strip()
                number = _issue_number_from_url(output)
                results[title] = {"title": title, "url": output, "number": number}
                if number is not None:
                    _sync_issue_labels(results[title], issue["labels"], apply=apply, failures=failures)
            except subprocess.CalledProcessError as exc:
                failures.append(_format_failure(command, exc))
        else:
            _print_action(command)
    return results


def _sync_issue_labels(issue: dict[str, Any], labels: list[str], *, apply: bool, failures: list[str]) -> None:
    number = issue.get("number")
    if number is None:
        return
    existing = {label["name"] for label in issue.get("labels") or [] if isinstance(label, dict)}
    missing = [label for label in labels if label not in existing]
    if not missing:
        return
    command = ["gh", "issue", "edit", str(number), "-R", REPO]
    for label in missing:
        command.extend(["--add-label", label])
    _action(command, apply=apply, failures=failures)


def _issue_number_from_url(url: str) -> int | None:
    match = re.search(r"/issues/(\d+)$", url)
    return int(match.group(1)) if match else None


def _pin_issues(
    issues: list[dict[str, Any]],
    issue_map: dict[str, dict[str, Any]],
    *,
    apply: bool,
    failures: list[str],
) -> None:
    pinned = _pinned_issue_numbers() if apply else set()
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
        if int(number) in pinned:
            continue
        try:
            issue_id = _json(["gh", "issue", "view", str(number), "-R", REPO, "--json", "id"])["id"]
        except subprocess.CalledProcessError as exc:
            failures.append(_format_failure(["gh", "issue", "view", str(number), "-R", REPO, "--json", "id"], exc))
            continue
        command = [
            "gh",
            "api",
            "graphql",
            "-f",
            "query=mutation($id:ID!){ pinIssue(input:{issueId:$id}) { issue { number } } }",
            "-f",
            f"id={issue_id}",
        ]
        _action(command, apply=apply, failures=failures)


def _pinned_issue_numbers() -> set[int]:
    data = _json(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            "query=query($owner:String!, $repo:String!){ repository(owner:$owner,name:$repo){ pinnedIssues(first:10){ nodes{ issue{ number } } } } }",
            "-f",
            "owner=vishal2612200",
            "-f",
            "repo=agentpack",
        ]
    )
    nodes = data["data"]["repository"]["pinnedIssues"]["nodes"]
    return {int(node["issue"]["number"]) for node in nodes}


def _action(command: list[str], *, apply: bool, failures: list[str]) -> None:
    if apply:
        try:
            _run(command, capture=True)
        except subprocess.CalledProcessError as exc:
            failures.append(_format_failure(command, exc))
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


def _format_failure(command: list[str], exc: subprocess.CalledProcessError) -> str:
    detail = (exc.stderr or exc.stdout or "").strip()
    rendered = " ".join(_shell_quote(part) for part in command)
    return f"{rendered} :: {detail}" if detail else rendered


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        raise SystemExit(exc.returncode) from exc
