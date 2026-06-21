from __future__ import annotations

import re
import os
import subprocess
import base64
import json
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentpack.core import git


_GITHUB_URL_RE = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/\d+")
_HASH_REF_RE = re.compile(r"(?<![\w/.-])#\d+\b")
_GH_REF_RE = re.compile(r"\bGH-\d+\b", re.IGNORECASE)
_JIRA_REF_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")


@dataclass(frozen=True)
class IssueReference:
    ref: str
    kind: str = "unknown"
    source: str = "detected"
    title: str = ""
    state: str = ""
    url: str = ""
    labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ref": self.ref,
            "kind": self.kind,
            "source": self.source,
        }
        if self.title:
            payload["title"] = self.title
        if self.state:
            payload["state"] = self.state
        if self.url:
            payload["url"] = self.url
        if self.labels:
            payload["labels"] = self.labels
        return payload


def extract_issue_references(*texts: str | None) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for pattern in (_GITHUB_URL_RE, _HASH_REF_RE, _GH_REF_RE, _JIRA_REF_RE):
            for match in pattern.findall(text):
                ref = _normalize_reference(match)
                key = ref.lower()
                if key not in seen:
                    seen.add(key)
                    refs.append(ref)
    return refs


def extract_repo_issue_references(root: Path, *texts: str | None) -> list[str]:
    return [item.ref for item in collect_repo_issue_references(root, *texts)]


def collect_repo_issue_references(root: Path, *texts: str | None, enrich: bool = True) -> list[IssueReference]:
    branch = git.current_branch(root) if git.is_git_repo(root) else None
    commit_subjects = _recent_commit_subjects(root) if git.is_git_repo(root) else []
    refs = [
        _reference_from_value(ref, source="detected")
        for ref in extract_issue_references(*texts, branch, *commit_subjects)
    ]
    if enrich:
        refs.extend(_github_current_pr_references(root))
        refs.extend(_github_reference_metadata(root, refs))
        refs.extend(_jira_reference_metadata(refs))
    return _merge_issue_reference_objects(refs)


