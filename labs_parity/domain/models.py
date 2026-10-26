"""Value objects of a parity check."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PythonEnvironment:
    """A Python interpreter inside a Docker image."""

    image: str
    python: str

    def describe(self) -> str:
        return f"{self.image} ({self.python})"


@dataclass(frozen=True)
class VersionDifference:
    package: str
    left: str
    right: str


@dataclass(frozen=True)
class ParityReport:
    left: PythonEnvironment
    right: PythonEnvironment
    shared: tuple[str, ...]
    differences: tuple[VersionDifference, ...]

    @property
    def equal(self) -> bool:
        return not self.differences
