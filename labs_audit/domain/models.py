"""Domain models for the structural audit of the lab notebooks."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Cell:
    cell_type: str
    source: str
    tags: tuple[str, ...] = ()
    outputs: int = 0
    execution_count: int | None = None


@dataclass(frozen=True)
class Notebook:
    """One notebook as committed (`.ipynb`) or as derived from its `.py` source."""

    path: str
    cells: tuple[Cell, ...]
    kernel: str | None = None

    @property
    def is_infra(self) -> bool:
        return "_infra" in self.path


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.path}: {self.detail}"


@dataclass
class AuditReport:
    notebooks: list[str] = field(default_factory=list)
    jars: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings and bool(self.notebooks)
