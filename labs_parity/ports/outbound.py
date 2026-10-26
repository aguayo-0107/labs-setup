"""Outbound port: where the installed packages are read from."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.models import PythonEnvironment


class PackageInventoryPort(ABC):
    @abstractmethod
    def freeze(self, environment: PythonEnvironment) -> str:
        """Return the `pip freeze` output of `environment`."""
