"""Inbound port: what the infrastructure notebook asks for."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.models import ParityReport, PythonEnvironment


class CheckParityUseCase(ABC):
    @abstractmethod
    def __call__(self, left: PythonEnvironment, right: PythonEnvironment) -> ParityReport:
        """Compare the packages installed in both environments; raise
        EnvironmentsDiffer when any shared package has different versions."""
