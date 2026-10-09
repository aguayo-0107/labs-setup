"""Command-line adapter and composition root.

    uv run python -m labs_audit

Read-only. Exit status 0 only when every notebook pair and every Spark JAR
passes every rule.
"""

from __future__ import annotations

from pathlib import Path

from ...application.service import LabsAuditService
from ...ports.inbound import AuditLabsUseCase
from ..outbound.filesystem import FileJarStore, FileNotebookSource

ROOT = Path(__file__).resolve().parents[3]


def build_audit(root: Path) -> AuditLabsUseCase:
    return LabsAuditService(FileNotebookSource(root), FileJarStore(root))


def main(root: Path = ROOT) -> int:
    report = build_audit(root).audit()
    for finding in report.findings:
        print(finding)
    print(
        f"{len(report.notebooks)} notebooks, {len(report.jars)} Spark JARs, "
        f"{len(report.findings)} findings -> {'PASS' if report.passed else 'FAIL'}"
    )
    return 0 if report.passed else 1
