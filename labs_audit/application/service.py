"""Use case: structural audit of every lab notebook pair and the Spark JARs."""

from __future__ import annotations

from ..domain import rules
from ..domain.models import AuditReport
from ..ports.inbound import AuditLabsUseCase
from ..ports.outbound import JarStorePort, NotebookSourcePort


class LabsAuditService(AuditLabsUseCase):
    def __init__(self, notebooks: NotebookSourcePort, jars: JarStorePort) -> None:
        self._notebooks = notebooks
        self._jars = jars

    def audit(self) -> AuditReport:
        report = AuditReport()
        for stem in self._notebooks.pairs():
            committed = self._notebooks.committed(stem)
            report.notebooks.append(committed.path)
            for rule in rules.NOTEBOOK_RULES:
                report.findings.extend(rule(committed))
            report.findings.extend(rules.in_sync(committed, self._notebooks.canonical(stem)))
        digests = self._jars.digests()
        report.jars.extend(sorted(name for name, digest in digests.items() if digest))
        report.findings.extend(rules.jar_checksums(digests))
        return report
