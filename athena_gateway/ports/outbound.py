"""Outbound ports: SQL engine, result storage, execution records, and runtime."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime

from ..domain.models import QueryExecution, QueryResult, S3Location


class SqlEnginePort(ABC):
    @abstractmethod
    def execute(self, query: str, database: str) -> QueryResult:
        """Run one statement in `database`; raise any exception on failure."""


class ResultStorePort(ABC):
    @abstractmethod
    def save(self, location: S3Location, content: bytes) -> None:
        """Write the result file of a query."""


class ExecutionRepositoryPort(ABC):
    @abstractmethod
    def put(self, execution: QueryExecution) -> None:
        """Insert or replace the record of an execution."""

    @abstractmethod
    def get(self, query_id: str) -> QueryExecution | None:
        """The record, or None if the id was never issued."""


class TaskRunnerPort(ABC):
    @abstractmethod
    def submit(self, task: Callable[[], None]) -> None:
        """Run `task` later, in submission order."""


class ClockPort(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """Current time, timezone-aware."""


class IdGeneratorPort(ABC):
    @abstractmethod
    def new_id(self) -> str:
        """A fresh, unique QueryExecutionId."""
