"""Inbound port: the three Athena operations a client can drive."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.models import QueryExecution, ResultPage, StartQueryRequest


class AthenaQueryApiPort(ABC):
    @abstractmethod
    def start_query_execution(self, request: StartQueryRequest) -> str:
        """Queue the query and return its QueryExecutionId immediately."""

    @abstractmethod
    def get_query_execution(self, query_id: str) -> QueryExecution:
        """Current state of a query; InvalidRequestError if the id is unknown."""

    @abstractmethod
    def get_query_results(self, query_id: str, max_results: int | None, next_token: str | None) -> ResultPage:
        """One page of results of a SUCCEEDED query; InvalidRequestError otherwise."""