def merge_issue_references(values: Iterable[str]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in values:
        ref = _normalize_reference(str(value))
        if not ref:
            continue
        key = ref.lower()
        if key not in seen:
            seen.add(key)
            refs.append(ref)
    return refs


def merge_issue_reference_objects(values: Iterable[IssueReference | dict[str, Any]]) -> list[IssueReference]:
    refs: list[IssueReference] = []
    for value in values:
        if isinstance(value, IssueReference):
            refs.append(value)
        elif isinstance(value, dict):
            ref = str(value.get("ref") or "").strip()
            if ref:
                refs.append(IssueReference(
                    ref=ref,
                    kind=str(value.get("kind") or "unknown"),
                    source=str(value.get("source") or "detected"),
                    title=str(value.get("title") or ""),
                    state=str(value.get("state") or ""),
                    url=str(value.get("url") or ""),
                    labels=[str(item) for item in value.get("labels") or [] if isinstance(item, str)],
                ))
    return _merge_issue_reference_objects(refs)


def issue_reference_dicts(values: Iterable[IssueReference]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in _merge_issue_reference_objects(values)]


def _normalize_reference(value: str) -> str:
    return value.strip().rstrip(".,;:)]}")


def _reference_from_value(value: str, *, source: str) -> IssueReference:
    ref = _normalize_reference(value)
    lower = ref.lower()
    kind = "unknown"
    if "/pull/" in lower:
        kind = "github_pr"
    elif "/issues/" in lower or ref.startswith("#") or lower.startswith("gh-"):
        kind = "github_issue"
    elif _JIRA_REF_RE.fullmatch(ref):
        kind = "jira_issue"
    return IssueReference(ref=ref, kind=kind, source=source)


def _merge_issue_reference_objects(values: Iterable[IssueReference]) -> list[IssueReference]:
    merged: dict[str, IssueReference] = {}
    order: list[str] = []
    for item in values:
        if not item.ref:
            continue
        key = item.ref.lower()
        if key not in merged:
            merged[key] = item
            order.append(key)
            continue
        merged[key] = _prefer_reference(merged[key], item)
    return [merged[key] for key in order]


def _prefer_reference(current: IssueReference, candidate: IssueReference) -> IssueReference:
    return IssueReference(
        ref=current.ref,
        kind=candidate.kind if current.kind == "unknown" and candidate.kind != "unknown" else current.kind,
        source=candidate.source if current.source == "detected" and candidate.source != "detected" else current.source,
        title=current.title or candidate.title,
        state=current.state or candidate.state,
        url=current.url or candidate.url,
        labels=current.labels or candidate.labels,
    )


def _recent_commit_subjects(root: Path, limit: int = 5) -> list[str]:
    out = git._run(["git", "log", f"-{limit}", "--pretty=%s"], root)
    return [line.strip() for line in (out or "").splitlines() if line.strip()]


def _run_gh(root: Path, args: list[str]) -> dict[str, Any] | list[Any] | None:
    try:
        result = subprocess.run(
            ["gh", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "{}")
    except ValueError:
        return None


def _github_current_pr_references(root: Path) -> list[IssueReference]:
    payload = _run_gh(root, ["pr", "view", "--json", "number,title,state,url,labels,closingIssuesReferences"])
    if not isinstance(payload, dict) or not payload.get("number"):
        return []
    refs = [_reference_from_github_payload(payload, ref=f"PR #{payload['number']}", kind="github_pr", source="gh pr view")]
    for issue in payload.get("closingIssuesReferences") or []:
        if isinstance(issue, dict) and issue.get("number"):
            refs.append(_reference_from_github_payload(issue, ref=f"#{issue['number']}", kind="github_issue", source="gh pr view"))
    return refs


def _github_reference_metadata(root: Path, refs: list[IssueReference]) -> list[IssueReference]:
    enriched: list[IssueReference] = []
    for item in refs[:10]:
        number = _github_number(item.ref)
        if not number:
            continue
        command = "pr" if item.kind == "github_pr" or "/pull/" in item.ref.lower() else "issue"
        payload = _run_gh(root, [command, "view", number, "--json", "number,title,state,url,labels"])
        if isinstance(payload, dict) and payload.get("number"):
            ref = f"PR #{payload['number']}" if command == "pr" else f"#{payload['number']}"
            enriched.append(_reference_from_github_payload(payload, ref=ref, kind=f"github_{command}", source=f"gh {command} view"))
    return enriched


def _github_number(ref: str) -> str:
    pr_match = re.fullmatch(r"PR #(\d+)", ref, flags=re.IGNORECASE)
    if pr_match:
        return pr_match.group(1)
    if ref.startswith("#") and ref[1:].isdigit():
        return ref[1:]
    match = re.search(r"/(?:issues|pull)/(\d+)", ref)
    return match.group(1) if match else ""


def _reference_from_github_payload(payload: dict[str, Any], *, ref: str, kind: str, source: str) -> IssueReference:
    labels = [
        str(label.get("name"))
        for label in payload.get("labels") or []
        if isinstance(label, dict) and label.get("name")
    ]
    return IssueReference(
        ref=ref,
        kind=kind,
        source=source,
        title=str(payload.get("title") or ""),
        state=str(payload.get("state") or ""),
        url=str(payload.get("url") or ""),
        labels=labels[:10],
    )


def _jira_reference_metadata(refs: list[IssueReference]) -> list[IssueReference]:
    base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    if not base_url:
        return []
    enriched: list[IssueReference] = []
    for item in refs[:10]:
        if item.kind != "jira_issue" or not _JIRA_REF_RE.fullmatch(item.ref):
            continue
        payload = _jira_issue_payload(base_url, item.ref)
        if payload:
            fields = payload.get("fields") or {}
            status = fields.get("status") or {}
            enriched.append(IssueReference(
                ref=item.ref,
                kind="jira_issue",
                source="jira api",
                title=str(fields.get("summary") or ""),
                state=str(status.get("name") or ""),
                url=f"{base_url}/browse/{item.ref}",
                labels=[str(label) for label in fields.get("labels") or [] if isinstance(label, str)][:10],
            ))
    return enriched


def _jira_issue_payload(base_url: str, key: str) -> dict[str, Any] | None:
    url = f"{base_url}/rest/api/3/issue/{key}?fields=summary,status,labels"
    request = urllib.request.Request(url, headers=_jira_headers())
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError):
        return None


def _jira_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    bearer = os.environ.get("JIRA_BEARER_TOKEN", "")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
        return headers
    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")
    if email and token:
        raw = f"{email}:{token}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    return headers
