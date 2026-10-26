"""Outbound ports: where notebooks and JARs come from."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from ..domain.models import Notebook


class NotebookSourcePort(ABC):
    @abstractmethod
    def pairs(self) -> tuple[str, ...]:
        """Relative paths (without extension) of every `.py`/`.ipynb` lab pair."""

    @abstractmethod
    def committed(self, stem: str) -> Notebook:
        """The `.ipynb` as it is on disk."""

    @abstractmethod
    def canonical(self, stem: str) -> Notebook:
        """The notebook jupytext derives from the canonical `.py`."""


class JarStorePort(ABC):
    @abstractmethod
    def digests(self) -> Mapping[str, str | None]:
        """SHA-256 of each expected Spark JAR, None when the file is missing."""
