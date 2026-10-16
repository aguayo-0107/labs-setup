"""Immutable values describing a query execution and its results."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class QueryState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"

    @property
    def finished(self) -> bool:
        return self in (QueryState.SUCCEEDED, QueryState.FAILED)


class StatementType(str, Enum):
    DDL = "DDL"
    DML = "DML"
    UTILITY = "UTILITY"


@dataclass(frozen=True)
class S3Location:
    bucket: str
    key: str

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class QueryResult:
    """Columns plus rows already rendered as Athena renders them (strings or None)."""

    columns: tuple[Column, ...]
    rows: tuple[tuple[str | None, ...], ...]


@dataclass(frozen=True)
class StartQueryRequest:
    query: str
    output_location: str
    database: str


@dataclass(frozen=True)
class QueryExecution:
    query_id: str
    query: str
    statement_type: StatementType
    database: str
    output_location: str
    state: QueryState
    submitted_at: datetime
    completed_at: datetime | None = None
    reason: str | None = None
    result: QueryResult | None = None
    result_file: S3Location | None = None

    def running(self) -> QueryExecution:
        return replace(self, state=QueryState.RUNNING)

    def succeeded(self, result: QueryResult, result_file: S3Location, at: datetime) -> QueryExecution:
        return replace(self, state=QueryState.SUCCEEDED, result=result, result_file=result_file, completed_at=at)

    def failed(self, reason: str, at: datetime) -> QueryExecution:
        return replace(self, state=QueryState.FAILED, reason=reason, completed_at=at)


@dataclass(frozen=True)
class ResultPage:
    columns: tuple[Column, ...]
    rows: tuple[tuple[str | None, ...], ...]
    next_token: str | None
