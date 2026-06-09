from pathlib import Path
from typing import Literal
from typing import Any
from pydantic import BaseModel, Field

SUMMARY_SCHEMA_VERSION = 2


class ScanResult(BaseModel):
    packable: list["FileInfo"]
    ignored: list["FileInfo"]
    binary: list["FileInfo"]
    scan_mode: Literal["full", "incremental"] = "full"
    rehashed_count: int = 0
    reused_count: int = 0
    full_scan_reason: str | None = None

    @property
    def all_files(self) -> list["FileInfo"]:
        return self.packable + self.ignored + self.binary


class FileInfo(BaseModel):
    path: str
    abs_path: Path
    language: str | None = None
    size_bytes: int
    estimated_tokens: int
    hash: str | None = None
    ignored: bool = False
    binary: bool = False
    too_large: bool = False
    content: str | None = None  # cached at scan time; avoids re-reads in scoring/selection

    model_config = {"arbitrary_types_allowed": True}


class Symbol(BaseModel):
    name: str
    kind: Literal["class", "function", "method", "variable"]
    start_line: int
    end_line: int
    signature: str | None = None
    summary: str | None = None
    body: str | None = None  # source text captured at extraction time; no re-read needed


class FileSummary(BaseModel):
    path: str
    hash: str
    language: str | None = None
    provider: str = "offline"
    schema_version: int = SUMMARY_SCHEMA_VERSION
    summary: str
    imports: list[str] = Field(default_factory=list)
    symbols: list[Symbol] = Field(default_factory=list)
    domain: str | None = None
    role: str | None = None
    entrypoints: list[str] = Field(default_factory=list)
    defines: list[str] = Field(default_factory=list)
    calls: list[str] = Field(default_factory=list)
    reads_env: list[str] = Field(default_factory=list)
    reads_files: list[str] = Field(default_factory=list)
    writes_files: list[str] = Field(default_factory=list)
    external_systems: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    failure_hints: list[str] = Field(default_factory=list)
    ranking_keywords: list[str] = Field(default_factory=list)
    related_hints: list[str] = Field(default_factory=list)
    public_api: list[str] = Field(default_factory=list)
    naming_signals: list[str] = Field(default_factory=list)
    naming_keywords: list[str] = Field(default_factory=list)
    error_paths: list[str] = Field(default_factory=list)
    test_hints: list[str] = Field(default_factory=list)


class SelectedFile(BaseModel):
    path: str
    language: str | None = None
    score: float
    include_mode: Literal["full", "diff", "symbols", "skeleton", "summary"]
    reasons: list[str]
    content: str | None = None
    summary: str | None = None
    symbols: list[Symbol] = []
    redaction_warnings: list[str] = []


class Receipt(BaseModel):
    path: str
    action: Literal["included", "excluded", "summarized"]
    reason: str


class OmittedRelevantFile(BaseModel):
    path: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    estimated_tokens: int
    suggested_mode: Literal["full", "diff", "symbols", "skeleton", "summary"]
    omission_reason: str = "budget exhausted"
    risk: Literal["high", "medium", "low"] = "low"


class ContextPack(BaseModel):
    task: str
    agent: str
    mode: Literal["minimal", "balanced", "deep"]
    task_class: str = "general"
    budget: int
    token_estimate: int
    raw_repo_tokens: int
    after_ignore_tokens: int
    estimated_savings_percent: float
    repo_map: str = ""
    delta_summary: str = ""
    agent_lessons: str = ""
    changed_files: list[str]
    selected_files: list[SelectedFile]
    receipts: list[Receipt]
    omitted_relevant_files: list[OmittedRelevantFile] = Field(default_factory=list)
    redaction_warnings: list[str] = []
    stale: bool = False
    freshness: dict[str, Any] = Field(default_factory=dict)
    freshness_warnings: list[str] = Field(default_factory=list)
    execution_state: dict[str, Any] = Field(default_factory=dict)
    concurrent_context: dict[str, Any] = Field(default_factory=dict)


class DependencyNode(BaseModel):
    path: str
    imports: list[str] = []
    imported_by: list[str] = []
    tests: list[str] = []


class DependencyGraph(BaseModel):
    nodes: dict[str, DependencyNode] = {}

    def get(self, path: str) -> DependencyNode:
        return self.nodes.get(path, DependencyNode(path=path))

    def __getitem__(self, path: str) -> DependencyNode:
        return self.nodes[path]

    def __setitem__(self, path: str, node: DependencyNode) -> None:
        self.nodes[path] = node

    def __contains__(self, path: object) -> bool:
        return path in self.nodes

    def __iter__(self):  # type: ignore[override]
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)

    def items(self):  # type: ignore[override]
        return self.nodes.items()
