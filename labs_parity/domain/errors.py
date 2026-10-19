"""Failure raised when two environments disagree."""

from __future__ import annotations

from .models import ParityReport


class EnvironmentsDiffer(RuntimeError):
    def __init__(self, report: ParityReport) -> None:
        lines = [f"{d.package}: {d.left} vs {d.right}" for d in report.differences]
        super().__init__(
            f"{report.left.describe()} and {report.right.describe()} differ in "
            f"{len(report.differences)} shared package(s): " + "; ".join(lines)
        )
        self.report = report
