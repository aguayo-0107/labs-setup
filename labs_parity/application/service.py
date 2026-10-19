"""Use case: compare two environments and apply the stop policy."""

from __future__ import annotations

from labs_runtime.ports.outbound import OutputSinkPort

from ..domain.errors import EnvironmentsDiffer
from ..domain.freeze import compare, parse_freeze
from ..domain.models import ParityReport, PythonEnvironment
from ..ports.inbound import CheckParityUseCase
from ..ports.outbound import PackageInventoryPort


class CheckParityService(CheckParityUseCase):
    def __init__(self, inventory: PackageInventoryPort, sink: OutputSinkPort) -> None:
        self._inventory = inventory
        self._sink = sink

    def __call__(self, left: PythonEnvironment, right: PythonEnvironment) -> ParityReport:
        shared, differences = compare(
            parse_freeze(self._inventory.freeze(left)), parse_freeze(self._inventory.freeze(right))
        )
        report = ParityReport(left, right, shared, differences)
        if not report.equal:
            raise EnvironmentsDiffer(report)
        self._sink.write(
            f"Same versions in {left.describe()} and {right.describe()}: "
            f"{len(shared)} shared packages ({', '.join(shared)})\n"
        )
        return report
