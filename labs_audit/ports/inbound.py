"""Inbound port: the use case this package offers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.models import AuditReport


class AuditLabsUseCase(ABC):
    @abstractmethod
    def audit(self) -> AuditReport:
        """Apply every structural rule to every lab notebook and the Spark JARs."""
