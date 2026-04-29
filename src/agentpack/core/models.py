from pathlib import Path
from typing import Literal
from pydantic import BaseModel


class ScanResult(BaseModel):
    packable: list["FileInfo"]
    ignored: list["FileInfo"]
    binary: list["FileInfo"]

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
    schema_version: int = 1
    summary: str
    imports: list[str] = []
    symbols: list[Symbol] = []


class SelectedFile(BaseModel):
    path: str
    language: str | None = None
    score: float
    include_mode: Literal["full", "symbols", "summary"]
    reasons: list[str]
    content: str | None = None
    summary: str | None = None
    symbols: list[Symbol] = []
    redaction_warnings: list[str] = []


class Receipt(BaseModel):
    path: str
    action: Literal["included", "excluded", "summarized"]
    reason: str


class ContextPack(BaseModel):
    task: str
    agent: str
    mode: Literal["minimal", "balanced", "deep"]
    budget: int
    token_estimate: int
    raw_repo_tokens: int
    after_ignore_tokens: int
    estimated_savings_percent: float
    changed_files: list[str]
    selected_files: list[SelectedFile]
    receipts: list[Receipt]
    redaction_warnings: list[str] = []
    stale: bool = False


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
